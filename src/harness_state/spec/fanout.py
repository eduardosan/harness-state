"""Módulo de decomposição, geração cirúrgica e reconciliação de specs com spokes."""

import re
import subprocess
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Any

import yaml

from harness_state.models import SpecRun, SubTask
from harness_state.spec.lifecycle import extract_yaml_frontmatter, get_next_spec_id


@dataclass
class SpecSyncOutcome:
    """Resultado da sincronização reversa de uma sub-spec para o spec-hub."""

    success: bool
    spec_id: str
    repo: str
    updated_sections: list[str]
    message: str


def is_global_section(first_line: str) -> bool:
    """Verifica se a seção markdown de nível H2 é de contexto ou princípio global.

    Args:
        first_line: Primeira linha do cabeçalho H2 em caixa baixa.

    Returns:
        True se a seção deve ser preservada como contexto compartilhado.
    """
    global_tokens = [
        "contexto",
        "motivação",
        "princípio",
        "12-factor",
        "estrutura do funil",
        "arquitetura",
        "visão geral",
        "objetivo",
    ]
    return any(token in first_line for token in global_tokens)


def extract_repos_from_markdown(text: str) -> set[str]:
    """Extrai nomes de repositórios declarados no markdown ou frontmatter.

    Args:
        text: Conteúdo markdown da especificação.

    Returns:
        Conjunto de nomes de repositórios identificados.
    """
    found: set[str] = set()
    matches = re.findall(r"[\w.-]+/[\w.-]+", text)
    for m in matches:
        if "/" in m and not m.startswith("http") and not m.startswith("api/"):
            found.add(m)
    return found


def extract_other_repos(all_repos: set[str], current_repo: str) -> set[str]:
    """Retorna os identificadores dos demais repositórios da especificação.

    Args:
        all_repos: Conjunto de slugs completos de todos os repositórios.
        current_repo: Slug completo do repositório alvo atual.

    Returns:
        Conjunto de strings em caixa baixa dos demais repositórios para exclusão mútua.
    """
    other_repos: set[str] = set()
    current_short = current_repo.split("/")[-1].lower()
    for repo_item in all_repos:
        repo_short = repo_item.split("/")[-1].lower()
        if repo_short != current_short:
            other_repos.add(repo_short)
            other_repos.add(repo_item.lower())
    return other_repos


def filter_scope_subsections(
    scope_section: str,
    repo_name: str,
    short_repo: str,
    task_ids: set[str],
) -> str:
    """Filtra subseções H3 de escopo exclusivas do repositório alvo.

    Args:
        scope_section: Texto integral da seção H2 de escopo.
        repo_name: Slug completo do repositório (ex: paralax-ia/paralax-evo-crm).
        short_repo: Nome simples do repositório (ex: paralax-evo-crm).
        task_ids: Identificadores de tarefas pertinentes ao repositório.

    Returns:
        Seção de escopo contendo apenas o intro e as subseções do repositório.
    """
    subsections = re.split(r"\n(?=###\s+)", scope_section.strip())
    matched_subs: list[str] = [subsections[0]]

    for sub in subsections[1:]:
        sub_stripped = sub.strip()
        if not sub_stripped:
            continue
        sub_title = sub_stripped.splitlines()[0].lower()
        has_repo = short_repo.lower() in sub_title or repo_name.lower() in sub_title
        has_task = (
            any(tid.lower() in sub_title for tid in task_ids) if task_ids else False
        )
        if has_repo or has_task:
            matched_subs.append(sub_stripped)

    if len(matched_subs) > 1:
        return "\n\n".join(matched_subs)
    return subsections[0].strip()


def build_contract_repo_keywords(repo_name: str, short_repo: str) -> list[str]:
    """Monta lista de palavras-chave de contrato para o repositório alvo.

    Args:
        repo_name: Slug completo do repositório.
        short_repo: Nome simples do repositório.

    Returns:
        Lista de palavras-chave em minúsculas.
    """
    repo_keywords: list[str] = [short_repo.lower(), repo_name.lower()]
    if "crm" in short_repo.lower():
        repo_keywords.extend(
            ["evo/crm", "crmapiclient", "pipelineitem", "pipelinestage"]
        )
    elif "support" in short_repo.lower():
        repo_keywords.extend(
            ["support/", "pipeline_rules", "after_agent", "pipeline_callback"]
        )
    elif "argocd" in short_repo.lower():
        repo_keywords.extend(["argocd/", "deployment.yaml", "manifesto"])
    return repo_keywords


def is_contract_subsection_relevant(
    sub_stripped: str,
    short_repo: str,
    repo_keywords: list[str],
    other_repos: set[str],
) -> bool:
    """Avalia se uma subseção de contrato é pertinente ao repositório alvo.

    Args:
        sub_stripped: Texto da subseção de contrato sem espaços nas bordas.
        short_repo: Nome simples do repositório.
        repo_keywords: Palavras-chave do repositório.
        other_repos: Conjunto de outros repositórios alvos.

    Returns:
        True se a subseção deve ser incluída.
    """
    sub_lower = sub_stripped.lower()
    sub_title = sub_stripped.splitlines()[0].lower()

    mentions_other_repo = any(other in sub_title for other in other_repos)
    mentions_current_repo = any(kw in sub_title for kw in repo_keywords)

    if mentions_other_repo and not mentions_current_repo:
        return False

    if mentions_current_repo:
        return True

    in_body = any(kw in sub_lower for kw in repo_keywords)
    mentions_other_body = any(other in sub_lower for other in other_repos)

    if "api rest do crm" in sub_title and (
        "crm" in short_repo.lower() or "support" in short_repo.lower()
    ):
        return True
    return in_body and (not mentions_other_body or mentions_current_repo)


def filter_contract_subsections(
    contracts_section: str,
    repo_name: str,
    short_repo: str,
    task_ids: set[str],
    other_repos: set[str],
) -> str:
    """Filtra subseções H3 da seção de contratos pertinentes ao repositório.

    Args:
        contracts_section: Texto integral da seção H2 de contratos.
        repo_name: Slug completo do repositório.
        short_repo: Nome simples do repositório.
        task_ids: Identificadores de tarefas do repositório.
        other_repos: Conjunto de outros repositórios alvos.

    Returns:
        Seção de contratos contendo apenas as subseções pertinentes.
    """
    subsections = re.split(r"\n(?=###\s+)", contracts_section.strip())
    matched_subs: list[str] = [subsections[0]]
    repo_keywords = build_contract_repo_keywords(repo_name, short_repo)

    for sub in subsections[1:]:
        sub_stripped = sub.strip()
        if sub_stripped and is_contract_subsection_relevant(
            sub_stripped, short_repo, repo_keywords, other_repos
        ):
            matched_subs.append(sub_stripped)

    if len(matched_subs) > 1:
        return "\n\n".join(matched_subs)
    return ""


def build_gherkin_repo_keywords(repo_name: str, short_repo: str) -> list[str]:
    """Monta lista de palavras-chave Gherkin para o repositório alvo.

    Args:
        repo_name: Slug completo do repositório.
        short_repo: Nome simples do repositório.

    Returns:
        Lista de palavras-chave em minúsculas.
    """
    repo_keywords: list[str] = [short_repo.lower(), repo_name.lower()]
    if "crm" in short_repo.lower():
        repo_keywords.extend(
            ["crm", "sdk", "crmapiclient", "pipelineitem", "pipelinestage"]
        )
    elif "support" in short_repo.lower():
        repo_keywords.extend(
            [
                "agente",
                "bot",
                "support",
                "llm",
                "lead",
                "after_agent",
                "pipeline_rules",
            ]
        )
    elif "argocd" in short_repo.lower():
        repo_keywords.extend(
            ["argocd", "manifesto", "deployment", "env_vars", "k8s", "cluster"]
        )
    return repo_keywords


