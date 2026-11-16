"""Módulo de ciclo de vida de bugs guiado por SDD (Spec-Driven Bugfix Lifecycle).

Este módulo implementa a especificação técnica formalizada em
docs/architecture/bug-lifecycle-sdd-flow.md, incluindo estruturação de planos
de bug, persistência de evidências de nuvem e geração de testes TDD Fail-First.
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import redis
import yaml
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from harness_state.agents import AgentRunner
from harness_state.config import get_active_config
from harness_state.sensors.prompt_sensor import discover_prompts_in_repository
from harness_state.spec.lifecycle import locate_repo_dir
from harness_state.workspace import find_manifest_path


@dataclass
class BugPlan:
    """Estrutura formal de especificação de um defeito no ecossistema SDD.

    Attributes:
        title: Título sintético da Issue do defeito.
        summary: Resumo executivo da falha.
        observed_behavior: Comportamento observado anômalo.
        expected_behavior: Comportamento esperado conforme a regra de negócio.
        affected_spoke: Repositório ou componente suspeito / identificado.
        affected_capability: Capacidade DDD afetada.
        runtime_contract: Contrato de runtime violado.
        reproduction_steps: Lista de passos determinísticos de reprodução.
        test_file_path: Caminho relativo do arquivo de teste de reprodução.
        test_function_name: Nome da função de teste unitário.
        business_rule: Regra de negócio obrigatória para o docstring do teste.
        selected_cloud_log: Evidência de log curada do Cloud Logging.
        intake_prompt: Prompt original informado pelo operador / usuário.
        issue_id: Identificador numérico da Issue (se já atribuído).
        linked_spec: Identificador opcional da especificação vinculada.
        spec_approved: Flag indicando aprovação da especificação no Gate 2.
        prompts: Lista de prompts governados associados ao defeito.
        origin_spoke: Spoke onde o incidente foi originalmente detectado.
        wave: Onda de execução topológica (1 para libs/SDKs, 2+ para consumidores).
        depends_on: Lista de dependências diretas mapeadas pelo manifesto.
    """

    title: str
    summary: str
    observed_behavior: str
    expected_behavior: str
    affected_spoke: str
    affected_capability: str
    runtime_contract: str
    reproduction_steps: list[str] = field(default_factory=list)
    test_file_path: str = ""
    test_function_name: str = ""
    business_rule: str = ""
    selected_cloud_log: str | None = None
    intake_prompt: str = ""
    issue_id: int | None = None
    linked_spec: str | None = None
    spec_approved: bool = False
    prompts: list[str] = field(default_factory=list)
    origin_spoke: str = ""
    wave: int = 1
    depends_on: list[str] = field(default_factory=list)


def compile_bug_issue_boundaries_markdown(plan: BugPlan) -> str:
    """Compila a seção de fronteiras arquiteturais e topológicas do defeito.

    Args:
        plan: Instância do BugPlan com a especificação do defeito.

    Returns:
        Bloco em Markdown descrevendo spoke, onda, dependências e contratos.
    """
    origin = getattr(plan, "origin_spoke", "")
    affected = getattr(plan, "affected_spoke", "")
    origin_line = (
        f"- **Spoke Originário:** `{origin}`\n"
        if origin and origin != affected and isinstance(origin, str)
        else ""
    )
    raw_wave = getattr(plan, "wave", 1)
    is_multi_wave = isinstance(raw_wave, int) and raw_wave > 1
    wave_line = f"- **Onda Topológica:** `Wave {raw_wave}`\n" if is_multi_wave else ""
    raw_deps = getattr(plan, "depends_on", [])
    deps_line = ""
    if isinstance(raw_deps, list) and raw_deps:
        deps_str = ", ".join(f"`{d}`" for d in raw_deps)
        deps_line = f"- **Depende de:** {deps_str}\n"

    spec_line = (
        f"- **Especificação Vinculada:** `{plan.linked_spec}`\n"
        if plan.linked_spec
        else ""
    )
    prompts_block = ""
    if plan.prompts:
        prompts_list_str = ", ".join(f"`{p}`" for p in plan.prompts)
        prompts_block = (
            "## 📝 Prompts de IA Sob Governança (Langfuse)\n"
            f"- **Prompts Afetados:** {prompts_list_str}\n\n"
        )

    return (
        "## 🎯 Fronteiras Arquiteturais & Capacidades DDD Afetadas\n"
        f"- **Spoke Afetado:** `{plan.affected_spoke}`\n"
        f"{origin_line}"
        f"{wave_line}"
        f"{deps_line}"
        f"- **Business Capability:** `{plan.affected_capability}`\n"
        f"- **Runtime Contract:** `{plan.runtime_contract}`\n"
        f"{spec_line}\n"
        f"{prompts_block}"
    )


def compile_bug_issue_markdown(plan: BugPlan) -> str:
    """Compila a especificação do plano de bug em Markdown canônico para a Issue.

    Args:
        plan: Instância do BugPlan a ser formatada.

    Returns:
        String contendo o corpo integral da Issue em Markdown padronizado.
    """
    steps_markdown = "\n".join(
        f"{idx + 1}. {step}" for idx, step in enumerate(plan.reproduction_steps)
    )
    if not steps_markdown:
        steps_markdown = "1. Reprodução guiada pelo teste unitário formal."

    log_block = ""
    if plan.selected_cloud_log:
        log_block = (
            "## ☁️ Evidência Selecionada no Google Cloud Logging (GCP)\n\n"
            "```json\n"
            f"{plan.selected_cloud_log.strip()}\n"
            "```\n\n"
        )

    summary_tag = (
        "<details>\n"
        "<summary>💬 Transcrição do Diálogo de Elicitação"
        " (Prompt Intake Trace)</summary>\n\n"
    )

    title_header = f"# {plan.title}\n\n" if plan.title else ""
    boundaries_block = compile_bug_issue_boundaries_markdown(plan)

    clean_rule = (
        plan.business_rule
        or "O sistema deve cumprir as garantias do contrato de negócio."
    )
    while clean_rule.startswith("Business Rule:"):
        clean_rule = clean_rule[len("Business Rule:") :].strip()

    return (
        "<!-- flywheel:bug-plan:v1 -->\n"
        f"{title_header}"
        f"## 📋 Sumário Executivo do Defeito\n{plan.summary}\n\n"
        "## 🔍 Sintomas Observados vs. Comportamento Esperado\n"
        f"- **Comportamento Observado:** {plan.observed_behavior}\n"
        f"- **Comportamento Esperado:** {plan.expected_behavior}\n\n"
        f"{log_block}"
        f"{boundaries_block}"
        "## 🔬 Passos Determinísticos de Reprodução\n"
        f"{steps_markdown}\n\n"
        "## 🧪 Especificação do Teste TDD (Fail-First Contract)\n"
        f"- **Arquivo Alvo:** `{plan.test_file_path}`\n"
        f"- **Nome da Função de Teste:** `{plan.test_function_name}`\n"
        "- **Docstring Mandatória:**\n"
        "  ```python\n"
        f'  """Business Rule: {clean_rule}"""\n'
        "  ```\n\n"
        f"{summary_tag}"
        f'> **Prompt Original:** "{plan.intake_prompt}"\n'
        "</details>\n"
    )


def parse_bug_issue_prompts_line(stripped: str) -> list[str] | None:
    """Extrai a lista de prompts governados de uma linha de metadado de Issue.

    Args:
        stripped: Linha do Markdown sem espaços nas bordas.

    Returns:
        Lista de nomes de prompts ou None se a linha não for de prompts.
    """
    prefixes = (
        "- **Prompts Afetados:**",
        "- **Prompts Governados:**",
        "- **Prompts:**",
    )
    for pfx in prefixes:
        if stripped.startswith(pfx):
            raw_prompts = stripped[len(pfx) :].strip()
            return [
                p.strip().strip("`")
                for p in raw_prompts.split(",")
                if p.strip().strip("`")
            ]
    return None


def apply_bug_issue_topology_metadata(plan: BugPlan, stripped: str) -> bool:
    """Extrai metadados de onda topológica e dependências de uma linha de Issue.

    Args:
        plan: Instância mutável de BugPlan.
        stripped: Linha do Markdown sem espaços nas bordas.

    Returns:
        True se a linha continha metadados de topologia, False caso contrário.
    """
    if stripped.startswith("- **Onda Topológica:**"):
        raw_wave = stripped[len("- **Onda Topológica:**") :].replace("`", "").strip()
        digits = re.findall(r"\d+", raw_wave)
        if digits:
            plan.wave = int(digits[0])
        return True

    if stripped.startswith("- **Depende de:**"):
        raw_deps = stripped[len("- **Depende de:**") :].strip()
        plan.depends_on = [
            d.strip().strip("`") for d in raw_deps.split(",") if d.strip().strip("`")
        ]
        return True

    return False


def apply_bug_issue_metadata_line(plan: BugPlan, stripped: str) -> None:
    """Atualiza o `BugPlan` com base em uma linha de metadado chave-valor.

    Args:
        plan: Instância mutável de `BugPlan`.
        stripped: Linha do Markdown sem espaços nas bordas.
    """
    prompts = parse_bug_issue_prompts_line(stripped)
    if prompts is not None:
        plan.prompts = prompts
        return

    if apply_bug_issue_topology_metadata(plan, stripped):
        return

    simple_prefix_map: list[tuple[str, str, bool]] = [
        ("- **Comportamento Observado:**", "observed_behavior", False),
        ("- **Comportamento Esperado:**", "expected_behavior", False),
        ("- **Spoke Afetado:**", "affected_spoke", True),
        ("- **Spoke Originário:**", "origin_spoke", True),
        ("- **Business Capability:**", "affected_capability", True),
        ("- **Runtime Contract:**", "runtime_contract", True),
        ("- **Especificação Vinculada:**", "linked_spec", True),
        ("- **Arquivo Alvo:**", "test_file_path", True),
        ("- **Nome da Função de Teste:**", "test_function_name", True),
    ]
    for prefix, attr_name, strip_backticks in simple_prefix_map:
        if not stripped.startswith(prefix):
            continue
        val = stripped[len(prefix) :]
        if strip_backticks:
            val = val.replace("`", "")
        setattr(plan, attr_name, val.strip())
        return

    if '"""Business Rule:' in stripped:
        plan.business_rule = (
            stripped.replace('"""Business Rule:', "").replace('"""', "").strip()
        )
    elif stripped.startswith('> **Prompt Original:** "'):
        plan.intake_prompt = stripped.replace('> **Prompt Original:** "', "").rstrip(
            '"'
        )


def process_bug_issue_section_line(
    line: str,
    stripped: str,
    plan: BugPlan,
    in_summary: bool,
    in_log: bool,
    summary_lines: list[str],
    log_lines: list[str],
) -> tuple[bool, bool, bool]:
    """Processa cabeçalhos, seção de sumário e bloco de log JSON de uma Issue.

    Args:
        line: Linha original da Issue.
        stripped: Linha sem espaços nas bordas.
        plan: Instância mutável de `BugPlan`.
        in_summary: Estado atual de leitura do sumário.
        in_log: Estado atual de leitura do bloco JSON de log.
        summary_lines: Lista acumuladora de linhas do sumário.
        log_lines: Lista acumuladora de linhas de log.

    Returns:
        Tupla `(handled, new_in_summary, new_in_log)`.
    """
    if stripped.startswith("# ") and not stripped.startswith("## "):
        plan.title = stripped[2:].strip()
        return True, in_summary, in_log
    if stripped == "## 📋 Sumário Executivo do Defeito":
        return True, True, in_log
    if in_summary:
        if stripped.startswith(("## ", "<!--")):
            plan.summary = " ".join(summary_lines).strip()
            in_summary = False
        elif stripped:
            summary_lines.append(stripped)
            return True, in_summary, in_log

    if stripped == "```json":
        return True, in_summary, True
    if stripped == "```" and in_log:
        plan.selected_cloud_log = "\n".join(log_lines)
        return True, in_summary, False
    if in_log:
        log_lines.append(line)
        return True, in_summary, in_log

    return False, in_summary, in_log