def is_gherkin_scenario_relevant(
    scn_stripped: str,
    repo_keywords: list[str],
    other_repos: set[str],
) -> bool:
    """Avalia se um cenário Gherkin é pertinente ao repositório alvo.

    Args:
        scn_stripped: Texto do cenário Gherkin sem espaços nas bordas.
        repo_keywords: Palavras-chave do repositório.
        other_repos: Conjunto de outros repositórios alvos.

    Returns:
        True se o cenário deve ser mantido.
    """
    scn_lower = scn_stripped.lower()
    scn_title = scn_stripped.splitlines()[0].lower()

    is_cross_cutting = (
        "configuração" in scn_lower and "git" in scn_lower
    ) or "12-factor" in scn_lower

    if is_cross_cutting:
        return True

    title_mentions_other = any(other in scn_title for other in other_repos)
    title_mentions_current = any(kw in scn_title for kw in repo_keywords)

    if title_mentions_other and not title_mentions_current:
        return False

    mentions_other = any(other in scn_lower for other in other_repos)
    mentions_current = any(kw in scn_lower for kw in repo_keywords)
    return mentions_current or not mentions_other


def filter_gherkin_scenarios(
    gherkin_section: str,
    repo_name: str,
    short_repo: str,
    task_ids: set[str],
    other_repos: set[str],
) -> str:
    """Filtra cenários Gherkin pertinentes ao repositório alvo.

    Args:
        gherkin_section: Texto integral da seção H2 de critérios de aceitação.
        repo_name: Slug completo do repositório.
        short_repo: Nome simples do repositório.
        task_ids: Identificadores de tarefas do repositório.
        other_repos: Conjunto de outros repositórios alvos.

    Returns:
        Seção de critérios de aceitação com os cenários pertinentes.
    """
    scenarios = re.split(
        r"\n(?=###\s+Cenário|\n###\s+Scenario|\n###\s+)",
        gherkin_section.strip(),
    )
    matched_scenarios: list[str] = [scenarios[0]]
    repo_keywords = build_gherkin_repo_keywords(repo_name, short_repo)

    for scn in scenarios[1:]:
        scn_stripped = scn.strip()
        if scn_stripped and is_gherkin_scenario_relevant(
            scn_stripped, repo_keywords, other_repos
        ):
            matched_scenarios.append(scn_stripped)

    if len(matched_scenarios) > 1:
        return "\n\n".join(matched_scenarios)
    return gherkin_section.strip()


def filter_rollout_subsections(
    rollout_section: str,
    repo_name: str,
    short_repo: str,
) -> str:
    """Filtra passos do plano de rollout pertinentes ao repositório alvo.

    Args:
        rollout_section: Texto integral da seção H2 de rollout.
        repo_name: Slug completo do repositório.
        short_repo: Nome simples do repositório.

    Returns:
        Texto do rollout contendo os passos do repositório.
    """
    lines = rollout_section.strip().splitlines()
    header_lines: list[str] = []
    filtered_lines: list[str] = []

    for line in lines:
        line_lower = line.lower()
        is_bullet = (
            line.strip().startswith("-")
            or line.strip().startswith("*")
            or (len(line.strip()) > 2 and line.strip()[:2].isdigit())
        )
        if line.startswith("## ") or not is_bullet:
            header_lines.append(line)
        elif short_repo.lower() in line_lower or repo_name.lower() in line_lower:
            filtered_lines.append(line)

    if filtered_lines:
        return "\n".join(header_lines + [""] + filtered_lines)
    return rollout_section.strip()


def filter_single_spec_section(
    sec_stripped: str,
    repo_name: str,
    short_repo: str,
    task_ids: set[str],
    other_repos: set[str],
) -> str:
    """Filtra uma única seção H2 do corpo da spec para o repositório alvo.

    Args:
        sec_stripped: Texto da seção H2 sem espaços nas bordas.
        repo_name: Nome do repositório alvo.
        short_repo: Nome simples do repositório.
        task_ids: Identificadores de subtarefas do repositório.
        other_repos: Conjunto de outros repositórios alvos.

    Returns:
        Seção filtrada ou string vazia se irrelevante.
    """
    first_line = sec_stripped.splitlines()[0].lower()

    if is_global_section(first_line):
        return sec_stripped
    if "escopo" in first_line or "repositórios" in first_line:
        return filter_scope_subsections(sec_stripped, repo_name, short_repo, task_ids)
    if "contrato" in first_line:
        return filter_contract_subsections(
            sec_stripped, repo_name, short_repo, task_ids, other_repos
        )
    if "critérios" in first_line or "gherkin" in first_line:
        return filter_gherkin_scenarios(
            sec_stripped, repo_name, short_repo, task_ids, other_repos
        )
    if "rollout" in first_line:
        return filter_rollout_subsections(sec_stripped, repo_name, short_repo)
    if short_repo.lower() in sec_stripped.lower():
        return sec_stripped
    return ""


def filter_relevant_spec_sections(
    body: str,
    repo_name: str,
    task_id: str = "",
    tasks: list[SubTask] | None = None,
    all_target_repos: set[str] | None = None,
) -> str:
    """Filtra cirurgicamente as seções do corpo da spec pertinentes ao repositório.

    Args:
        body: Corpo markdown completo da especificação principal.
        repo_name: Nome do repositório alvo (ex: paralax-ia/paralax-evo-crm).
        task_id: Identificador opcional da subtarefa.
        tasks: Lista opcional de subtarefas pertencentes ao repositório.
        all_target_repos: Conjunto opcional de todos os repositórios alvos da spec.

    Returns:
        Texto markdown composto pelas seções relevantes ao repositório.
    """
    short_repo = repo_name.split("/")[-1]
    task_ids = {t.id for t in (tasks or [])}
    if task_id:
        task_ids.add(task_id)

    known_repos = all_target_repos or (extract_repos_from_markdown(body) | {repo_name})
    other_repos = extract_other_repos(known_repos, repo_name)

    sections = re.split(r"\n(?=##\s+)", "\n" + body)
    relevant_sections: list[str] = []

    for sec in sections:
        sec_stripped = sec.strip()
        if not sec_stripped:
            continue
        filtered = filter_single_spec_section(
            sec_stripped, repo_name, short_repo, task_ids, other_repos
        )
        if filtered:
            relevant_sections.append(filtered)

    return "\n\n".join(relevant_sections).strip()


def resolve_primary_task_attributes(
    spec_id: str,
    short_repo: str,
    task: SubTask | None,
    all_tasks: list[SubTask],
) -> tuple[str, int, str]:
    """Determina os atributos primários (id, wave, branch) da subtarefa do spoke.

    Args:
        spec_id: Identificador da spec principal.
        short_repo: Nome simples do repositório.
        task: Subtarefa principal opcional.
        all_tasks: Lista de subtarefas do repositório.

    Returns:
        Tupla `(primary_task_id, primary_wave, primary_branch)`.
    """
    primary = task or (all_tasks[0] if all_tasks else None)
    if primary:
        return primary.id, primary.wave, primary.branch
    return "task-1", 1, f"feat/{spec_id.lower()}-{short_repo}"


def is_prompt_for_fanout_repo(
    p: Any,
    repo_name: str,
    short_repo: str,
    clean_repo: str,
    target_count: int,
) -> bool:
    """Verifica se um prompt declarado é compatível com o repositório da sub-spec.

    Args:
        p: Descritor de prompt (dicionário ou string).
        repo_name: Nome completo do repositório.
        short_repo: Nome curto do repositório.
        clean_repo: Nome normalizado com underscores.
        target_count: Total de repositórios alvos na spec pai.

    Returns:
        True se o prompt deve ser propagado para o spoke.
    """
    if isinstance(p, dict):
        p_repo = str(p.get("target_repo", ""))
        p_repo_short = p_repo.split("/")[-1] if p_repo else ""
        return not p_repo or p_repo == repo_name or p_repo_short == short_repo

    if target_count <= 1:
        return True

    p_str = str(p)
    p_prefix = p_str.split("/")[0]
    return p_prefix in clean_repo or clean_repo in p_prefix or p_prefix in short_repo


def filter_fanout_prompts_for_repo(
    prompts: list[Any],
    repo_name: str,
    short_repo: str,
    all_target_repos: set[str] | list[Any] | None,
) -> list[Any]:
    """Filtra prompts no fanout mantendo apenas os pertinentes ao repositório alvo.

    Args:
        prompts: Lista de prompts brutos da spec pai.
        repo_name: Nome completo do repositório
            (ex: paralax-ia/customer-support-vehicles).
        short_repo: Nome curto do repositório (ex: customer-support-vehicles).
        all_target_repos: Conjunto ou lista de todos os repositórios alvos da spec.

    Returns:
        Lista filtrada contendo apenas prompts pertinentes à sub-spec.
    """
    clean_repo = short_repo.replace("-", "_")
    target_count = len(all_target_repos) if all_target_repos is not None else 1
    return [
        p
        for p in prompts
        if is_prompt_for_fanout_repo(p, repo_name, short_repo, clean_repo, target_count)
    ]


def resolve_primary_issue(
    task: SubTask | None,
    all_tasks: list[SubTask],
    primary_task_id: str,
) -> int | None:
    """Resolve o número da issue associada à tarefa primária da sub-spec.

    Args:
        task: Tarefa primária opcional.
        all_tasks: Lista de todas as tarefas da spec.
        primary_task_id: Identificador da tarefa principal.

    Returns:
        Número da issue de tracking ou None se não atribuída.
    """
    if task and task.issue_number:
        return task.issue_number
    for t in all_tasks:
        if t.id == primary_task_id and t.issue_number:
            return t.issue_number
    return None


def build_sub_spec_header(
    yaml_header: str,
    spec_id: str,
    task_title: str,
    main_spec_name: str,
    repo_name: str,
    primary_task_id: str,
    primary_wave: int,
    primary_branch: str,
    primary_issue: int | None,
) -> str:
    """Compõe o cabeçalho formatado em Markdown da sub-spec de um spoke.

    Args:
        yaml_header: Metadados YAML serializados.
        spec_id: Identificador da especificação.
        task_title: Título descritivo da tarefa.
        main_spec_name: Nome do arquivo da spec principal.
        repo_name: Nome do repositório spoke.
        primary_task_id: Identificador da subtarefa primária.
        primary_wave: Onda de execução da subtarefa primária.
        primary_branch: Branch de trabalho da subtarefa.
        primary_issue: Número opcional da issue de rastreamento.

    Returns:
        Bloco de cabeçalho Markdown pronto para composição.
    """
    lines = [
        f"---\n{yaml_header}\n---\n\n",
        f"# {spec_id}: {task_title}\n\n",
        f"> **Parent Spec:** `{spec_id}` ({main_spec_name})  \n",
        f"> **Repositório Alvo:** `{repo_name}`  \n",
        f"> **Subtarefa Principal:** `{primary_task_id}` (Onda {primary_wave})  \n",
        f"> **Branch:** `{primary_branch}`  \n",
    ]
    if primary_issue is not None:
        lines.append(f"> **Issue de Rastreamento:** #{primary_issue}  \n")
    lines.append("> **Status:** `IN_PROGRESS`\n\n")

    closes_directive = (
        f"Closes #{primary_issue}"
        if primary_issue is not None
        else "Closes #<issue_number>"
    )
    lines.append(
        "> [!IMPORTANT]\n"
        f"> Ao abrir o Pull Request via `gh pr create`, inclua obrigatoriamente `{closes_directive}` "
        "no corpo do PR para encerramento automático da issue vinculada após o merge.\n\n"
        "---\n\n"
    )
    return "".join(lines)


def build_repo_spec_frontmatter(
    spec_id: str,
    task_title: str,
    repo_name: str,
    primary_task_id: str,
    primary_wave: int,
    primary_branch: str,
    tasks_metadata: list[dict[str, Any]],
    products: Any,
    capability: str,
    prompts: Any,
    short_repo: str,
    all_target_repos: set[str] | None,
) -> dict[str, Any]:
    """Constrói o dicionário de frontmatter para a sub-spec de um spoke.

    Args:
        spec_id: Identificador da especificação.
        task_title: Título composto da tarefa.
        repo_name: Slug do repositório.
        primary_task_id: Identificador da tarefa principal.
        primary_wave: Onda de execução principal.
        primary_branch: Branch de trabalho principal.
        tasks_metadata: Metadados das tarefas da sub-spec.
        products: Produtos associados.
        capability: Business Capability associada.
        prompts: Lista de prompts da especificação.
        short_repo: Nome simples do repositório.
        all_target_repos: Conjunto de repositórios da spec.

    Returns:
        Dicionário formatado de frontmatter.
    """
    prod_list = [products] if isinstance(products, str) else list(products)
    frontmatter: dict[str, Any] = {
        "spec_id": spec_id,
        "title": task_title,
        "parent_spec": spec_id,
        "repo": repo_name,
        "task_id": primary_task_id,
        "wave": primary_wave,
        "branch": primary_branch,
        "tasks": tasks_metadata,
        "product": prod_list,
        "capability": capability,
        "status": "IN_PROGRESS",
    }
    if prompts:
        filtered = filter_fanout_prompts_for_repo(
            prompts=prompts,
            repo_name=repo_name,
            short_repo=short_repo,
            all_target_repos=all_target_repos,
        )
        if filtered:
            frontmatter["prompts"] = filtered
    return frontmatter


def generate_repo_spec(
    main_spec_path: Path,
    repo_name: str,
    task: SubTask | None = None,
    tasks: list[SubTask] | None = None,
    main_spec: SpecRun | None = None,
    all_target_repos: set[str] | None = None,
) -> str:
    """Gera especificação técnica focada e autocontida para o repositório spoke.

    Args:
        main_spec_path: Caminho da especificação central no spec-hub.
        repo_name: Identificador do repositório alvo (ex: paralax-ia/paralax-evo-crm).
        task: Objeto `SubTask` opcional correspondente à tarefa ativa.
        tasks: Lista opcional de tarefas do repositório na especificação.
        main_spec: Instância opcional de `SpecRun` já carregada.
        all_target_repos: Conjunto opcional de todos os repositórios da spec.

    Returns:
        String contendo a especificação markdown completa formatada para o repositório.
    """
    raw_text = main_spec_path.read_text(encoding="utf-8")
    frontmatter, body = extract_yaml_frontmatter(raw_text)

    spec_id = (
        main_spec.spec_id if main_spec else str(frontmatter.get("spec_id") or "SPEC")
    )
    base_title = (
        main_spec.title if main_spec else str(frontmatter.get("title") or spec_id)
    )
    short_repo = repo_name.split("/")[-1]
    task_title = f"{base_title} - {short_repo}"

    products = main_spec.product if main_spec else frontmatter.get("product", [])
    capability = (
        main_spec.capability if main_spec else str(frontmatter.get("capability") or "")
    )

    all_tasks = tasks or ([task] if task else [])
    tasks_metadata: list[dict[str, Any]] = [
        {
            "id": t.id,
            "wave": t.wave,
            "branch": t.branch,
            "expected_version": t.expected_version or "N/A",
        }
        for t in all_tasks
    ]

    primary_task_id, primary_wave, primary_branch = resolve_primary_task_attributes(
        spec_id, short_repo, task, all_tasks
    )

    prompts = frontmatter.get("prompts", []) or (main_spec.prompts if main_spec else [])
    repo_frontmatter = build_repo_spec_frontmatter(
        spec_id=spec_id,
        task_title=task_title,
        repo_name=repo_name,
        primary_task_id=primary_task_id,
        primary_wave=primary_wave,
        primary_branch=primary_branch,
        tasks_metadata=tasks_metadata,
        products=products,
        capability=capability,
        prompts=prompts,
        short_repo=short_repo,
        all_target_repos=all_target_repos,
    )

    yaml_header = yaml.safe_dump(
        repo_frontmatter, sort_keys=False, allow_unicode=True
    ).strip()

    filtered_body = filter_relevant_spec_sections(
        body=body,
        repo_name=repo_name,
        task_id=primary_task_id,
        tasks=all_tasks,
        all_target_repos=all_target_repos,
    )

    primary_issue = resolve_primary_issue(task, all_tasks, primary_task_id)
    header_block = build_sub_spec_header(
        yaml_header=yaml_header,
        spec_id=spec_id,
        task_title=task_title,
        main_spec_name=main_spec_path.name,
        repo_name=repo_name,
        primary_task_id=primary_task_id,
        primary_wave=primary_wave,
        primary_branch=primary_branch,
        primary_issue=primary_issue,
    )

    return f"{header_block}{filtered_body}\n"