def parse_bug_issue_markdown(markdown_content: str) -> BugPlan:
    """Extrai os dados de um BugPlan a partir do Markdown de uma Issue do GitHub.

    Args:
        markdown_content: Conteúdo em Markdown da Issue.

    Returns:
        Instância reconstituída de BugPlan.
    """
    plan = BugPlan(
        title="",
        summary="",
        observed_behavior="",
        expected_behavior="",
        affected_spoke="",
        affected_capability="",
        runtime_contract="",
    )
    in_log = False
    in_summary = False
    log_lines: list[str] = []
    summary_lines: list[str] = []

    for line in markdown_content.splitlines():
        stripped = line.strip()
        handled, in_summary, in_log = process_bug_issue_section_line(
            line, stripped, plan, in_summary, in_log, summary_lines, log_lines
        )
        if not handled:
            apply_bug_issue_metadata_line(plan, stripped)

    if in_summary and summary_lines:
        plan.summary = " ".join(summary_lines).strip()

    if not plan.origin_spoke and plan.affected_spoke:
        plan.origin_spoke = plan.affected_spoke

    return plan


def calculate_spoke_wave_recursive(
    spoke_name: str, dep_map: dict[str, list[str]], visited: set[str]
) -> int:
    """Calcula recursivamente a onda topológica de um spoke a partir de dependências.

    Args:
        spoke_name: Nome limpo do spoke.
        dep_map: Mapeamento de spokes para suas dependências.
        visited: Conjunto de nós já visitados para evitar ciclos.

    Returns:
        Número da onda (1 para base, 2+ para consumidores).
    """
    if spoke_name in visited:
        return 1
    visited.add(spoke_name)
    deps = dep_map.get(spoke_name, [])
    if not deps:
        return 1
    return 1 + max(
        (calculate_spoke_wave_recursive(dep, dep_map, visited) for dep in deps),
        default=0,
    )


def build_spoke_dependency_map(
    repos: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Constrói o mapeamento bidirecional de nomes/slugs para dependências limpas.

    Args:
        repos: Lista de dicionários de repositórios extraídos do manifesto.

    Returns:
        Dicionário associando nomes e slugs às suas dependências.
    """
    dep_map: dict[str, list[str]] = {}
    for entry in repos:
        name = entry.get("name", "")
        slug = entry.get("repo", "")
        deps = entry.get("depends_on", []) or []
        clean_deps = [d.split("/")[-1].strip() for d in deps if d]
        if name:
            dep_map[name] = clean_deps
        if slug:
            dep_map[slug] = clean_deps
            dep_map[slug.split("/")[-1]] = clean_deps
    return dep_map


def resolve_spoke_wave_and_dependencies(
    spoke: str, workspace_root: Path | None = None
) -> tuple[int, list[str]]:
    """Calcula a onda topológica e as dependências diretas de um spoke no manifesto.

    Args:
        spoke: Nome ou slug do spoke afetado (ex: 'customer-support-vehicles').
        workspace_root: Diretório opcional da raiz do workspace.

    Returns:
        Tupla contendo `(wave, direct_dependencies)`.
    """
    if not spoke or spoke == "unknown":
        return 1, []

    manifest_path = find_manifest_path(workspace_root=workspace_root)
    if not manifest_path or not manifest_path.is_file():
        return 1, []

    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return 1, []

    repos = data.get("repositories", [])
    dep_map = build_spoke_dependency_map(repos)

    clean_spoke = spoke.split("/")[-1].strip()
    direct_deps = dep_map.get(spoke, []) or dep_map.get(clean_spoke, [])

    wave = calculate_spoke_wave_recursive(clean_spoke, dep_map, set())
    return wave, direct_deps


def is_ai_agent_spoke(spoke: str, manifest_path: Path | None) -> bool:
    """Verifica se o spoke possui o papel 'ai-agent' no manifesto corporativo.

    Args:
        spoke: Nome ou identificador do repositório/spoke.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        True se o papel configurado for 'ai-agent', False caso contrário.
    """
    if not manifest_path or not manifest_path.is_file():
        return False
    try:
        data = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return False

    clean_spoke = spoke.split("/")[-1].strip()
    for repo_item in data.get("repositories", []):
        if not isinstance(repo_item, dict):
            continue
        repo_name = str(repo_item.get("repo", "")).split("/")[-1].strip()
        if repo_name == clean_spoke:
            return repo_item.get("role") == "ai-agent"
    return False


def bug_plan_mentions_prompts(plan: BugPlan) -> bool:
    """Verifica se os campos textuais do BugPlan mencionam termos de prompts.

    Args:
        plan: Instância do BugPlan inspecionada.

    Returns:
        True se contiver termos relacionados a instruções de prompts ou Langfuse.
    """
    combined = " ".join(
        [
            plan.intake_prompt or "",
            plan.summary or "",
            plan.observed_behavior or "",
            plan.expected_behavior or "",
        ]
    )
    return bool(
        re.search(r"\bprompts?\.py\b", combined, re.IGNORECASE)
        or re.search(r"\binstruction\b", combined, re.IGNORECASE)
        or re.search(r"\blangfuse\b", combined, re.IGNORECASE)
    )


def discover_prompts_for_bug_spoke(
    spoke: str,
    workspace_root: Path,
    manifest: Path | None,
) -> list[str]:
    """Descobre prompts em um spoke do bug caso o diretório exista.

    Args:
        spoke: Nome do repositório/spoke afetado.
        workspace_root: Diretório raiz do workspace.
        manifest: Caminho opcional do manifest.yaml.

    Returns:
        Lista de identificadores de prompts localizados.
    """
    repo_dir = locate_repo_dir(
        repo_name=spoke,
        workspace_root=workspace_root,
        manifest_path=manifest,
    )
    if not (repo_dir and repo_dir.is_dir()):
        return []
    return discover_prompts_in_repository(repo_dir)


def ensure_bug_plan_has_prompts(
    plan: BugPlan,
    workspace_root: Path = Path("."),
    manifest_path: Path | None = None,
) -> list[str]:
    """Garante que o BugPlan contenha declaração formal de prompts governados.

    Se `plan.prompts` já contiver itens, normaliza strings e retorna. Caso esteja
    vazio, investiga se o spoke afetado é um agente de IA ou se o defeito menciona
    prompts, auto-descobrindo os prompts do repositório via Langfuse governance.

    Args:
        plan: Especificação formal do defeito.
        workspace_root: Diretório raiz do workspace.
        manifest_path: Caminho opcional para o manifest.yaml.

    Returns:
        Lista de identificadores de prompts governados associados ao defeito.
    """
    if plan.prompts:
        raw_prompts: list[Any] = list(plan.prompts)
        plan.prompts = [
            p["name"] if isinstance(p, dict) else str(p) for p in raw_prompts if p
        ]
        return plan.prompts

    if not plan.affected_spoke:
        return []

    manifest = manifest_path or find_manifest_path(workspace_root=workspace_root)
    should_discover = is_ai_agent_spoke(
        plan.affected_spoke, manifest
    ) or bug_plan_mentions_prompts(plan)
    if not should_discover:
        return []

    discovered = discover_prompts_for_bug_spoke(
        spoke=plan.affected_spoke,
        workspace_root=workspace_root,
        manifest=manifest,
    )
    if discovered:
        plan.prompts = list(discovered)

    return plan.prompts


def enrich_bug_plan_topology(
    plan: BugPlan, workspace_root: Path | None = None
) -> BugPlan:
    """Enriquece o BugPlan com onda topológica e spoke originário do manifesto.

    Args:
        plan: Instância do BugPlan a enriquecer.
        workspace_root: Diretório opcional da raiz do workspace.

    Returns:
        A mesma instância de BugPlan com os campos de topologia preenchidos.
    """
    if not plan.origin_spoke:
        plan.origin_spoke = plan.affected_spoke

    ws = workspace_root or Path(".")
    wave, deps = resolve_spoke_wave_and_dependencies(
        plan.affected_spoke, workspace_root=ws
    )
    plan.wave = wave
    if not plan.depends_on:
        plan.depends_on = deps

    manifest = find_manifest_path(workspace_root=ws)
    ensure_bug_plan_has_prompts(plan=plan, workspace_root=ws, manifest_path=manifest)
    return plan


def generate_test_file_from_plan(plan: BugPlan, base_directory: Path) -> Path:
    """Gera fisicamente o arquivo de teste unitário TDD Fail-First.

    Args:
        plan: Especificação formal do defeito contendo contratos e asserções.
        base_directory: Diretório raiz do módulo/spoke onde o teste será criado.

    Returns:
        Path absoluto para o arquivo de teste unitário instanciado.
    """
    rel_path = plan.test_file_path or "tests/unit/test_bug_repro.py"
    target_path = base_directory / rel_path
    if target_path.is_file() and target_path.read_text(encoding="utf-8").strip():
        return target_path
    target_path.parent.mkdir(parents=True, exist_ok=True)

    func_name = plan.test_function_name or "test_bug_reproduction"
    rule = plan.business_rule or "O sistema deve atender ao contrato de negócio."
    while rule.startswith("Business Rule:"):
        rule = rule[len("Business Rule:") :].strip()

    content = (
        '"""Teste de reprodução determinística TDD para bugfix."""\n\n'
        "import pytest\n\n\n"
        f"def {func_name}() -> None:\n"
        f'    """Business Rule: {rule}"""\n'
        '    assert False, "Reprodução TDD: falha mandatória antes da correção."\n'
    )

    target_path.write_text(content, encoding="utf-8")
    return target_path


def check_spec_gate_approval(
    spec_target: str,
    workspace_root: Path = Path("."),
) -> tuple[bool, str, Path | None]:
    """Verifica se a especificação vinculada ao defeito foi aprovada no Gate 2.

    Args:
        spec_target: Identificador da spec (ex: SPEC-012) ou caminho do arquivo.
        workspace_root: Raiz do repositório para resolução de caminhos.

    Returns:
        Tupla contendo `(is_approved, status_string, resolved_path)`.
    """
    from harness_state.spec.lifecycle import (
        extract_yaml_frontmatter,
        resolve_spec_file_path,
    )

    spec_file = resolve_spec_file_path(
        spec_target=spec_target,
        workspace_root=workspace_root,
    )
    if not spec_file or not spec_file.is_file():
        return False, "NOT_FOUND", None

    content = spec_file.read_text(encoding="utf-8")
    meta, _ = extract_yaml_frontmatter(content)
    raw_status = meta.get("status")
    if not raw_status:
        match = re.search(r"status:\s*([A-Za-z_-]+)", content, re.IGNORECASE)
        raw_status = match.group(1).upper() if match else "UNKNOWN"
    else:
        raw_status = str(raw_status).upper()

    is_approved = raw_status in ("APPROVED", "MERGED", "IMPLEMENTED")
    return is_approved, raw_status, spec_file


def load_cloud_environment_config(
    manifest_path: Path, environment: str = "production"
) -> dict[str, Any]:
    """Carrega as configurações de nuvem declaradas no manifest.yaml do spec-hub.

    Args:
        manifest_path: Caminho do arquivo manifest.yaml.
        environment: Nome do ambiente a ser carregado (default: production).

    Returns:
        Dicionário com as configurações do ambiente de nuvem.

    Raises:
        FileNotFoundError: Se o arquivo manifest não existir.
        KeyError: Se o ambiente não estiver declarado no manifest.
    """
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest não encontrado em {manifest_path}")

    with open(manifest_path, encoding="utf-8") as file_stream:
        manifest_data = yaml.safe_load(file_stream) or {}

    cloud_envs = manifest_data.get("cloud_environments", {})
    if environment not in cloud_envs:
        raise KeyError(
            f"Ambiente '{environment}' não declarado em cloud_environments do manifest."
        )

    return cloud_envs[environment]


def build_container_filter_clause(container_name: list[str] | str) -> str:
    """Constrói a cláusula de filtro de containers para o Cloud Logging.

    Args:
        container_name: Nome do container ou lista de nomes de containers.

    Returns:
        Cláusula de filtro `resource.labels.container_name` ou string vazia.
    """
    if isinstance(container_name, list) and container_name:
        clean_containers = [c.strip() for c in container_name if c and c.strip()]
        if len(clean_containers) == 1:
            return f'resource.labels.container_name="{clean_containers[0]}"'
        if len(clean_containers) > 1:
            clauses = [
                f'resource.labels.container_name="{c}"' for c in clean_containers
            ]
            return f"({' OR '.join(clauses)})"
        return ""
    if isinstance(container_name, str) and container_name.strip():
        return f'resource.labels.container_name="{container_name.strip()}"'
    return ""


def build_gcloud_logging_command(
    cloud_config: dict[str, Any],
    container_name: list[str] | str,
    severity: str = "ERROR",
    since: str = "1h",
    start_time: str | None = None,
    end_time: str | None = None,
    custom_filter: str | None = None,
    limit: int = 30,
) -> list[str]:
    """Constrói os argumentos para invocação da CLI gcloud logging read.

    Args:
        cloud_config: Dicionário com as configurações de nuvem do ambiente.
        container_name: Nome do container ou lista de containers no cluster GKE.
        severity: Nível mínimo de severidade do log.
        since: Janela relativa padrão caso start_time não seja informado.
        start_time: Timestamp de início opcional em ISO 8601.
        end_time: Timestamp de término opcional em ISO 8601.
        custom_filter: Filtro adicional opcional.
        limit: Quantidade máxima de entradas a ler.

    Returns:
        Lista de strings com a invocação parametrizada do comando gcloud.
    """
    project_id = cloud_config.get("project_id", "")
    cluster_name = cloud_config.get("kubernetes", {}).get("cluster_name", "")

    query_parts = ['resource.type="k8s_container"']
    if cluster_name:
        query_parts.append(f'resource.labels.cluster_name="{cluster_name}"')

    container_clause = build_container_filter_clause(container_name)
    if container_clause:
        query_parts.append(container_clause)

    if severity:
        query_parts.append(f"severity>={severity}")

    use_freshness = False
    if start_time and end_time:
        query_parts.append(f'timestamp >= "{start_time}" AND timestamp <= "{end_time}"')
    elif start_time:
        query_parts.append(f'timestamp >= "{start_time}"')
    elif since:
        use_freshness = True

    if custom_filter:
        query_parts.append(f"({custom_filter})")

    cmd = [
        "gcloud",
        "logging",
        "read",
        " ".join(query_parts),
        f"--project={project_id}",
    ]
    if use_freshness:
        cmd.append(f"--freshness={since}")
    cmd.extend([f"--limit={limit}", "--format=json"])
    return cmd


def resolve_container_name_for_spoke(spoke: str) -> str:
    """Mapeia um spoke para o nome provável do container no Kubernetes/GKE.

    Args:
        spoke: Identificador ou nome do repositório/spoke.

    Returns:
        Nome do container provável no cluster GKE.
    """
    mapping = {
        "customer-support-vehicles": "prod-customer-support-v2-vehicles",
        "duo-dermato-support": "prod-duo-dermato-support",
        "google-calendar-agent": "prod-paralax-calendar",
        "paralax-support": "prod-paralax-support",
        "anero-cafe-support": "prod-anero-cafe-support",
        "evo-bot-runtime": "evo-bot-runtime",
        "evo-ai-crm-community": "evo-crm",
        "evolution-api": "prod-evolution-api-customer-support-v2",
    }
    clean_spoke = spoke.strip().lower()
    for key, val in mapping.items():
        if key in clean_spoke or clean_spoke in key:
            return val
    return spoke or "prod-customer-support-v2-vehicles"


def resolve_flow_containers_for_spoke(spoke: str) -> list[str]:
    """Resolve os containers do fluxo do agente e do evo-bot-runtime.

    Args:
        spoke: Nome do spoke afetado.

    Returns:
        Lista de nomes de containers envolvidos no fluxo do agente.
    """
    primary = resolve_container_name_for_spoke(spoke)
    containers = [primary]
    if "evo-bot-runtime" not in containers:
        containers.append("evo-bot-runtime")
    return containers


def build_fallback_log_query_context(
    user_response: str,
    base_containers: list[str],
) -> dict[str, Any]:
    """Constrói parâmetros de busca de logs por heurística quando o LLM falha.

    Args:
        user_response: Texto livre informado pelo usuário.
        base_containers: Lista base de containers já em análise.

    Returns:
        Dicionário estruturado de parâmetros de busca.
    """
    containers = list(base_containers)
    lower_resp = user_response.lower()
    if "crm" in lower_resp and "evo-crm" not in containers:
        containers.append("evo-crm")
    if "evolution" in lower_resp or "whatsapp" in lower_resp:
        evolution_svc = "prod-evolution-api-customer-support-v2"
        if evolution_svc not in containers:
            containers.append(evolution_svc)
    return {
        "containers": containers,
        "since": "6h" if "ontem" in lower_resp else "2h",
        "start_time": None,
        "end_time": None,
        "severity": "ERROR",
        "custom_filter": None,
    }


def extract_log_query_context_with_llm(
    user_response: str,
    base_containers: list[str],
    base_url: str = "",
    api_key: str = "",
    model_name: str = "",
) -> dict[str, Any]:
    """Mapeia o contexto livre do usuário para parâmetros estruturados de log via LLM.

    Args:
        user_response: Texto livre informado pelo usuário com detalhes adicionais.
        base_containers: Lista base de containers já em análise.
        base_url: URL base opcional da API OpenAI.
        api_key: Chave opcional da API.
        model_name: Nome do modelo LLM.

    Returns:
        Dicionário com containers, since, start_time, end_time e severidade.
    """
    system_instruction = (
        "Você é um Engenheiro de SRE e Observabilidade especialista em GCP "
        "Cloud Logging e Kubernetes.\n"
        "Sua missão é extrair parâmetros estruturados de busca de logs a partir "
        "do relato livre do usuário.\n\n"
        "MAPEAMENTO DE SERVIÇOS DO ECOSSISTEMA:\n"
        "- 'veiculos' / 'carros' -> prod-customer-support-v2-vehicles\n"
        "- 'bot' / 'runtime' -> evo-bot-runtime\n"
        "- 'evolution' / 'whatsapp' -> prod-evolution-api-customer-support-v2\n"
        "- 'crm' / 'evo-crm' -> evo-crm\n"
        "- 'calendar' / 'agenda' -> prod-paralax-calendar\n"
        "- 'duo' / 'dermato' -> prod-duo-dermato-support\n"
        "- 'support' / 'paralax-support' -> prod-paralax-support\n"
        "- 'anero' / 'cafe' -> prod-anero-cafe-support\n\n"
        "Responda EXCLUSIVAMENTE em formato JSON com as chaves:\n"
        "{\n"
        '  "containers": ["container1", "container2"],\n'
        '  "since": "2h",\n'
        '  "start_time": null,\n'
        '  "end_time": null,\n'
        '  "severity": "ERROR",\n'
        '  "custom_filter": null\n'
        "}"
    )

    user_content = (
        f"Containers iniciais do fluxo: {base_containers}\n"
        f'Relato adicional do usuário: "{user_response}"'
    )

    data = call_llm_json_completion(
        system_instruction=system_instruction,
        user_content=user_content,
        base_url=base_url,
        api_key=api_key,
        model_name=model_name,
        stream=False,
    )

    if not data or not isinstance(data, dict):
        return build_fallback_log_query_context(user_response, base_containers)

    extracted_containers = data.get("containers") or []
    final_containers = list(base_containers)
    for c in extracted_containers:
        if c and c not in final_containers:
            final_containers.append(c)

    return {
        "containers": final_containers,
        "since": data.get("since") or "2h",
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "severity": data.get("severity") or "ERROR",
        "custom_filter": data.get("custom_filter"),
    }


def format_gcloud_log_entries_summary(entries: list[dict[str, Any]]) -> list[str]:
    """Formata um resumo conciso das primeiras entradas de log do GCP.

    Args:
        entries: Lista de dicionários de eventos de log do Cloud Logging.

    Returns:
        Lista de linhas de resumo formatadas.
    """
    sample_msgs: list[str] = []
    for entry in entries[:3]:
        ts = entry.get("timestamp", "")
        json_payload = entry.get("jsonPayload")
        payload = entry.get("textPayload") or (
            json_payload.get("message") if isinstance(json_payload, dict) else None
        )
        if not payload and isinstance(json_payload, dict):
            payload = json.dumps(json_payload)
        if payload:
            first_line = str(payload).strip().splitlines()[0]
            sample_msgs.append(f"    • [{ts[:19]}] {first_line[:90]}")
    return sample_msgs


def execute_gcloud_log_query(cmd: list[str]) -> tuple[str | None, list[dict[str, Any]]]:
    """Executa um comando `gcloud logging read` e decodifica as entradas JSON.

    Args:
        cmd: Lista de argumentos do comando `gcloud`.

    Returns:
        Tupla `(raw_stdout_ou_None, lista_de_entradas)`.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        sys.stdout.write(f"  ⚠ Não foi possível executar gcloud: {exc}\n\n")
        sys.stdout.flush()
        return None, []

    if proc.returncode != 0 or not proc.stdout.strip():
        return "", []

    raw_stdout = proc.stdout.strip()
    try:
        parsed = json.loads(raw_stdout)
        return raw_stdout, parsed if isinstance(parsed, list) else []
    except Exception:  # noqa: BLE001
        return raw_stdout, []


def print_discovered_log_entries(
    entries: list[dict[str, Any]],
    header_msg: str,
) -> None:
    """Imprime no stdout a confirmação e o resumo das entradas de log localizadas.

    Args:
        entries: Lista de eventos de erro localizados.
        header_msg: Mensagem de cabeçalho de confirmação.
    """
    sys.stdout.write(header_msg)
    sample_msgs = format_gcloud_log_entries_summary(entries)
    if sample_msgs:
        sys.stdout.write(
            "  Resumo dos eventos encontrados:\n" + "\n".join(sample_msgs) + "\n\n"
        )
    sys.stdout.flush()


def interactive_fetch_cloud_logs(
    spoke: str = "",
    manifest_path: Path | None = None,
    prompt_fn: Callable[[str], str] | None = None,
    default_window: str = "2h",
) -> str | None:
    """Investiga automaticamente logs no fluxo do agente e do evo-bot-runtime.

    Elimina perguntas iniciais. Se nada for localizado automaticamente, solicita
    mais informações ao usuário e mapeia via LLM novos serviços e janelas.

    Args:
        spoke: Nome do spoke afetado para resolver os containers do fluxo.
        manifest_path: Caminho opcional do manifest.yaml.
        prompt_fn: Função opcional para captura de input do usuário.
        default_window: Janela relativa padrão (default: 2h).

    Returns:
        String contendo os logs JSON curados ou None.
    """
    active_prompt_fn = prompt_fn or input
    flow_containers = resolve_flow_containers_for_spoke(spoke)
    containers_label = ", ".join(flow_containers)

    sys.stdout.write(
        f"\n  ⏳ Analisando logs do fluxo ({containers_label}) no "
        "GCP Cloud Logging...\n"
    )
    sys.stdout.flush()

    cloud_config: dict[str, Any] = {
        "project_id": "paralax-prod",
        "kubernetes": {
            "cluster_name": "prod-gke-cluster",
            "namespace": "crm",
        },
    }
    if manifest_path and manifest_path.is_file():
        try:
            cloud_config = load_cloud_environment_config(manifest_path, "production")
        except Exception:  # noqa: BLE001, S110
            pass

    cmd = build_gcloud_logging_command(
        cloud_config=cloud_config,
        container_name=flow_containers,
        severity="ERROR",
        since=default_window,
        limit=25,
    )
    raw_stdout, entries = execute_gcloud_log_query(cmd)
    if raw_stdout is None:
        return None

    if entries:
        print_discovered_log_entries(
            entries,
            f"  ✓ {len(entries)} eventos de erro localizados no fluxo "
            f"({containers_label})!\n",
        )
        return raw_stdout

    sys.stdout.write(
        f"  ⚠ Nenhum log de erro localizado automaticamente no fluxo "
        f"({containers_label}) na janela recente ({default_window}).\n"
    )
    sys.stdout.flush()

    try:
        user_info = active_prompt_fn(
            "Forneça mais detalhes para localizar os logs (ex: quando aconteceu "
            "o erro, horário aproximado ou outros serviços envolvidos como "
            "evo-crm, evolution-api) [Enter para pular]: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        user_info = ""

    if not user_info:
        sys.stdout.write(
            "  Prosseguindo com a elicitação técnica do defeito via IA.\n\n"
        )
        sys.stdout.flush()
        return None

    sys.stdout.write("  🤖 Mapeando contexto e serviços adicionais via IA...\n")
    sys.stdout.flush()

    query_params = extract_log_query_context_with_llm(
        user_response=user_info,
        base_containers=flow_containers,
    )
    refined_containers = query_params.get("containers") or flow_containers
    refined_start = query_params.get("start_time")

    sys.stdout.write(
        "  ⏳ Reconsultando logs no GCP para os serviços: "
        f"{', '.join(refined_containers)}...\n"
    )
    sys.stdout.flush()

    second_cmd = build_gcloud_logging_command(
        cloud_config=cloud_config,
        container_name=refined_containers,
        severity=query_params.get("severity") or "ERROR",
        since=(query_params.get("since") or default_window)
        if not refined_start
        else "",
        start_time=refined_start,
        end_time=query_params.get("end_time"),
        custom_filter=query_params.get("custom_filter"),
        limit=25,
    )
    second_stdout, second_entries = execute_gcloud_log_query(second_cmd)
    if second_stdout is None:
        return None

    if second_entries:
        print_discovered_log_entries(
            second_entries,
            f"  ✓ {len(second_entries)} eventos de erro localizados nos "
            "serviços expandidos!\n",
        )
        return second_stdout

    sys.stdout.write(
        "  ⚠ Nenhum log encontrado mesmo com os parâmetros adicionais.\n"
        "  Prosseguindo com a elicitação técnica do defeito via IA.\n\n"
    )
    sys.stdout.flush()
    return None


def resolve_most_probable_spoke(
    candidate_spoke: str,
    known_repos: list[Any],
) -> str:
    """Resolve e normaliza o repositório mais provável a partir de conhecidos.

    Args:
        candidate_spoke: Nome retornado pelo LLM ou inferido pelo contexto.
        known_repos: Lista de nomes ou dicionários de repositórios conhecidos.

    Returns:
        Nome canônico do repositório mais provável ou 'unknown'.
    """
    clean_candidate = candidate_spoke.strip().lower()
    if clean_candidate in ("", "unknown", "none", "null"):
        return "unknown"

    repo_names: list[str] = []
    for r in known_repos:
        if isinstance(r, dict) and "name" in r:
            repo_names.append(r["name"])
        elif isinstance(r, str):
            repo_names.append(r.split()[0].strip())

    for name in repo_names:
        clean_name = name.lower()
        if clean_candidate == clean_name or clean_candidate.endswith(f"/{clean_name}"):
            return name

    for name in repo_names:
        clean_name = name.lower()
        if clean_name in clean_candidate or clean_candidate in clean_name:
            return name

    return candidate_spoke


def infer_spoke_from_prompt_heuristic(
    prompt: str,
    repos_context: list[Any],
) -> str:
    """Infere deterministicamente o spoke mais provável por palavras-chave do domínio.

    Args:
        prompt: Relato do usuário.
        repos_context: Lista de repositórios conhecidos.

    Returns:
        Nome do spoke mais provável ou 'unknown'.
    """
    clean_p = prompt.lower()
    keywords_map: dict[str, list[str]] = {
        "customer-support-vehicles": [
            "veicul",
            "carro",
            "automov",
            "concessionari",
            "veículos",
            "carros",
        ],
        "duo-dermato-support": ["dermat", "pele", "clinica", "duo"],
        "google-calendar-agent": ["agenda", "calendar", "consulta", "horario"],
        "paralax-evo-crm": ["sdk", "client crm"],
        "evo-ai-crm-community": ["crm", "conversa", "contato", "inbox", "lead"],
        "evo-bot-runtime": ["whatsapp", "runtime", "debounce", "webhook"],
        "anero-cafe-support": ["cafe", "cafeteria", "anero", "cardapio"],
    }
    for repo_name, keywords in keywords_map.items():
        if any(kw in clean_p for kw in keywords):
            return repo_name

    repo_names: list[str] = []
    for r in repos_context:
        name = r.get("name") if isinstance(r, dict) else str(r).split()[0].strip()
        if name:
            repo_names.append(name)

    if len(repo_names) == 1:
        return repo_names[0]
    return "unknown"


def extract_json_payload_from_text(text: str) -> dict[str, Any] | None:
    """Extrai um payload JSON válido a partir de uma saída textual do agente.

    Args:
        text: Texto bruto emitido pelo agente ou LLM.

    Returns:
        Dicionário com o payload JSON decodificado ou None.
    """
    clean = text.strip()
    if not clean:
        return None

    match_markdown = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", clean, re.DOTALL)
    if match_markdown:
        try:
            return json.loads(match_markdown.group(1).strip())
        except json.JSONDecodeError:
            pass

    start_idx = clean.find("{")
    end_idx = clean.rfind("}")
    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = clean[start_idx : end_idx + 1]
        try:
            return json.loads(candidate.strip())
        except json.JSONDecodeError:
            pass

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return None


def process_llm_stream_chunk(
    delta: Any,
    target_model: str,
    thought_header_printed: bool,
    tokens: list[str],
) -> bool:
    """Processa um único chunk delta do stream OpenAI e escreve no stdout.

    Args:
        delta: Objeto delta do chunk.
        target_model: Nome do modelo LLM.
        thought_header_printed: Indica se o cabeçalho de pensamento já foi impresso.
        tokens: Lista acumuladora de tokens de conteúdo.

    Returns:
        Novo estado de `thought_header_printed`.
    """
    reasoning_tk = getattr(delta, "reasoning_content", None)
    if reasoning_tk:
        if not thought_header_printed:
            sys.stdout.write(f"\n💭 [{target_model} Pensamento]:\n  ")
            thought_header_printed = True
        sys.stdout.write(reasoning_tk)
        sys.stdout.flush()
        return thought_header_printed

    tk = getattr(delta, "content", None)
    if not tk:
        return thought_header_printed

    tokens.append(tk)
    display_tk = tk
    if "<think>" in display_tk:
        if not thought_header_printed:
            sys.stdout.write(f"\n💭 [{target_model} Pensamento]:\n  ")
            thought_header_printed = True
        display_tk = display_tk.replace("<think>", "")
    if "</think>" in display_tk:
        display_tk = display_tk.replace("</think>", "\n\n")

    sys.stdout.write(display_tk)
    sys.stdout.flush()
    return thought_header_printed


def consume_llm_stream_response(
    stream_resp: Any,
    target_model: str,
) -> str:
    """Consome o stream de tokens do cliente OpenAI e imprime pensamento/conteúdo.

    Args:
        stream_resp: Iterador de chunks retornado pelo `client.chat.completions.create`.
        target_model: Nome do modelo em execução.

    Returns:
        Conteúdo textual acumulado dos chunks de resposta.
    """
    tokens: list[str] = []
    thought_header_printed = False

    for chunk in stream_resp:
        if not chunk.choices:
            continue
        thought_header_printed = process_llm_stream_chunk(
            chunk.choices[0].delta, target_model, thought_header_printed, tokens
        )

    sys.stdout.write("\n")
    sys.stdout.flush()
    return "".join(tokens)


def call_llm_json_completion(
    system_instruction: str,
    user_content: str,
    base_url: str = "",
    api_key: str = "",
    model_name: str = "",
    stream: bool = True,
) -> dict[str, Any] | None:
    """Envia requisição para LLM compatível com OpenAI e extrai JSON de resposta.

    Args:
        system_instruction: Mensagem de sistema / prompt mestre.
        user_content: Mensagem de entrada do usuário.
        base_url: Endpoint base da API.
        api_key: Chave de API.
        model_name: Nome do modelo alvo.
        stream: Habilita streaming dos tokens no terminal.

    Returns:
        Dicionário com o payload JSON decodificado ou None em caso de falha.
    """
    resolved_base_url = base_url
    resolved_api_key = api_key
    if not resolved_base_url or not resolved_api_key:
        default_url, default_key = AgentRunner()._resolve_ollama_settings()
        resolved_base_url = resolved_base_url or default_url
        resolved_api_key = resolved_api_key or default_key

    resolved_model = (
        model_name
        or os.environ.get("LLM_DEFAULT_MODEL")
        or os.environ.get("LLM_MODEL")
        or "agentic-qwen:latest"
    )

    candidate_models = [resolved_model]
    if ":7b" in resolved_model:
        candidate_models.append(resolved_model.replace(":7b", ":latest"))

    client = OpenAI(
        base_url=resolved_base_url,
        api_key=resolved_api_key,
        timeout=60.0,
    )
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": system_instruction},
        {"role": "user", "content": user_content},
    ]

    for target_model in candidate_models:
        try:
            if stream:
                stream_resp = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    temperature=0.1,
                    stream=True,
                )
                raw_content = consume_llm_stream_response(stream_resp, target_model)
            else:
                sync_resp = client.chat.completions.create(
                    model=target_model,
                    messages=messages,
                    temperature=0.1,
                    stream=False,
                )
                raw_content = sync_resp.choices[0].message.content or ""

            return extract_json_payload_from_text(raw_content)
        except Exception:  # noqa: BLE001, S112
            continue

    return None