def save_repo_spec(
    repo_dir: Path,
    spec_id: str,
    content: str,
    filename: str | None = None,
    task_id: str = "",
) -> Path:
    """Salva a especificação técnica na pasta `specs/` do repositório spoke.

    Proteção contra colisão (SPEC-004 B1): o arquivo do spoke é identificado
    pelo par `(spec_id, task_id)`. Sobrescreve um candidato existente apenas
    quando o frontmatter dele declara o MESMO `task_id` (idempotência de
    re-run da mesma fatia). Caso contrário — incluindo a mestre do hub, cujo
    frontmatter não tem `task_id` — grava arquivo novo com o próximo
    identificador sequencial disponível, preservando `parent_spec`.

    Args:
        repo_dir: Diretório raiz do repositório spoke local.
        spec_id: Identificador da especificação (ex: SPEC-004).
        content: Conteúdo completo em Markdown da especificação.
        filename: Nome opcional do arquivo; se omitido, busca existente ou usa
            `{spec_id}.md`.
        task_id: Identificador da fatia/subtarefa corrente (ex: task-3).

    Returns:
        Instância de `Path` apontando para o arquivo salvo.
    """
    specs_dir = repo_dir / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)

    target_file: Path
    if filename:
        target_file = specs_dir / filename
    elif task_id:
        target_file, content = resolve_slice_target(
            specs_dir, spec_id, task_id, content
        )
    else:
        target_file = resolve_plain_target(specs_dir, spec_id)

    target_file.write_text(content, encoding="utf-8")
    return target_file


def resolve_plain_target(specs_dir: Path, spec_id: str) -> Path:
    """Resolve o destino legado (sem task_id): candidato existente ou `{spec_id}.md`.

    Args:
        specs_dir: Diretório `specs/` do repositório alvo.
        spec_id: Identificador da especificação.

    Returns:
        Path de destino do arquivo.
    """
    candidates = list(specs_dir.glob(f"{spec_id}*.md"))
    if candidates:
        return candidates[0]
    return specs_dir / f"{spec_id}.md"


def find_same_slice(candidates: list[Path], task_id: str) -> Path | None:
    """Encontra o candidato que pertence à MESMA fatia (frontmatter com task_id igual).

    Args:
        candidates: Arquivos candidatos com prefixo `{spec_id}`.
        task_id: Identificador da fatia corrente.

    Returns:
        Path do arquivo da mesma fatia, ou None se nenhum casar.
    """
    for candidate in candidates:
        frontmatter, _ = extract_yaml_frontmatter(candidate.read_text(encoding="utf-8"))
        if str(frontmatter.get("task_id") or "") == task_id:
            return candidate
    return None


def resolve_collision_target(
    specs_dir: Path, spec_id: str, content: str
) -> tuple[Path, str]:
    """Resolve colisão: próximo id com frontmatter renomeado, parent_spec preservado.

    Args:
        specs_dir: Diretório `specs/` do repositório alvo.
        spec_id: Identificador da especificação original.
        content: Conteúdo completo da fatia.

    Returns:
        Tupla `(path_novo, content_com_spec_id_renomeado)`.
    """
    resolved_spec_id = get_next_spec_id(specs_dir)
    resolved_content = re.sub(
        rf"^(spec_id:\s*){re.escape(spec_id)}\b",
        rf"\g<1>{resolved_spec_id}",
        content,
        count=1,
        flags=re.MULTILINE,
    )
    target = specs_dir / build_collision_filename(resolved_spec_id, resolved_content)
    return target, resolved_content


def resolve_slice_target(
    specs_dir: Path, spec_id: str, task_id: str, content: str
) -> tuple[Path, str]:
    """Resolve o destino da fatia com proteção contra colisão (SPEC-004 B1).

    Sobrescreve apenas o arquivo da MESMA fatia — identidade do arquivo é o
    par `(parent_spec, task_id)` no frontmatter: primeiro entre os candidatos
    por prefixo; se nenhum casar (fatia já renomeada em colisão anterior,
    ex: no hub onde um `spec_id` declara mestre como `target_repositories`),
    varre todo o diretório por identidade. Só grava arquivo novo com próximo
    id quando a fatia é genuinamente inédita.

    Args:
        specs_dir: Diretório `specs/` do repositório alvo.
        spec_id: Identificador da especificação.
        task_id: Identificador da fatia corrente.
        content: Conteúdo completo da fatia.

    Returns:
        Tupla `(path_destino, content_final)` — `content_final` tem o
        `spec_id` renomeado apenas em caso de colisão.
    """
    candidates = list(specs_dir.glob(f"{spec_id}*.md"))
    same_slice = find_same_slice(candidates, task_id)
    if same_slice is None:
        same_slice, resolved_id = find_slice_by_identity(specs_dir, spec_id, task_id)
        if same_slice is not None:
            content = re.sub(
                rf"^(spec_id:\s*){re.escape(spec_id)}\b",
                rf"\g<1>{resolved_id}",
                content,
                count=1,
                flags=re.MULTILINE,
            )
            return same_slice, content
    if same_slice is not None:
        return same_slice, content
    if not candidates:
        return specs_dir / f"{spec_id}.md", content
    return resolve_collision_target(specs_dir, spec_id, content)


def find_slice_by_identity(
    specs_dir: Path, spec_id: str, task_id: str
) -> tuple[Path | None, str]:
    """Busca a fatia da tarefa corrente varrendo todo o diretório specs/.

    A identidade do arquivo do spoke é o par `(parent_spec, task_id)` no
    frontmatter — cobre fatias renomeadas em colisões anteriores, cujo nome
    de arquivo não contém mais o `spec_id` da mestre.

    Args:
        specs_dir: Diretório `specs/` do repositório alvo.
        spec_id: Identificador da mestre (valor esperado em `parent_spec`).
        task_id: Identificador da fatia corrente.

    Returns:
        Tupla `(path_da_fatia_ou_None, spec_id_resolvido_do_arquivo)`.
    """
    for spec_file in sorted(specs_dir.glob("*.md")):
        frontmatter, _ = extract_yaml_frontmatter(spec_file.read_text(encoding="utf-8"))
        if str(frontmatter.get("task_id") or "") != task_id:
            continue
        if str(frontmatter.get("parent_spec") or "") != spec_id:
            continue
        return spec_file, str(frontmatter.get("spec_id") or spec_id)
    return None, spec_id


def build_collision_filename(resolved_spec_id: str, content: str) -> str:
    """Deriva o nome `{SPEC-NNN}-{slug}.md` da fatia em colisão (kebab-case, 60 chars).

    Args:
        resolved_spec_id: Identificador novo da fatia (ex: SPEC-003).
        content: Conteúdo da especificação, com frontmatter e título.

    Returns:
        Nome de arquivo seguro para o filesystem.
    """
    title = ""
    frontmatter, body = extract_yaml_frontmatter(content)
    title = str(frontmatter.get("title") or "")
    if not title:
        for line in body.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower(), flags=re.UNICODE).strip("-")
    slug = slug[:60].rstrip("-")
    if not slug:
        slug = "slice"
    return f"{resolved_spec_id}-{slug}.md"