def format_manifest_repos_for_prompt(repos_context: list[Any]) -> list[str]:
    """Formata a lista de repositórios do manifesto para inclusão no prompt do LLM.

    Args:
        repos_context: Lista de dicionários ou strings de repositórios.

    Returns:
        Lista de descrições formatadas.
    """
    repos_desc: list[str] = []
    for r in repos_context:
        if isinstance(r, dict):
            details = [f"name: {r.get('name')}"]
            for key in ("role", "entrypoint", "description"):
                if r.get(key):
                    details.append(f"{key}: {r.get(key)}")
            repos_desc.append("{" + ", ".join(details) + "}")
        else:
            repos_desc.append(str(r))
    return repos_desc


def build_fallback_bug_plan(
    prompt: str,
    repos_context: list[Any],
    cloud_log: str | None,
) -> BugPlan:
    """Constrói um `BugPlan` padrão por heurística quando o LLM não retorna JSON.

    Args:
        prompt: Relato livre do usuário.
        repos_context: Lista de repositórios conhecidos.
        cloud_log: Evidência opcional do Cloud Logging.

    Returns:
        Instância de `BugPlan` preenchida com valores padrão seguros.
    """
    inferred_spoke = infer_spoke_from_prompt_heuristic(prompt, repos_context)
    plan = BugPlan(
        title=(
            f"[Bug] {prompt[:60]}..."
            if len(prompt) > 60
            else f"[Bug] {prompt or 'Defeito'}"
        ),
        summary=prompt or "Defeito a ser investigado via TDD.",
        observed_behavior="Comportamento anômalo reportado em tempo de execução.",
        expected_behavior="Execução conforme as regras de negócio.",
        affected_spoke=inferred_spoke,
        affected_capability="core",
        runtime_contract="Service.execute",
        reproduction_steps=["1. Reproduzir o fluxo reportado pelo usuário."],
        test_file_path="tests/unit/test_bug_repro.py",
        test_function_name="test_reproduce_reported_bug",
        business_rule="O sistema deve cumprir as garantias do contrato de negócio.",
        selected_cloud_log=cloud_log,
        intake_prompt=prompt,
        prompts=[],
    )
    return enrich_bug_plan_topology(plan)


def elicit_bug_plan_with_llm(
    prompt: str,
    manifest_repos: list[Any] | None = None,
    cloud_log: str | None = None,
    base_url: str = "",
    api_key: str = "",
    model_name: str = "",
    stream: bool = True,
    agent: Any = None,
    continue_session: bool | None = None,
) -> BugPlan:
    """Elicita uma especificação formal de bug a partir de um prompt informal via LLM.

    Args:
        prompt: Relato livre do defeito informado pelo usuário.
        manifest_repos: Lista opcional de repositórios ou metadados conhecidos.
        cloud_log: Evidência de log curada opcional coletada do Cloud Logging.
        base_url: URL base compatível com a API da OpenAI.
        api_key: Chave de API para autenticação no servidor LLM.
        model_name: Nome do modelo no servidor LLM.
        stream: Se True, transmite a resposta do modelo em tempo real no console.
        agent: Instância opcional de DetectedAgent para execução via CLI.
        continue_session: Se True, retoma sessão anterior. Padrão None (desativado).

    Returns:
        Instância estruturada de BugPlan.
    """
    resolved_continue = (
        bool(continue_session) if continue_session is not None else False
    )
    repos_context = manifest_repos or []
    repos_desc = format_manifest_repos_for_prompt(repos_context)

    system_instruction = (
        "Você é um Arquiteto de Software e Engenheiro de QA especialista em "
        "Spec-Driven Development (SDD) e Domain-Driven Design (DDD).\n"
        "Sua missão é converter um relato informal de bug em uma especificação "
        "formal e rigorosa de defeito.\n\n"
        "INFERÊNCIA OBRIGATÓRIA DO SPOKE:\n"
        "Caso o usuário não especifique o repositório diretamente, você DEVE "
        "analisar os sintomas e o contexto do relato para DEDUZIR O SPOKE MAIS "
        "PROVÁVEL dentre os repositórios conhecidos do ecossistema informados. "
        "Utilize seus papéis (role), nomes e entrypoints para a escolha.\n"
        "Defina 'unknown' apenas se houver total ambiguidade transversal.\n\n"
        "Você DEVE responder EXCLUSIVAMENTE em formato JSON com as chaves:\n"
        '- "title": Título conciso da Issue (ex: "fix(customer-support-vehicles): '
        'erro na busca de carros")\n'
        '- "summary": Resumo executivo da falha em 1 a 2 frases\n'
        '- "observed_behavior": Comportamento anômalo observado\n'
        '- "expected_behavior": Comportamento esperado segundo a regra de negócio\n'
        '- "affected_spoke": Nome do repositório/spoke identificado dentre '
        "os conhecidos\n"
        '- "affected_capability": Nome da capacidade de negócio/DDD impactada\n'
        '- "runtime_contract": Nome da classe/método de contrato violado\n'
        '- "reproduction_steps": Lista de strings com passos determinísticos '
        "de reprodução\n"
        '- "test_file_path": Caminho relativo do arquivo de teste TDD '
        '(ex: "tests/unit/test_vehicle_search.py")\n'
        '- "test_function_name": Nome da função de teste unitário '
        '(ex: "test_vehicle_search_returns_available_cars")\n'
        '- "business_rule": Regra de negócio obrigatória para o docstring '
        "do teste TDD\n"
        '- "prompts": Lista de strings com identificadores de prompts governados no '
        'Langfuse (ex: ["vehicles/vehicle_search_agent_instruction"]) caso envolva '
        "agentes de IA, instruções de sistema ou prompts.py\n"
    )

    user_content = (
        f'Relato informal do usuário: "{prompt}"\n'
        "Repositórios conhecidos do ecossistema:\n"
        + "\n".join(f"- {d}" for d in repos_desc)
    )
    if cloud_log:
        user_content += (
            f"\nEvidência coletada no Cloud Logging:\n```json\n{cloud_log}\n```\n"
        )

    plan_data = None
    if agent is not None:
        agent_prompt = (
            f"{system_instruction}\n\n"
            f"{user_content}\n\n"
            "Responda estritamente com o bloco JSON contendo as chaves solicitadas."
        )
        exit_code, agent_output = AgentRunner().run_prompt(
            agent=agent,
            working_dir=Path("."),
            prompt_text=agent_prompt,
            task_label="eliciação técnica do defeito",
            continue_session=resolved_continue,
        )
        if exit_code == 0 and agent_output:
            plan_data = extract_json_payload_from_text(agent_output)

    if not plan_data:
        plan_data = call_llm_json_completion(
            system_instruction=system_instruction,
            user_content=user_content,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
        )

    if not plan_data:
        return build_fallback_bug_plan(prompt, repos_context, cloud_log)

    raw_spoke = plan_data.get("affected_spoke") or ""
    resolved_spoke = resolve_most_probable_spoke(raw_spoke, repos_context)
    if resolved_spoke == "unknown":
        resolved_spoke = infer_spoke_from_prompt_heuristic(prompt, repos_context)

    plan = BugPlan(
        title=plan_data.get("title") or f"[Bug] {prompt}",
        summary=plan_data.get("summary") or prompt,
        observed_behavior=(
            plan_data.get("observed_behavior") or "Comportamento divergente observado."
        ),
        expected_behavior=(
            plan_data.get("expected_behavior") or "Comportamento esperado pelo negócio."
        ),
        affected_spoke=resolved_spoke,
        affected_capability=plan_data.get("affected_capability") or "core",
        runtime_contract=plan_data.get("runtime_contract") or "Service.execute",
        reproduction_steps=plan_data.get("reproduction_steps") or [],
        test_file_path=(
            plan_data.get("test_file_path") or "tests/unit/test_bug_repro.py"
        ),
        test_function_name=(
            plan_data.get("test_function_name") or "test_reproduce_reported_bug"
        ),
        business_rule=(
            plan_data.get("business_rule")
            or "O sistema deve cumprir as garantias do contrato de negócio."
        ),
        selected_cloud_log=cloud_log,
        intake_prompt=prompt,
        prompts=plan_data.get("prompts") or [],
    )
    return enrich_bug_plan_topology(plan)