def mark_repo_spec_status(
    repo_dir: Path,
    spec_id: str,
    new_status: str = "IMPLEMENTED",
    task_id: str = "",
) -> bool:
    """Atualiza o status no frontmatter da especificação do repo-alvo.

    Sem `task_id`, o alvo é a MESTRE do repo (arquivo `{spec_id}.md` exato
    ou frontmatter `spec_id == spec_id` sem `task_id`) — fatias com o mesmo
    prefixo nunca são tocadas (SPEC-005 D2). Com `task_id`, marca apenas a
    fatia específica (frontmatter idêntico em `spec_id` e `task_id`).
    Exceção de compatibilidade single-file (spoke): quando existe exatamente
    UM candidato com `spec_id == spec_id`, ele é marcado (comportamento
    legado). Sem alvo determinável (zero ou múltiplos) → False honesto,
    nada tocado.

    Args:
        repo_dir: Diretório raiz do repositório alvo.
        spec_id: Identificador da especificação (ex: SPEC-004).
        new_status: Novo status formal (ex: IMPLEMENTED, APPROVED, CLOSED).
        task_id: Identificador da fatia a marcar (vazio = mestre).

    Returns:
        True se a especificação foi localizada e atualizada com sucesso.
    """
    specs_dir = repo_dir / "specs"
    if not specs_dir.is_dir():
        return False
    target_file = resolve_mark_target(specs_dir, spec_id, task_id)
    if target_file is None:
        return False

    content = target_file.read_text(encoding="utf-8")
    frontmatter, body = extract_yaml_frontmatter(content)

    frontmatter["status"] = new_status
    updated_yaml = yaml.safe_dump(
        frontmatter, sort_keys=False, allow_unicode=True
    ).strip()

    new_content = f"---\n{updated_yaml}\n---\n\n{body.strip()}\n"
    target_file.write_text(new_content, encoding="utf-8")
    return True


def format_pr_reference(pr_number: int | None, pr_url: str | None) -> str:
    """Formata o link markdown do Pull Request para anotação na spec.

    Args:
        pr_number: Número do Pull Request.
        pr_url: URL pública do Pull Request.

    Returns:
        String formatada (ex: ` [PR #123](url)` ou ` [PR #123]` ou string vazia).
    """
    if pr_number is None:
        return ""
    if pr_url:
        return f" [PR #{pr_number}]({pr_url})"
    return f" [PR #{pr_number}]"


def is_matching_subtask_line(
    line: str,
    task_id: str,
    repo: str,
) -> bool:
    """Verifica se uma linha de checklist corresponde à subtarefa informada.

    Args:
        line: Linha de texto da especificação.
        task_id: Identificador da tarefa (ex: `task-2` ou `2`).
        repo: Slug do repositório (ex: `eduardosan/harness-state`).

    Returns:
        True se a linha corresponder à subtarefa.
    """
    stripped = line.strip()
    if not stripped.startswith(("- [ ]", "- [x]", "- [X]")):
        return False

    short_id = task_id.removeprefix("task-").strip()
    if short_id and re.search(
        rf"\*\*Sub-tarefa\s*{re.escape(short_id)}\b", stripped, re.IGNORECASE
    ):
        return True

    if repo:
        clean_repo = repo.strip()
        short_repo = clean_repo.split("/")[-1]
        if f"`{clean_repo}`" in stripped or f"`{short_repo}`" in stripped:
            return True

    return False


def mark_single_subtask_line(
    line: str,
    pr_number: int | None,
    pr_url: str | None,
) -> str:
    """Converte um item `- [ ]` em `- [x]` e adiciona referência de PR se ausente.

    Args:
        line: Linha de texto correspondente à subtarefa.
        pr_number: Número opcional do PR a ser vinculado.
        pr_url: URL opcional do PR a ser vinculada.

    Returns:
        Linha atualizada com `[x]` e eventual link de PR.
    """
    updated_line = re.sub(r"^(\s*-\s*\[)[ xX](\])", r"\g<1>x\2", line)
    if pr_number is None:
        return updated_line

    if f"PR #{pr_number}" in updated_line:
        return updated_line

    pr_ref = format_pr_reference(pr_number, pr_url)
    return f"{updated_line.rstrip()}{pr_ref}\n" if line.endswith("\n") else f"{updated_line.rstrip()}{pr_ref}"


def mark_subtask_completed_in_spec_text(
    content: str,
    task_id: str = "",
    repo: str = "",
    pr_number: int | None = None,
    pr_url: str | None = None,
) -> str:
    """Marca o checkbox da subtarefa como `[x]` no corpo Markdown da spec.

    Args:
        content: Conteúdo completo do arquivo Markdown da especificação.
        task_id: Identificador da subtarefa (ex: `task-1`).
        repo: Nome ou slug do repositório alvo.
        pr_number: Número opcional do Pull Request.
        pr_url: URL opcional do Pull Request.

    Returns:
        Conteúdo atualizado com a subtarefa marcada como concluída.
    """
    lines = content.splitlines(keepends=True)
    new_lines: list[str] = []
    marked = False

    for line in lines:
        if not marked and is_matching_subtask_line(line, task_id, repo):
            new_lines.append(mark_single_subtask_line(line, pr_number, pr_url))
            marked = True
        else:
            new_lines.append(line)

    return "".join(new_lines)


def mark_subtask_completed_in_spec_file(
    spec_file: Path,
    task_id: str = "",
    repo: str = "",
    pr_number: int | None = None,
    pr_url: str | None = None,
) -> bool:
    """Atualiza o arquivo Markdown da spec marcando a subtarefa como `[x]`.

    Args:
        spec_file: Caminho do arquivo de especificação.
        task_id: Identificador da subtarefa (ex: `task-1`).
        repo: Nome ou slug do repositório alvo.
        pr_number: Número opcional do Pull Request.
        pr_url: URL opcional do Pull Request.

    Returns:
        True se o arquivo existia e foi modificado, False caso contrário.
    """
    if not spec_file.is_file():
        return False

    original_text = spec_file.read_text(encoding="utf-8")
    updated_text = mark_subtask_completed_in_spec_text(
        content=original_text,
        task_id=task_id,
        repo=repo,
        pr_number=pr_number,
        pr_url=pr_url,
    )

    if updated_text != original_text:
        spec_file.write_text(updated_text, encoding="utf-8")
        return True

    return False



def collect_owned_specs(
    specs_dir: Path, spec_id: str
) -> list[tuple[Path, dict[str, Any]]]:
    """Coleta candidatos com prefixo cujo frontmatter declara o `spec_id` informado.

    Args:
        specs_dir: Diretório `specs/` do repo-alvo.
        spec_id: Identificador da mestre.

    Returns:
        Lista de `(caminho, frontmatter)` cujo `spec_id` é o informado.
    """
    candidates = sorted(specs_dir.glob(f"{spec_id}*.md"))
    owned: list[tuple[Path, dict[str, Any]]] = []
    for candidate in candidates:
        frontmatter, _ = extract_yaml_frontmatter(candidate.read_text(encoding="utf-8"))
        if str(frontmatter.get("spec_id") or "") == str(spec_id):
            owned.append((candidate, frontmatter))
    return owned


def find_renamed_slice(specs_dir: Path, spec_id: str, task_id: str) -> Path | None:
    """Busca fatia renomeada por identidade (parent_spec + task_id) — critério do B1.

    Args:
        specs_dir: Diretório `specs/` do repo-alvo.
        spec_id: Identificador da mestre (valor em `parent_spec`).
        task_id: Identificador da fatia desejada.

    Returns:
        Path da fatia, ou None quando não encontrada.
    """
    for spec_file in sorted(specs_dir.glob("*.md")):
        frontmatter, _ = extract_yaml_frontmatter(spec_file.read_text(encoding="utf-8"))
        if str(frontmatter.get("task_id") or "") == task_id and str(
            frontmatter.get("parent_spec") or ""
        ) == str(spec_id):
            return spec_file
    return None


def resolve_mark_target(specs_dir: Path, spec_id: str, task_id: str) -> Path | None:
    """Resolve o arquivo alvo do mark de status (SPEC-005 D2).

    Alvo padrão é a mestre (frontmatter `spec_id == spec_id` sem `task_id`);
    com `task_id`, a fatia específica (por prefixo ou por identidade de
    fatia renomeada). Exceção de compat single-file (spoke): candidato único
    com `spec_id == spec_id` é marcado (legado). Ambiguidade → None.

    Args:
        specs_dir: Diretório `specs/` do repo-alvo.
        spec_id: Identificador da especificação.
        task_id: Identificador da fatia (vazio = mestre).

    Returns:
        Path do alvo, ou None quando nada determinável.
    """
    owned = collect_owned_specs(specs_dir, spec_id)
    if not owned:
        if task_id:
            return find_renamed_slice(specs_dir, spec_id, task_id)
        return None
    if task_id:
        for candidate, frontmatter in owned:
            if str(frontmatter.get("task_id") or "") == task_id:
                return candidate
        return find_renamed_slice(specs_dir, spec_id, task_id)
    for candidate, frontmatter in owned:
        if not str(frontmatter.get("task_id") or ""):
            return candidate
    if len(owned) == 1:
        return owned[0][0]
    return None