def extract_repos_from_manifest_file(m_path: Path) -> list[str]:
    """Extrai os identificadores `repo` de um arquivo `manifest.yaml`.

    Args:
        m_path: Caminho do arquivo `manifest.yaml`.

    Returns:
        Lista de identificadores `owner/repo` declarados no manifesto.
    """
    if not m_path.is_file():
        return []
    try:
        data = yaml.safe_load(m_path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001
        return []

    repos: list[str] = []
    for repo_item in data.get("repositories", []):
        if isinstance(repo_item, dict) and repo_item.get("repo"):
            repos.append(str(repo_item["repo"]))
    return repos


def extract_git_remote_slug(repo_dir: Path) -> str | None:
    """Obtém o slug `owner/repo` a partir do remote `origin` de um diretório git.

    Args:
        repo_dir: Diretório contendo `.git`.

    Returns:
        Slug `owner/repo` ou None.
    """
    if not (repo_dir.is_dir() and (repo_dir / ".git").is_dir()):
        return None
    try:
        proc = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:  # noqa: BLE001
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    raw_url = proc.stdout.strip()
    repo_str = raw_url.removesuffix(".git").split(":")[-1]
    cleaned_repo = repo_str.split("github.com/")[-1].strip("/")
    return cleaned_repo if "/" in cleaned_repo else None


def discover_candidate_repositories(
    workspace_root: Path = Path("."),
) -> list[str]:
    """Descobre repositórios GitHub candidatos no workspace e no manifesto.

    Args:
        workspace_root: Diretório raiz para busca.

    Returns:
        Lista de strings no formato 'owner/repo'.
    """
    candidates: list[str] = []
    manifest_paths = [
        workspace_root / "manifest.yaml",
        workspace_root / "paralax-spec-hub" / "manifest.yaml",
    ]
    for m_path in manifest_paths:
        for repo_id in extract_repos_from_manifest_file(m_path):
            if repo_id not in candidates:
                candidates.append(repo_id)

    if workspace_root.is_dir():
        for child in workspace_root.iterdir():
            slug = extract_git_remote_slug(child)
            if slug and slug not in candidates:
                candidates.append(slug)

    return candidates


def fetch_github_issue_bug_plan(
    clean_id: str,
    repo: str | None = None,
) -> BugPlan | None:
    """Consulta o corpo de uma Issue no GitHub via `gh` e converte em `BugPlan`.

    Args:
        clean_id: Identificador numérico da Issue (sem `#`).
        repo: Slug opcional `owner/repo`.

    Returns:
        Instância de `BugPlan` se localizada, senão None.
    """
    gh_cmd = ["gh", "issue", "view", clean_id]
    if repo:
        gh_cmd.extend(["--repo", repo])
    gh_cmd.extend(["--json", "body", "-q", ".body"])

    proc = subprocess.run(gh_cmd, capture_output=True, text=True, check=False)
    if proc.returncode == 0 and proc.stdout.strip():
        plan = parse_bug_issue_markdown(proc.stdout)
        plan.issue_id = int(clean_id)
        if repo and (not plan.affected_spoke or plan.affected_spoke == "unknown"):
            plan.affected_spoke = repo.split("/")[-1]
        return plan
    return None


def resolve_bug_plan_by_issue_id(
    clean_id: str,
    workspace_root: Path,
    repo: str | None,
) -> BugPlan | None:
    """Busca um `BugPlan` por ID numérico de Issue no repo alvo, local ou candidatos.

    Args:
        clean_id: ID numérico da Issue.
        workspace_root: Raiz do workspace.
        repo: Repositório explícito opcional.

    Returns:
        Instância de `BugPlan` se encontrada, senão None.
    """
    if repo:
        plan = fetch_github_issue_bug_plan(clean_id, repo)
        if plan is not None:
            return plan

    local_plan = fetch_github_issue_bug_plan(clean_id, None)
    if local_plan is not None:
        return local_plan

    for cand_repo in discover_candidate_repositories(workspace_root):
        cand_plan = fetch_github_issue_bug_plan(clean_id, cand_repo)
        if cand_plan is not None:
            return cand_plan
    return None


def find_latest_bug_spec_file(workspace_root: Path) -> Path | None:
    """Busca o arquivo Markdown mais recente de bug em `specs/bugs/`.

    Args:
        workspace_root: Raiz do workspace.

    Returns:
        Path do arquivo encontrado ou None.
    """
    specs_bugs_dir = workspace_root / "specs" / "bugs"
    if not specs_bugs_dir.is_dir():
        return None
    for candidate in sorted(specs_bugs_dir.glob("*.md"), reverse=True):
        content = candidate.read_text(encoding="utf-8")
        if "<!-- flywheel:bug-plan:v1 -->" in content:
            return candidate
    return None


def load_bug_plan_target(
    target: str | Path | None = None,
    workspace_root: Path = Path("."),
    repo: str | None = None,
) -> tuple[BugPlan, Path | None]:
    """Carrega a especificação do defeito a partir de arquivo, issue ou padrão local.

    Args:
        target: Caminho para arquivo Markdown de bug, ID de issue ou None.
        workspace_root: Raiz do workspace para busca de arquivos padrão.
        repo: Identificador opcional do repositório remoto (ex: owner/repo).

    Returns:
        Tupla contendo a instância de BugPlan e o caminho do arquivo (se local).

    Raises:
        FileNotFoundError: Caso nenhum plano de defeito seja localizado.
    """
    if target:
        target_str = str(target).strip()
        candidate_path = Path(target_str)
        if candidate_path.is_file():
            return parse_bug_issue_markdown(
                candidate_path.read_text(encoding="utf-8")
            ), candidate_path

        clean_id = target_str.lstrip("#")
        if clean_id.isdigit():
            issue_plan = resolve_bug_plan_by_issue_id(clean_id, workspace_root, repo)
            if issue_plan is not None:
                return issue_plan, None

    for fallback_path in (workspace_root / "bug_issue.md", Path("/tmp/bug_plan.md")):
        if fallback_path.is_file():
            return parse_bug_issue_markdown(
                fallback_path.read_text(encoding="utf-8")
            ), fallback_path

    latest_spec = find_latest_bug_spec_file(workspace_root)
    if latest_spec is not None:
        return parse_bug_issue_markdown(
            latest_spec.read_text(encoding="utf-8")
        ), latest_spec

    raise FileNotFoundError(
        "Nenhum plano de defeito encontrado. Execute "
        "'harness bug plan \"<relato>\"' primeiro."
    )


def find_matching_spoke_child_dir(
    workspace_root: Path,
    clean_spoke: str,
) -> Path | None:
    """Procura nos subdiretórios de `workspace_root` um spoke correspondente.

    Args:
        workspace_root: Diretório raiz do workspace.
        clean_spoke: Nome normalizado do spoke em minúsculas.

    Returns:
        Path do subdiretório correspondente ou None.
    """
    if not workspace_root.is_dir():
        return None
    for child in workspace_root.iterdir():
        if not child.is_dir():
            continue
        child_lower = child.name.lower()
        if child_lower == clean_spoke or (
            clean_spoke == "spec-hub" and child_lower.endswith("-spec-hub")
        ):
            return child
    return None


def resolve_spoke_directory(
    affected_spoke: str,
    workspace_root: Path = Path("."),
) -> Path:
    """Resolve o diretório do spoke impactado pelo defeito.

    Args:
        affected_spoke: Nome do spoke/repositório indicado no BugPlan.
        workspace_root: Raiz do diretório de execução atual.

    Returns:
        Path absoluto ou relativo do diretório onde o teste e fix serão aplicados.
    """
    raw_spoke = re.sub(r"\s*\(.*?\)", "", affected_spoke).strip()
    clean_spoke = raw_spoke.split("/")[-1].strip().lower()
    if clean_spoke in ("", "unknown", "none", "null"):
        return workspace_root

    if workspace_root.resolve().name.lower() == clean_spoke:
        return workspace_root

    direct_candidate = workspace_root / clean_spoke
    if direct_candidate.is_dir():
        return direct_candidate

    child_match = find_matching_spoke_child_dir(workspace_root, clean_spoke)
    return child_match if child_match is not None else workspace_root


def build_bug_fix_prompt(plan: BugPlan, test_file_path: str) -> str:
    """Constrói o prompt prescritivo para o agente de IA solucionar o defeito.

    Args:
        plan: Especificação formal do defeito (BugPlan).
        test_file_path: Caminho do arquivo de teste de reprodução TDD (Red).

    Returns:
        Texto estruturado em Markdown com as instruções operacionais de fix.
    """
    lines = [
        f"# 🛠️ Task: Solução do Defeito TDD: {plan.title}",
        f"- **Spoke Alvo:** `{plan.affected_spoke}`",
        f"- **Capacidade DDD Afetada:** `{plan.affected_capability}`",
        f"- **Contrato Violado:** `{plan.runtime_contract}`",
        "",
        "## 📋 Diagnóstico e Regras do Defeito",
        f"- **Sumário:** {plan.summary}",
        f"- **Comportamento Observado:** {plan.observed_behavior}",
        f"- **Comportamento Esperado:** {plan.expected_behavior}",
        f"- **Regra de Negócio Mandatória:** {plan.business_rule}",
        "",
        "## 🧪 Teste de Reprodução TDD (Fail-First Red)",
        "O teste unitário que reproduz a falha já foi instanciado e está falhando:",
        f"- **Arquivo:** `{test_file_path}`",
        f"- **Função:** `{plan.test_function_name}`",
        "",
        "## 🎯 Instruções Obrigatórias de Execução:",
        f"1. Examine `{test_file_path}` para entender o contrato e a asserção exigida.",
        "2. Localize o código-fonte responsável no projeto e implemente o fix mínimo.",
        (
            f"3. Execute o teste com pytest e garanta que `{test_file_path}` "
            "passe (Green)."
        ),
        "4. Metodologia de Causa Raiz Mandatória (RCA, Ishikawa e 5 Whys):",
        (
            "   - ANTES de alterar qualquer código, construa o Diagrama de "
            "Ishikawa cobrindo as 6 categorias: Método, Máquina/Ambiente, "
            "Mão de Obra/Agente, Material/Dependências, Medição/Testes e "
            "Meio Ambiente."
        ),
        (
            "   - Responda os 5 Porquês e rejeite correções que resolvam "
            "apenas o primeiro nível."
        ),
        (
            "   - ENTREGÁVEL: o Diagrama de Ishikawa e os 5 Porquês devem "
            "constar no corpo do Pull Request (seções 'Ishikawa' e "
            "'5 Porquês'). Sem eles, o fix é considerado incompleto."
        ),
        (
            "   - NUNCA mascare erros ou dependências ausentes envolvendo chamadas "
            "em try-except ou mocks artificiais."
        ),
        (
            "   - Se um comando CLI, binário (ex: gcloud, git, uv) ou serviço falhou, "
            "investigue a causa raiz estrutural e o ambiente."
        ),
        (
            "   - Use os 5 Porquês para garantir que sua correção resolve "
            "a causa raiz profunda."
        ),
        "5. Diretrizes Arquiteturais Mandatórias:",
        "   - NUNCA defina funções aninhadas (exceto decoradores indispensáveis).",
        "   - NUNCA aninhe blocos try-except.",
        "   - NUNCA utilize _ (underscore) prefixado em variáveis soltas de módulo.",
        "   - Mantenha a complexidade cognitiva <= 15 (verificado por complexipy).",
        "   - Imports devem ser ordenados estritamente com isort, sem try-except.",
        "   - Respeite o PEP 8 estrito (88 colunas) e Google Style Docstrings.",
        (
            "6. Validação: Execute os sensores locais (`just verify` ou `pytest`) "
            "e garanta 100% de sucesso sem regressões."
        ),
    ]
    if plan.issue_id:
        lines.append(
            f"7. Vínculo da Issue: o corpo do Pull Request DEVE conter a linha "
            f"`Fixes #{plan.issue_id}` e a branch deve incluir "
            f"`issue-{plan.issue_id}`. Sem isso a esteira post-merge não "
            "identifica a issue e as ondas topológicas não são executadas."
        )
    return "\n".join(lines)


def build_bug_feedback_prompt(
    plan: BugPlan,
    test_file_path: str,
    feedback: str,
    iteration: int,
    max_iterations: int,
) -> str:
    """Constrói prompt de feedback prescritivo para iterações do ciclo de bugfix.

    Args:
        plan: Especificação formal do defeito (BugPlan).
        test_file_path: Caminho do arquivo de teste de reprodução TDD (Red).
        feedback: Diagnóstico com falhas nos testes ou sensores determinísticos.
        iteration: Número da iteração atual no ciclo interativo.
        max_iterations: Limite máximo de iterações configurado.

    Returns:
        Texto estruturado em Markdown com feedback detalhado para o agente.
    """
    lines = [
        (
            f"# ⚠️ Correção Incompleta: Falha na Verificação do Defeito "
            f"({iteration}/{max_iterations})"
        ),
        f"- **Defeito:** `{plan.title}`",
        f"- **Spoke Alvo:** `{plan.affected_spoke}`",
        f"- **Teste TDD:** `{test_file_path}`",
        "",
        "## ❌ Diagnóstico da Falha na Tentativa Anterior",
        "A tentativa anterior de correção não passou nos testes ou sensores:",
        "```",
        feedback.strip(),
        "```",
        "",
        "## 🎯 Instruções de Ajuste:",
        (
            f"1. Analise cuidadosamente a falha acima e corrija o código-fonte "
            f"em `{plan.affected_spoke}`."
        ),
        f"2. O teste `{test_file_path}` deve passar com sucesso (Fase Green).",
        (
            "3. Os sensores determinísticos (`just verify` ou pytest) devem ser "
            "100% aprovados sem regressões."
        ),
        (
            "4. Mantenha as diretrizes arquiteturais: proibidas funções aninhadas, "
            "proibidos try-except aninhados,"
        ),
        "   isort estrito, PEP 8 e docstrings Google Python Style.",
    ]
    if plan.issue_id:
        lines.append(f"5. Lembre-se de manter o vínculo com a issue `{plan.issue_id}`.")
    return "\n".join(lines)


def refine_bug_plan_with_llm(
    current_plan: BugPlan,
    refinement_instruction: str,
    manifest_repos: list[Any] | None = None,
    cloud_log: str | None = None,
    base_url: str = "",
    api_key: str = "",
    model_name: str = "",
    stream: bool = True,
    agent: Any = None,
    continue_session: bool | None = None,
) -> BugPlan:
    """Refina iterativamente o plano de bug com base nas orientações do usuário.

    Args:
        current_plan: Especificação atual do defeito.
        refinement_instruction: Instruções ou detalhes adicionais do usuário.
        manifest_repos: Lista opcional de repositórios conhecidos.
        cloud_log: Evidência opcional de log coletada do Cloud Logging.
        base_url: URL base opcional da API OpenAI.
        api_key: Chave opcional de API.
        model_name: Modelo LLM opcional.
        stream: Habilita streaming dos tokens no terminal.
        agent: Instância opcional de DetectedAgent para execução via CLI.
        continue_session: Se True, retoma a sessão. Padrão None (ativado).

    Returns:
        Nova instância de BugPlan com os refinamentos aplicados.
    """
    resolved_continue = bool(continue_session) if continue_session is not None else True
    repos_context = manifest_repos or []
    current_markdown = compile_bug_issue_markdown(current_plan)

    system_instruction = (
        "Você é um Arquiteto de Software e Engenheiro de QA especialista em "
        "Spec-Driven Development (SDD) e Domain-Driven Design (DDD).\n"
        "Sua missão é aprimorar e refinar uma especificação de bug existente "
        "com base no feedback do usuário.\n\n"
        "INSTRUÇÕES MANDATÓRIAS:\n"
        "1. Analise a especificação atual e o feedback do usuário.\n"
        "2. Enriqueça o sumário, comportamento esperado, passos de reprodução "
        "e regras de negócio.\n"
        "3. Preserve o spoke afetado caso esteja correto ou ajuste se o "
        "usuário solicitar.\n"
        "4. Responda ESTRITAMENTE em formato JSON puro com as chaves:\n"
        "{\n"
        '  "title": "[Bug] Título refinado",\n'
        '  "summary": "Resumo detalhado",\n'
        '  "observed_behavior": "Comportamento anômalo",\n'
        '  "expected_behavior": "Comportamento esperado pelo negócio",\n'
        '  "affected_spoke": "nome-do-spoke",\n'
        '  "affected_capability": "capacidade DDD",\n'
        '  "runtime_contract": "Classe.metodo",\n'
        '  "reproduction_steps": ["passo 1", "passo 2"],\n'
        '  "test_file_path": "tests/unit/test_exemplo.py",\n'
        '  "test_function_name": "test_exemplo",\n'
        '  "business_rule": "Regra formal",\n'
        '  "prompts": ["identificador/do/prompt"]\n'
        "}"
    )

    user_content = (
        f"Especificação Atual do Defeito:\n"
        f"```markdown\n{current_markdown}\n```\n\n"
        f"Instruções de Refinamento do Usuário:\n"
        f'"{refinement_instruction}"'
    )
    if cloud_log:
        user_content += (
            f"\n\nEvidência coletada no Cloud Logging:\n```json\n{cloud_log}\n```\n"
        )

    plan_data = None
    if agent is not None:
        agent_prompt = (
            f"{system_instruction}\n\n"
            f"{user_content}\n\n"
            "Responda estritamente com o bloco JSON contendo as chaves solicitadas."
        )
        runner = AgentRunner()
        exit_code, agent_output = runner.run_prompt(
            agent=agent,
            working_dir=Path("."),
            prompt_text=agent_prompt,
            task_label="refinamento técnico do defeito",
            continue_session=resolved_continue,
        )
        if exit_code == 0 and agent_output:
            plan_data = extract_json_payload_from_text(agent_output)

    if not plan_data:
        plan_data = call_llm_json_completion(
            system_instruction=system_instruction,
            user_content=user_content,
            base_url=base_url,
            api_key=api_key,
            model_name=model_name,
            stream=stream,
        )

    selected_log = cloud_log or current_plan.selected_cloud_log

    if not plan_data:
        return BugPlan(
            title=current_plan.title,
            summary=f"{current_plan.summary} (Refinado: {refinement_instruction})",
            observed_behavior=current_plan.observed_behavior,
            expected_behavior=current_plan.expected_behavior,
            affected_spoke=current_plan.affected_spoke,
            affected_capability=current_plan.affected_capability,
            runtime_contract=current_plan.runtime_contract,
            reproduction_steps=current_plan.reproduction_steps,
            test_file_path=current_plan.test_file_path,
            test_function_name=current_plan.test_function_name,
            business_rule=current_plan.business_rule,
            selected_cloud_log=selected_log,
            intake_prompt=f"{current_plan.intake_prompt} | {refinement_instruction}",
            issue_id=current_plan.issue_id,
            prompts=list(current_plan.prompts),
        )

    raw_spoke = plan_data.get("affected_spoke") or current_plan.affected_spoke
    resolved_spoke = resolve_most_probable_spoke(raw_spoke, repos_context)
    if resolved_spoke == "unknown":
        resolved_spoke = current_plan.affected_spoke

    refined_prompts: list[str] = [
        str(item) for item in (plan_data.get("prompts") or list(current_plan.prompts))
    ]

    refined_plan = BugPlan(
        title=plan_data.get("title") or current_plan.title,
        summary=plan_data.get("summary") or current_plan.summary,
        observed_behavior=(
            plan_data.get("observed_behavior") or current_plan.observed_behavior
        ),
        expected_behavior=(
            plan_data.get("expected_behavior") or current_plan.expected_behavior
        ),
        affected_spoke=resolved_spoke,
        affected_capability=(
            plan_data.get("affected_capability") or current_plan.affected_capability
        ),
        runtime_contract=(
            plan_data.get("runtime_contract") or current_plan.runtime_contract
        ),
        reproduction_steps=(
            plan_data.get("reproduction_steps") or current_plan.reproduction_steps
        ),
        test_file_path=(plan_data.get("test_file_path") or current_plan.test_file_path),
        test_function_name=(
            plan_data.get("test_function_name") or current_plan.test_function_name
        ),
        business_rule=(plan_data.get("business_rule") or current_plan.business_rule),
        selected_cloud_log=selected_log,
        intake_prompt=(
            f"{current_plan.intake_prompt} | Refinamento: {refinement_instruction}"
        ),
        issue_id=current_plan.issue_id,
        prompts=refined_prompts,
    )
    return enrich_bug_plan_topology(refined_plan, workspace_root=Path("."))


def resolve_github_repo_for_spoke(
    spoke_name: str,
    manifest_repos: list[Any] | None = None,
    default_org: str = "paralax-ia",
) -> str:
    """Resolve o repositório remoto no formato org/repo para o spoke informado.

    Args:
        spoke_name: Nome do spoke ou repositório.
        manifest_repos: Metadados dos repositórios conhecidos no manifest.yaml.
        default_org: Organização padrão no GitHub.

    Returns:
        String no formato 'org/repo' (ex: 'paralax-ia/customer-support-vehicles').
    """
    if not isinstance(spoke_name, str):
        return ""
    clean = re.sub(r"\s*\(.*?\)", "", spoke_name).strip()
    if "/" in clean:
        return clean

    for r in manifest_repos or []:
        if isinstance(r, dict) and r.get("name") == clean and r.get("repo"):
            return r["repo"]

    if clean and clean != "unknown":
        return f"{default_org}/{clean}"
    return clean


def create_github_bug_issue(
    plan: BugPlan,
    markdown_body: str,
    target_repo: str | None = None,
    ready: bool = False,
) -> tuple[int | None, str | None]:
    """Cria uma Issue formal no GitHub contendo o plano do defeito e labels canônicas.

    Args:
        plan: Instância do BugPlan com a especificação do defeito.
        markdown_body: Conteúdo formatado da Issue em Markdown.
        target_repo: Identificador 'org/repo' ou None.
        ready: Se True, anexa a label 'bug:ready', senão 'status:bug/planned'.

    Returns:
        Tupla `(issue_number, issue_url)` ou `(None, None)` em caso de falha.
    """
    labels = ["status:bug/planned"]
    if ready:
        labels.append("bug:ready")

    cmd = [
        "gh",
        "issue",
        "create",
        "--title",
        plan.title,
        "--body",
        markdown_body,
    ]
    for lbl in labels:
        cmd.extend(["--label", lbl])

    if target_repo and target_repo != "unknown":
        cmd.extend(["--repo", target_repo])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 and labels:
        fallback_cmd = [
            "gh",
            "issue",
            "create",
            "--title",
            plan.title,
            "--body",
            markdown_body,
        ]
        if target_repo and target_repo != "unknown":
            fallback_cmd.extend(["--repo", target_repo])
        proc = subprocess.run(fallback_cmd, capture_output=True, text=True, check=False)

    if proc.returncode != 0:
        return None, None

    created_url = proc.stdout.strip()
    match = re.search(r"/issues/(\d+)", created_url)
    created_num = int(match.group(1)) if match else None
    if created_num is not None:
        plan.issue_id = created_num
    return created_num, created_url


def update_github_bug_issue(
    issue_id: int | str,
    plan: BugPlan,
    markdown_body: str,
    target_repo: str | None = None,
) -> bool:
    """Atualiza o título e o corpo de uma Issue existente no GitHub.

    Args:
        issue_id: Identificador numérico da Issue.
        plan: Instância do BugPlan com os dados atualizados.
        markdown_body: Novo corpo em Markdown da Issue.
        target_repo: Identificador 'org/repo' opcional.

    Returns:
        True se a atualização foi bem-sucedida, senão False.
    """
    clean_id = str(issue_id).lstrip("#")
    cmd = [
        "gh",
        "issue",
        "edit",
        clean_id,
        "--title",
        plan.title,
        "--body",
        markdown_body,
    ]
    if target_repo and target_repo != "unknown":
        cmd.extend(["--repo", target_repo])

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode == 0


class StateBackendUnavailableError(RuntimeError):
    """Erro lançado quando Redis ou Elasticsearch obrigatórios estão inacessíveis."""


def resolve_redis_endpoint() -> tuple[str, int]:
    """Resolve host e porta do Redis a partir do ambiente e da config ativa.

    Returns:
        Tupla `(host, port)` do Redis central do harness.
    """
    cfg = get_active_config()
    host = (
        os.environ.get("HARNESS_REDIS_HOST", "")
        or cfg.redis.internal_host
        or cfg.redis.external_host
        or "127.0.0.1"
    )
    port = int(
        os.environ.get("HARNESS_REDIS_PORT", "0")
        or cfg.redis.internal_port
        or cfg.redis.external_port
        or 6379
    )
    return host, port


def resolve_elasticsearch_base_url() -> str:
    """Resolve a URL base do Elasticsearch a partir do ambiente e da config.

    Returns:
        URL base sem barra final, ou string vazia se não configurada.
    """
    cfg = get_active_config()
    return (
        os.environ.get("ES_URL", "").rstrip("/")
        or cfg.elasticsearch.external_url.rstrip("/")
        or cfg.elasticsearch.internal_url.rstrip("/")
    )


def check_redis_reachable() -> str | None:
    """Testa o Redis com `PING`.

    Returns:
        None se acessível; caso contrário, descrição da falha.
    """
    host, port = resolve_redis_endpoint()
    try:
        client = redis.Redis(host=host, port=port, socket_timeout=3)
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return f"Redis indisponível em {host}:{port} ({exc})"
    return None


def check_elasticsearch_reachable() -> str | None:
    """Testa o Elasticsearch com uma requisição GET na URL base.

    Returns:
        None se acessível; caso contrário, descrição da falha.
    """
    base_es = resolve_elasticsearch_base_url()
    if not base_es:
        return "Elasticsearch não configurado (ES_URL ausente)"
    req = urllib.request.Request(base_es)
    es_token = os.environ.get("ES_TOKEN", "").strip()
    if es_token:
        req.add_header("Authorization", f"Bearer {es_token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return None
            return f"Elasticsearch respondeu HTTP {resp.status} em {base_es}"
    except Exception as exc:  # noqa: BLE001
        return f"Elasticsearch indisponível em {base_es} ({exc})"


def ensure_state_backends_available() -> None:
    """Exige que Redis e Elasticsearch estejam acessíveis antes do bug flow.

    Raises:
        StateBackendUnavailableError: Se qualquer backend estiver inacessível,
            listando todos os que falharam.
    """
    failures = [
        failure
        for failure in (check_redis_reachable(), check_elasticsearch_reachable())
        if failure
    ]
    if failures:
        raise StateBackendUnavailableError("; ".join(failures))


def record_bug_state_in_redis(
    plan: BugPlan,
    stage: str,
    pr_number: int | None = None,
    pr_url: str | None = None,
    max_retries: int = 3,
) -> bool:
    """Registra ou atualiza o estado transacional do defeito no Redis central.

    Args:
        plan: Instância do BugPlan com os dados formais do defeito.
        stage: Estado atual da máquina de estados (ex: REPRODUCING, REPRODUCED,
            FIXING, RESOLVED, CLOSED).
        pr_number: Número opcional do Pull Request associado à correção.
        pr_url: URL opcional do Pull Request no GitHub.
        max_retries: Quantidade máxima de tentativas em caso de erro de conexão.

    Returns:
        True se o registro foi salvo com sucesso no Redis, False caso contrário.
    """
    host, port = resolve_redis_endpoint()

    issue_ref = str(plan.issue_id) if plan.issue_id else "unassigned"
    key = f"bug:{plan.affected_spoke}:{issue_ref}"
    now_str = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    payload = {
        "issue_id": plan.issue_id,
        "spoke": plan.affected_spoke,
        "capability": plan.affected_capability,
        "runtime_contract": plan.runtime_contract,
        "title": plan.title,
        "stage": stage,
        "test_file_path": plan.test_file_path,
        "test_function_name": plan.test_function_name,
        "business_rule": plan.business_rule,
        "linked_spec": plan.linked_spec,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "updated_at": now_str,
    }

    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            client = redis.Redis(
                host=host, port=port, decode_responses=True, socket_timeout=3
            )
            client.set(key, json.dumps(payload))
            if stage == "CLOSED":
                client.srem("bugs:active", key)
                client.sadd("bugs:archived", key)
            else:
                client.sadd("bugs:active", key)
            return True
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt < max_retries:
                time.sleep(0.5 * attempt)

    print(
        f"[State Tracker] Aviso ao persistir bug no Redis após "
        f"{max_retries} tentativas: {last_exc}",
        file=sys.stderr,
    )
    return False


def send_bug_telemetry_to_es(
    plan: BugPlan,
    stage: str,
    pr_number: int | None = None,
    pr_url: str | None = None,
    test_passed: bool = True,
) -> bool:
    """Envia payload de telemetria do ciclo de bugfix para o cluster Elasticsearch.

    Args:
        plan: Instância do BugPlan com a especificação do defeito.
        stage: Fase concluída no ciclo (ex: REPRODUCED, RESOLVED, CLOSED).
        pr_number: Número do Pull Request se aberto.
        pr_url: URL do Pull Request no GitHub se aberto.
        test_passed: Indica se a asserção do teste atendeu à fase.

    Returns:
        True se a telemetria foi enviada com sucesso, False caso contrário.
    """
    cfg = get_active_config()
    base_es = (
        os.environ.get("ES_URL", "").rstrip("/")
        or cfg.elasticsearch.external_url.rstrip("/")
        or cfg.elasticsearch.internal_url.rstrip("/")
    )
    es_idx = os.environ.get("ES_INDEX", "") or "harness-sensor-telemetry"
    if not base_es:
        return False

    resolved_url = f"{base_es}/{es_idx}/_doc"
    headers = {"Content-Type": "application/json"}
    es_token = os.environ.get("ES_TOKEN", "").strip()
    if es_token:
        headers["Authorization"] = f"Bearer {es_token}"

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "@timestamp": now,
        "event_type": "bug_lifecycle",
        "issue_id": plan.issue_id,
        "spoke": plan.affected_spoke,
        "capability": plan.affected_capability,
        "runtime_contract": plan.runtime_contract,
        "title": plan.title,
        "stage": stage,
        "test_file_path": plan.test_file_path,
        "test_function_name": plan.test_function_name,
        "business_rule": plan.business_rule,
        "linked_spec": plan.linked_spec,
        "pr_number": pr_number,
        "pr_url": pr_url,
        "test_passed": test_passed,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        resolved_url,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=4) as resp:
            return resp.status in (200, 201)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[Telemetry] Aviso ao despachar telemetria para o Elasticsearch: {exc}",
            file=sys.stderr,
        )
        return False


def update_github_issue_status_label(
    plan: BugPlan,
    new_status: str,
    remove_status: str | None = None,
    target_repo: str | None = None,
) -> bool:
    """Atualiza as labels de status da Issue do defeito no GitHub.

    Args:
        plan: Instância do BugPlan associado à Issue.
        new_status: Novo rótulo de status (ex: reproducing, reproduced,
            fixing, resolved).
        remove_status: Rótulo anterior a ser removido (opcional).
        target_repo: Repositório GitHub de destino opcional (owner/repo).

    Returns:
        True se a atualização foi executada com sucesso, False caso contrário.
    """
    if not plan.issue_id:
        return False

    repo = target_repo or resolve_github_repo_for_spoke(plan.affected_spoke)
    cmd = [
        "gh",
        "issue",
        "edit",
        str(plan.issue_id),
        "--add-label",
        f"status:bug/{new_status}",
    ]
    if repo and repo != "unknown":
        cmd.extend(["--repo", repo])
    if remove_status:
        cmd.extend(["--remove-label", f"status:bug/{remove_status}"])

    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return res.returncode == 0


def ensure_pr_links_issue(
    repo_dir: Path,
    pr_number: int | None,
    pr_body: str,
    issue_id: int | str | None,
) -> bool:
    """Garante que o corpo do PR referencie a issue com `Fixes #N`.

    O workflow `bug-post-merge` identifica a issue exclusivamente pelo corpo do
    PR (ou pelo nome da branch). PRs abertos previamente pelo agente de IA podem
    não conter a referência, o que impede o fechamento transacional.

    Args:
        repo_dir: Diretório do repositório local do spoke.
        pr_number: Número do Pull Request existente.
        pr_body: Corpo atual do Pull Request.
        issue_id: Número da issue associada ao defeito.

    Returns:
        True se o corpo foi atualizado com a referência, False se nada mudou.
    """
    if not issue_id or pr_number is None:
        return False
    closing_ref = re.compile(
        rf"(fixes|closes|resolves)\s+#{issue_id}\b", flags=re.IGNORECASE
    )
    if closing_ref.search(pr_body):
        return False
    new_body = f"{pr_body.rstrip()}\n\nFixes #{issue_id}\n"
    edit_proc = subprocess.run(
        ["gh", "pr", "edit", str(pr_number), "--body", new_body],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return edit_proc.returncode == 0


def publish_bug_pr(
    repo_dir: Path,
    plan: BugPlan,
) -> tuple[int | None, str | None, str]:
    """Prepara a branch, comita alterações pendentes e abre ou obtém o Pull Request.

    Args:
        repo_dir: Diretório do repositório local do spoke.
        plan: Instância do BugPlan com a especificação do defeito.

    Returns:
        Tupla contendo `(pr_number, pr_url, status_message)`.
    """
    branch_proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    current_branch = branch_proc.stdout.strip()

    if not current_branch or current_branch == "main":
        slug = re.sub(r"[^a-z0-9\-]+", "-", plan.title.lower()).strip("-")[:30]
        issue_tag = f"issue-{plan.issue_id}" if plan.issue_id else "repro"
        current_branch = f"agent/bug-{issue_tag}-{slug}"
        subprocess.run(
            ["git", "checkout", "-b", current_branch],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if status_proc.stdout.strip():
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        commit_msg = (
            f"fix({plan.affected_spoke}): {plan.title}"
            f"{f' (fixes #{plan.issue_id})' if plan.issue_id else ''}"
        )
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    push_proc = subprocess.run(
        ["git", "push", "-u", "origin", current_branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if push_proc.returncode != 0:
        err = push_proc.stderr.strip()
        return None, None, f"Falha no push da branch {current_branch}: {err}"

    pr_view_proc = subprocess.run(
        ["gh", "pr", "view", "--json", "number,url,body"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if pr_view_proc.returncode == 0 and pr_view_proc.stdout.strip():
        try:
            view_data = json.loads(pr_view_proc.stdout.strip())
            pr_num = view_data.get("number")
            pr_url = view_data.get("url")
            ensure_pr_links_issue(
                repo_dir=repo_dir,
                pr_number=pr_num,
                pr_body=view_data.get("body") or "",
                issue_id=plan.issue_id,
            )
            return (
                pr_num,
                pr_url,
                f"Pull Request #{pr_num} já ativo para a branch {current_branch}.",
            )
        except json.JSONDecodeError:
            pass

    pr_title = f"fix({plan.affected_spoke}): {plan.title}"
    body_lines = [
        "## 🛠️ Correção Automatizada de Bugfix (TDD Fail-First)\n",
        f"- **Defeito:** {plan.title}",
        f"- **Spoke Alvo:** `{plan.affected_spoke}`",
        f"- **Capacidade DDD:** `{plan.affected_capability}`",
        f"- **Teste TDD:** `{plan.test_file_path}` (`{plan.test_function_name}`)",
        f"- **Regra de Negócio:** `{plan.business_rule}`\n",
        "### 🧪 Ciclo de Validação",
        "- **Fase Red:** Teste de reprodução comprovado e documentado.",
        "- **Fase Green:** Teste unitário e sensores aprovados com sucesso.\n",
    ]
    if plan.issue_id:
        body_lines.append(f"Fixes #{plan.issue_id}\n")

    create_proc = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            pr_title,
            "--body",
            "\n".join(body_lines),
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if create_proc.returncode != 0:
        err = create_proc.stderr.strip()
        return None, None, f"Falha ao abrir Pull Request via GitHub CLI: {err}"

    out_url = create_proc.stdout.strip()
    match_num = re.search(r"/pull/(\d+)", out_url)
    num = int(match_num.group(1)) if match_num else None
    return num, out_url, "Pull Request criado com sucesso."


def merge_bug_pr_and_close_issue(
    repo_dir: Path,
    plan: BugPlan,
    pr_number: int,
) -> tuple[bool, str]:
    """Aprova e mescla o Pull Request e encerra transacionalmente a Issue vinculada.

    Args:
        repo_dir: Diretório do spoke onde o PR reside.
        plan: Instância do BugPlan associado.
        pr_number: Número do Pull Request no GitHub.

    Returns:
        Tupla contendo `(success, message)`.
    """
    merge_proc = subprocess.run(
        ["gh", "pr", "merge", str(pr_number), "--merge", "--auto"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_proc.returncode != 0:
        merge_proc = subprocess.run(
            ["gh", "pr", "merge", str(pr_number), "--merge"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
    if merge_proc.returncode != 0:
        err = merge_proc.stderr.strip()
        return False, f"Falha ao mesclar PR #{pr_number}: {err}"

    if plan.issue_id:
        close_comment = (
            f"Defeito formalmente resolvido e validado via ciclo TDD pelo "
            f"Pull Request #{pr_number} (Aprovado no Gate 3)."
        )
        repo = resolve_github_repo_for_spoke(plan.affected_spoke)
        cmd_close = [
            "gh",
            "issue",
            "close",
            str(plan.issue_id),
            "--comment",
            close_comment,
        ]
        if repo and repo != "unknown":
            cmd_close.extend(["--repo", repo])
        subprocess.run(cmd_close, capture_output=True, text=True, check=False)

    record_bug_state_in_redis(plan=plan, stage="CLOSED", pr_number=pr_number)
    send_bug_telemetry_to_es(plan=plan, stage="CLOSED", pr_number=pr_number)
    return (
        True,
        f"Pull Request #{pr_number} mesclado e Issue #{plan.issue_id} encerrada.",
    )