def resolve_spoke_repo_dir(
    repo_slug: str,
    workspace_root: Path,
) -> Path | None:
    """Localiza o diretório local de um repositório spoke no workspace.

    Args:
        repo_slug: Identificador do repositório (ex: paralax-ia/paralax-evo-crm).
        workspace_root: Diretório raiz do workspace ou projeto.

    Returns:
        Instância de Path do diretório existente ou None.
    """
    short_name = repo_slug.split("/")[-1]
    if workspace_root.name == short_name and workspace_root.is_dir():
        return workspace_root

    candidate = workspace_root / short_name
    if candidate.is_dir():
        return candidate

    sibling = workspace_root.parent / short_name
    if sibling.is_dir():
        return sibling

    return None


def build_repo_tasks_for_slug(
    repo_slug: str,
    main_spec_path: Path,
    main_spec: SpecRun | None,
    declared_targets: list[dict[str, Any]],
) -> list[SubTask]:
    """Monta a lista de `SubTask` de um repositório spoke a partir da spec principal.

    Args:
        repo_slug: Slug do repositório alvo.
        main_spec_path: Caminho da spec principal.
        main_spec: Instância opcional de `SpecRun`.
        declared_targets: Lista de repositórios declarados no frontmatter.

    Returns:
        Lista de `SubTask` associadas ao `repo_slug`.
    """
    if main_spec:
        return [t for t in main_spec.tasks.values() if t.repo == repo_slug]

    repo_tasks: list[SubTask] = []
    for item in declared_targets:
        if isinstance(item, dict) and str(item.get("repo")) == repo_slug:
            repo_tasks.append(
                SubTask(
                    id=str(item.get("id") or f"task-{item.get('wave', 1)}"),
                    repo=repo_slug,
                    branch=f"feat/{main_spec_path.stem.lower()}-{repo_slug.split('/')[-1]}",
                    wave=int(item.get("wave", 1)),
                    expected_version=item.get("expected_version"),
                )
            )
    return repo_tasks


def fanout_all_repository_specs(
    main_spec_path: Path,
    workspace_root: Path,
    main_spec: SpecRun | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Path]:
    """Decompõe a especificação mestre em sub-specs cirúrgicas para todos os spokes.

    Args:
        main_spec_path: Caminho da especificação central no spec-hub.
        workspace_root: Diretório raiz onde os repositórios residem.
        main_spec: Instância opcional de SpecRun.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        Dicionário mapeando cada repo_slug para o Path da sub-spec salva.
    """
    raw_text = main_spec_path.read_text(encoding="utf-8")
    frontmatter, _ = extract_yaml_frontmatter(raw_text)

    declared_targets: list[dict[str, Any]] = frontmatter.get("target_repositories", [])
    all_repo_slugs = {
        str(item["repo"])
        for item in declared_targets
        if isinstance(item, dict) and "repo" in item
    }
    if main_spec:
        all_repo_slugs.update(task.repo for task in main_spec.tasks.values())

    spec_id = str(frontmatter.get("spec_id") or "SPEC")
    results: dict[str, Path] = {}

    for repo_slug in sorted(all_repo_slugs):
        repo_dir = resolve_spoke_repo_dir(repo_slug, workspace_root)
        if repo_dir is None:
            continue

        repo_tasks = build_repo_tasks_for_slug(
            repo_slug, main_spec_path, main_spec, declared_targets
        )
        sub_spec_text = generate_repo_spec(
            main_spec_path=main_spec_path,
            repo_name=repo_slug,
            tasks=repo_tasks,
            task=repo_tasks[0] if repo_tasks else None,
            main_spec=main_spec,
            all_target_repos=all_repo_slugs,
        )
        results[repo_slug] = save_repo_spec(
            repo_dir=repo_dir,
            spec_id=spec_id,
            content=sub_spec_text,
            task_id=repo_tasks[0].id if repo_tasks else "",
        )

    return results


@dataclass
class MergeOutcome:
    """Resultado do auto-merge seguro de branches de fatias no fechamento (SPEC-004 B2).

    Attributes:
        merged: Branches efetivamente mergeadas em main.
        skipped: Branches pendentes deixadas intactas (aborto global).
        warnings: Falhas de sincronização com origin (push/pull) reportadas
            sem abortar o merge local.
        aborted_reason: Motivo do aborto (vazio quando não há aborto).
    """

    merged: list[str] = dataclass_field(default_factory=list)
    skipped: list[str] = dataclass_field(default_factory=list)
    warnings: list[str] = dataclass_field(default_factory=list)
    aborted_reason: str = ""


def run_git(repo_dir: Path, args: list[str], check: bool = True) -> str:
    """Executa um comando git no diretório informado.

    Args:
        repo_dir: Diretório raiz do repositório.
        args: Argumentos do comando git (sem o binário).
        check: Se True, lança RuntimeError em código de saída ≠ 0.

    Returns:
        Saída padrão do comando, stripada.
    """
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falhou: {proc.stderr.strip()}")
    return proc.stdout.strip()


def hub_unmerged_branches(hub_dir: Path, spec_id: str) -> list[str]:
    """Lista branches do hub contendo o spec_id e ainda não mergeadas em main.

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.
        spec_id: Identificador da spec mestre (ex: SPEC-004).

    Returns:
        Lista de nomes de branches pendentes (merge-base com main ≠ ancestral).
    """
    listing = run_git(hub_dir, ["branch", "--format", "%(refname:short)"], check=False)
    needle = spec_id.lower()
    branches = [
        line.strip()
        for line in listing.splitlines()
        if line.strip() and needle in line.strip().lower()
    ]
    pending: list[str] = []
    for branch in branches:
        proc_ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", branch, "main"],
            cwd=hub_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_ancestor.returncode != 0:
            pending.append(branch)
    return pending


def validate_branch_diff(hub_dir: Path, branch: str) -> str:
    """Valida o diff de uma branch de fatia contra main (regras do B2).

    Somente arquivos `specs/SPEC-*.md` com `task_id` no frontmatter podem
    mudar; a mestre (frontmatter sem `task_id`) e arquivos fora de `specs/`
    abortam o auto-merge.

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.
        branch: Nome da branch de fatia.

    Returns:
        Vazio quando a branch é válida; caso contrário, motivo do aborto.
    """
    listing = run_git(hub_dir, ["diff", "--name-only", f"main..{branch}"])
    files = [line.strip() for line in listing.splitlines() if line.strip()]
    for file_path in files:
        if not file_path.startswith("specs/"):
            return (
                f"branch {branch} altera arquivo fora de specs/ ({file_path}) "
                "— auto-merge abortado, revisão manual necessária."
            )
        proc_show = subprocess.run(
            ["git", "show", f"{branch}:{file_path}"],
            cwd=hub_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc_show.returncode != 0:
            return (
                f"branch {branch} remove o arquivo ({file_path}) "
                "— auto-merge abortado, revisão manual necessária."
            )
        frontmatter, _ = extract_yaml_frontmatter(proc_show.stdout)
        if not str(frontmatter.get("task_id") or ""):
            return (
                f"branch {branch} altera a mestre ({file_path}) — arquivo sem "
                "task_id; auto-merge abortado, revisão manual necessária."
            )
    return ""


def merge_hub_branch(hub_dir: Path, branch: str, spec_id: str) -> str:
    """Mescla uma branch validada em main (ff-only, fallback merge commit).

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.
        branch: Nome da branch de fatia já validada.
        spec_id: Identificador da spec mestre (usado na mensagem de merge).

    Returns:
        Vazio quando o merge acontece; caso contrário, motivo do aborto.
    """
    proc_ff = subprocess.run(
        ["git", "merge", "--ff-only", branch],
        cwd=hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_ff.returncode == 0:
        return ""
    proc_noff = subprocess.run(
        ["git", "merge", "--no-ff", "-m", f"merge(spec): fatias de {spec_id}", branch],
        cwd=hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_noff.returncode != 0:
        return (
            f"merge de {branch} em main falhou (conflito?): "
            f"{proc_noff.stderr.strip()} — revisão manual necessária."
        )
    return ""


def sync_hub_with_origin(hub_dir: Path) -> str:
    """Sincroniza main local com origin antes dos merges (SPEC-004 review).

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.

    Returns:
        Vazio quando sincronizado (ou sem origin); motivo (warning) em
        falha de pull/divergência.
    """
    has_origin = (
        subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=hub_dir,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )
    if not has_origin:
        return ""
    proc_pull = subprocess.run(
        ["git", "pull", "--ff-only", "origin", "main"],
        cwd=hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_pull.returncode != 0:
        return (
            f"pull --ff-only de origin/main falhou "
            f"({proc_pull.stderr.strip() or proc_pull.stdout.strip()}) — "
            "merge local prossegue; sincronize com origin manualmente."
        )
    return ""


def push_merged_hub_branch(hub_dir: Path, branch: str) -> tuple[bool, str]:
    """Empurra main para origin e apaga a branch remota; falha é reportada.

    Nunca apaga a branch (nem local, nem remota) quando o push de main
    falha: as fatias precisam sobreviver em algum ref remoto (anti perda
    de dados no SSOT).

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.
        branch: Branch já mergeada localmente em main.

    Returns:
        Tupla `(push_ok, warning)` — warning descreve a falha de sync.
    """
    has_origin = (
        subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=hub_dir,
            capture_output=True,
            text=True,
            check=False,
        ).returncode
        == 0
    )
    if not has_origin:
        return True, ""
    proc_push = subprocess.run(
        ["git", "push", "origin", "main"],
        cwd=hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc_push.returncode != 0:
        error_details = proc_push.stderr.strip() or proc_push.stdout.strip()
        return (
            False,
            (
                f"push de main para origin falhou ({error_details}) — "
                f"branch {branch} preservada localmente e remotamente."
            ),
        )
    subprocess.run(
        ["git", "push", "origin", "--delete", branch],
        cwd=hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return True, ""


def merge_completed_hub_branches(spec_id: str, hub_dir: Path) -> MergeOutcome:
    """Executa o auto-merge seguro das branches de fatias do spec no hub (SPEC-004 B2).

    Lista branches contendo o spec_id ainda não mergeadas em main; valida o
    diff de todas ANTES de qualquer merge (aborto global sem tocar o estado
    local); mescla cada branch válida, empurra main quando houver origin e
    apaga as branches (local e remota). Sem branches pendentes → no-op.

    Args:
        spec_id: Identificador da spec mestre (ex: SPEC-004).
        hub_dir: Diretório raiz do repositório do spec-hub.

    Returns:
        MergeOutcome com o resultado da operação.
    """
    outcome = MergeOutcome()
    branches = hub_unmerged_branches(hub_dir, spec_id)
    if not branches:
        return outcome

    for branch in branches:
        reason = validate_branch_diff(hub_dir, branch)
        if reason:
            outcome.skipped = list(branches)
            outcome.aborted_reason = reason
            return outcome

    run_git(hub_dir, ["checkout", "main"])
    sync_warning = sync_hub_with_origin(hub_dir)
    if sync_warning:
        outcome.warnings.append(sync_warning)
    abort_reason = merge_and_publish_hub_branches(hub_dir, branches, spec_id, outcome)
    if abort_reason:
        outcome.aborted_reason = abort_reason
    return outcome


def merge_and_publish_hub_branches(
    hub_dir: Path, branches: list[str], spec_id: str, outcome: MergeOutcome
) -> str:
    """Mergeia as branches validadas em main, publica e apaga as branches.

    Rollback transacional por branch: em falha de merge, desfaz o merge
    pendente (`git merge --abort`), preserva as merges concluídas no
    `outcome` e reporta o resto como skipped.

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.
        branches: Branches validadas, na ordem de merge.
        spec_id: Identificador da spec mestre (mensagem de merge commit).
        outcome: Outcome acumulado do auto-merge.

    Returns:
        Vazio quando tudo mergeia; motivo do aborto em caso contrário.
    """
    merged: list[str] = []
    for branch in branches:
        reason = merge_hub_branch(hub_dir, branch, spec_id)
        if reason:
            abort_pending_git_merge(hub_dir)
            outcome.merged = merged
            outcome.skipped = [b for b in branches if b not in merged]
            return reason
        merged.append(branch)
        outcome.merged = list(merged)

    for branch in outcome.merged:
        push_ok, warning = push_merged_hub_branch(hub_dir, branch)
        if warning:
            outcome.warnings.append(warning)
        if push_ok:
            run_git(hub_dir, ["branch", "-D", branch], check=False)
    return ""


def abort_pending_git_merge(hub_dir: Path) -> None:
    """Desfaz um merge em conflito pendente no hub, restaurando main limpa.

    Rollback transacional do merge abortado (não é mascaramento): o estado
    local volta ao ponto pré-merge, sem MERGE_HEAD pendente, para que o
    próximo re-run funcione.

    Args:
        hub_dir: Diretório raiz do repositório do spec-hub.
    """
    subprocess.run(
        ["git", "merge", "--abort"],
        cwd=hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )


def find_matching_spoke_scope_h3(
    spoke_h3s: list[str],
    repo_name: str,
    short_repo: str,
) -> str | None:
    """Encontra a subseção H3 de escopo correspondente ao repositório spoke.

    Args:
        spoke_h3s: Lista de subseções H3 da sub-spec do spoke.
        repo_name: Slug completo do repositório.
        short_repo: Nome simples do repositório.

    Returns:
        Texto da subseção H3 correspondente ou None.
    """
    for s in spoke_h3s:
        s_title = s.splitlines()[0].lower()
        if short_repo.lower() in s_title or repo_name.lower() in s_title:
            return s
    return None


def reconcile_scope_h2_block(
    block_stripped: str,
    spoke_sections: dict[str, str],
    repo_name: str,
    short_repo: str,
    updated_sections: list[str],
) -> str:
    """Reconcilia a seção H2 de Escopo entre a sub-spec do spoke e a spec do hub.

    Args:
        block_stripped: Bloco H2 atual no spec-hub.
        spoke_sections: Mapa de seções H2 da sub-spec do spoke.
        repo_name: Slug completo do repositório spoke.
        short_repo: Nome simples do repositório spoke.
        updated_sections: Lista mutável de nomes de seções atualizadas.

    Returns:
        Bloco H2 reconciliado.
    """
    spoke_scope_match = next(
        (
            v
            for k, v in spoke_sections.items()
            if "escopo" in k.lower() or "repositórios" in k.lower()
        ),
        None,
    )
    if not spoke_scope_match:
        return block_stripped

    spoke_h3s = [
        s.strip()
        for s in re.split(r"\n(?=###\s+)", spoke_scope_match)
        if s.strip().startswith("### ")
    ]
    matching_spoke_h3 = find_matching_spoke_scope_h3(spoke_h3s, repo_name, short_repo)
    hub_h3s = re.split(r"\n(?=###\s+)", block_stripped)
    new_hub_h3s: list[str] = [hub_h3s[0].strip()]

    for h_sub in hub_h3s[1:]:
        h_sub_stripped = h_sub.strip()
        h_sub_title = h_sub_stripped.splitlines()[0].lower()
        if short_repo.lower() in h_sub_title or repo_name.lower() in h_sub_title:
            new_hub_h3s.append(matching_spoke_h3 or h_sub_stripped)
        else:
            new_hub_h3s.append(h_sub_stripped)

    new_scope_block = "\n\n".join(new_hub_h3s)
    if new_scope_block != block_stripped:
        updated_sections.append("Escopo e Repositórios Afetados")
    return new_scope_block


def find_matching_spoke_contract_h3(
    h_sub_title: str,
    spoke_h3s: list[str],
    short_repo: str,
) -> str | None:
    """Encontra a subseção H3 de contrato correspondente no spoke.

    Args:
        h_sub_title: Primeira linha em minúsculas da subseção do hub.
        spoke_h3s: Subseções H3 de contrato do spoke.
        short_repo: Nome simples do repositório spoke.

    Returns:
        Texto da subseção H3 correspondente no spoke ou None.
    """
    for s_sub in spoke_h3s:
        s_title = s_sub.splitlines()[0].lower()
        prefix_match = (
            s_title.split(":")[0].strip() == h_sub_title.split(":")[0].strip()
            if ":" in s_title and ":" in h_sub_title
            else False
        )
        term_match = short_repo.lower() in s_title and short_repo.lower() in h_sub_title
        if prefix_match or term_match:
            return s_sub
    return None


def reconcile_contracts_h2_block(
    block_stripped: str,
    spoke_sections: dict[str, str],
    short_repo: str,
    updated_sections: list[str],
) -> str:
    """Reconcilia a seção H2 de Contratos de Interface entre spoke e hub.

    Args:
        block_stripped: Bloco H2 atual no spec-hub.
        spoke_sections: Mapa de seções H2 da sub-spec do spoke.
        short_repo: Nome simples do repositório spoke.
        updated_sections: Lista mutável de nomes de seções atualizadas.

    Returns:
        Bloco H2 reconciliado.
    """
    spoke_contracts_match = next(
        (v for k, v in spoke_sections.items() if "contrato" in k.lower()),
        None,
    )
    if not spoke_contracts_match:
        return block_stripped

    spoke_h3s = [
        s.strip()
        for s in re.split(r"\n(?=###\s+)", spoke_contracts_match)
        if s.strip().startswith("### ")
    ]
    hub_h3s = re.split(r"\n(?=###\s+)", block_stripped)
    new_hub_h3s: list[str] = [hub_h3s[0].strip()]

    for h_sub in hub_h3s[1:]:
        h_sub_stripped = h_sub.strip()
        h_sub_title = h_sub_stripped.splitlines()[0].lower()
        matched_spoke_sub = find_matching_spoke_contract_h3(
            h_sub_title, spoke_h3s, short_repo
        )
        new_hub_h3s.append(matched_spoke_sub or h_sub_stripped)

    new_contract_block = "\n\n".join(new_hub_h3s)
    if new_contract_block != block_stripped:
        updated_sections.append("Contratos de Interface")
    return new_contract_block


def reconcile_gherkin_h2_block(
    block_stripped: str,
    spoke_sections: dict[str, str],
    updated_sections: list[str],
) -> str:
    """Reconcilia a seção H2 de Critérios de Aceitação (Gherkin) entre spoke e hub.

    Args:
        block_stripped: Bloco H2 atual no spec-hub.
        spoke_sections: Mapa de seções H2 da sub-spec do spoke.
        updated_sections: Lista mutável de nomes de seções atualizadas.

    Returns:
        Bloco H2 reconciliado.
    """
    spoke_gherkin_match = next(
        (
            v
            for k, v in spoke_sections.items()
            if "critérios" in k.lower() or "gherkin" in k.lower()
        ),
        None,
    )
    if not spoke_gherkin_match:
        return block_stripped

    spoke_by_title = {
        s.strip().splitlines()[0].lower(): s.strip()
        for s in re.split(r"\n(?=###\s+)", spoke_gherkin_match)
        if s.strip().startswith("### ")
    }
    hub_scenarios = re.split(r"\n(?=###\s+)", block_stripped)
    new_hub_scenarios: list[str] = [hub_scenarios[0].strip()]
    hub_scenario_titles = {hs.splitlines()[0].lower() for hs in hub_scenarios[1:]}

    for h_scn in hub_scenarios[1:]:
        h_scn_stripped = h_scn.strip()
        h_title = h_scn_stripped.splitlines()[0].lower()
        new_hub_scenarios.append(spoke_by_title.get(h_title, h_scn_stripped))

    for s_title, s_scn in spoke_by_title.items():
        if s_title not in hub_scenario_titles:
            new_hub_scenarios.append(s_scn)

    new_gherkin_block = "\n\n".join(new_hub_scenarios)
    if (
        new_gherkin_block != block_stripped
        and "Critérios de Aceitação (Gherkin)" not in updated_sections
    ):
        updated_sections.append("Critérios de Aceitação (Gherkin)")
    return new_gherkin_block


def reconcile_single_hub_h2_block(
    block_stripped: str,
    spoke_sections: dict[str, str],
    repo_name: str,
    short_repo: str,
    updated_sections: list[str],
) -> str:
    """Reconcilia um único bloco H2 da spec do hub com as seções do spoke.

    Args:
        block_stripped: Bloco H2 atual no spec-hub.
        spoke_sections: Mapa de seções H2 da sub-spec do spoke.
        repo_name: Slug completo do repositório spoke.
        short_repo: Nome simples do repositório spoke.
        updated_sections: Lista mutável de seções atualizadas.

    Returns:
        Bloco H2 reconciliado.
    """
    first_line_lower = block_stripped.splitlines()[0].strip().lower()
    if "escopo" in first_line_lower or "repositórios" in first_line_lower:
        return reconcile_scope_h2_block(
            block_stripped, spoke_sections, repo_name, short_repo, updated_sections
        )
    if "contrato" in first_line_lower:
        return reconcile_contracts_h2_block(
            block_stripped, spoke_sections, short_repo, updated_sections
        )
    if "critérios" in first_line_lower or "gherkin" in first_line_lower:
        return reconcile_gherkin_h2_block(
            block_stripped, spoke_sections, updated_sections
        )
    return block_stripped


def sync_spoke_spec_to_hub(
    spoke_spec_path: Path,
    hub_spec_path: Path,
) -> SpecSyncOutcome:
    """Sincroniza alterações da sub-spec de um spoke de volta para a spec do spec-hub.

    Args:
        spoke_spec_path: Caminho da sub-spec salva no repositório spoke.
        hub_spec_path: Caminho da spec principal no spec-hub.

    Returns:
        Instância de SpecSyncOutcome detalhando o resultado da reconciliação.
    """
    if not spoke_spec_path.is_file():
        return SpecSyncOutcome(
            success=False,
            spec_id="",
            repo="",
            updated_sections=[],
            message=f"Arquivo de sub-spec não encontrado: {spoke_spec_path}",
        )
    if not hub_spec_path.is_file():
        return SpecSyncOutcome(
            success=False,
            spec_id="",
            repo="",
            updated_sections=[],
            message=f"Arquivo da spec do hub não encontrado: {hub_spec_path}",
        )

    spoke_text = spoke_spec_path.read_text(encoding="utf-8")
    spoke_frontmatter, spoke_body = extract_yaml_frontmatter(spoke_text)

    hub_text = hub_spec_path.read_text(encoding="utf-8")
    hub_frontmatter, hub_body = extract_yaml_frontmatter(hub_text)

    spec_id = str(
        spoke_frontmatter.get("spec_id") or hub_frontmatter.get("spec_id") or ""
    )
    repo_name = str(spoke_frontmatter.get("repo") or "")
    short_repo = repo_name.split("/")[-1]
    updated_sections: list[str] = []

    spoke_sections = {
        sec.strip().splitlines()[0].strip(): sec.strip()
        for sec in re.split(r"\n(?=##\s+)", "\n" + spoke_body)
        if sec.strip().startswith("## ")
    }

    hub_h2_blocks = re.split(r"\n(?=##\s+)", "\n" + hub_body)
    new_hub_h2_blocks = [
        reconcile_single_hub_h2_block(
            block.strip(), spoke_sections, repo_name, short_repo, updated_sections
        )
        for block in hub_h2_blocks
        if block.strip()
    ]

    hub_frontmatter_yaml = yaml.safe_dump(
        hub_frontmatter, sort_keys=False, allow_unicode=True
    ).strip()
    new_hub_body = "\n\n".join(new_hub_h2_blocks).strip()
    new_hub_content = f"---\n{hub_frontmatter_yaml}\n---\n\n{new_hub_body}\n"

    hub_spec_path.write_text(new_hub_content, encoding="utf-8")

    return SpecSyncOutcome(
        success=True,
        spec_id=spec_id,
        repo=repo_name,
        updated_sections=updated_sections,
        message=f"Spec {spec_id} reconciliada com sucesso no spec-hub.",
    )
