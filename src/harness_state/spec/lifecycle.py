"""Ciclo de vida, autoria assistida por IA e aprovação de specs (SDD)."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness_state.capabilities import (
    BusinessCapability,
    load_business_capability,
    save_business_capability,
)
from harness_state.models import CapabilitySyncResult, SpecRun, SubTask, TaskState
from harness_state.sensors.prompt_sensor import discover_prompts_in_repository
from harness_state.workspace import find_manifest_path

SPEC_ID_REGEX = re.compile(r"SPEC-(\d+)", re.IGNORECASE)


def extract_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extrai o bloco de frontmatter YAML do topo de uma especificação Markdown.

    Args:
        text: Conteúdo completo do arquivo Markdown.

    Returns:
        Tupla contendo `(dicionario_frontmatter, corpo_markdown)`.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx == -1:
        return {}, text

    yaml_block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            return parsed, body
    except yaml.YAMLError:
        return {}, text
    return {}, body


def slugify(text: str) -> str:
    """Converte texto livre em slug seguro para nome de arquivo.

    Args:
        text: Texto a ser convertido.

    Returns:
        Slug em minúsculas separado por hífens.
    """
    clean_text = re.sub(r"[^\w\s-]", "", text.strip().lower())
    return re.sub(r"[-\s]+", "-", clean_text)


def get_next_spec_id(specs_dir: Path) -> str:
    """Identifica o próximo ID sequencial de especificação no diretório.

    Args:
        specs_dir: Diretório contendo as especificações existentes.

    Returns:
        String no formato 'SPEC-XXX' (ex: 'SPEC-004').
    """
    if not specs_dir.is_dir():
        return "SPEC-001"

    highest_num = 0
    for file_path in specs_dir.iterdir():
        if not file_path.is_file() or not file_path.name.endswith(".md"):
            continue
        match = SPEC_ID_REGEX.search(file_path.name)
        if match:
            num = int(match.group(1))
            highest_num = max(highest_num, num)

    next_num = highest_num + 1
    return f"SPEC-{next_num:03d}"


def get_default_template_path() -> Path:
    """Retorna o caminho padrão do template de especificação no catálogo do harness-state.

    Returns:
        Path para o SPEC-TEMPLATE.md.
    """
    return (
        Path(__file__).resolve().parent.parent
        / "catalog"
        / "pipeline"
        / "common"
        / "SPEC-TEMPLATE.md"
    )


def create_spec_draft(
    title: str,
    specs_dir: Path,
    template_path: Path | None = None,
) -> Path:
    """Cria um novo arquivo de especificação técnica com status DRAFT.

    Args:
        title: Título descritivo da especificação.
        specs_dir: Diretório de destino onde a spec será salva.
        template_path: Caminho opcional do template customizado.

    Returns:
        Path apontando para o arquivo de spec recém-criado.
    """
    specs_dir.mkdir(parents=True, exist_ok=True)
    next_id = get_next_spec_id(specs_dir)
    slug = slugify(title)
    target_file = specs_dir / f"{next_id}-{slug}.md"

    chosen_template = template_path or get_default_template_path()
    template_content = ""
    if chosen_template.is_file():
        template_content = chosen_template.read_text(encoding="utf-8")

    if not template_content:
        template_content = (
            "---\n"
            "spec_id: SPEC-001\n"
            'title: "Título da Funcionalidade"\n'
            "status: DRAFT\n"
            "target_repositories: []\n"
            "prompts:\n"
            "  - name: module-name/agent_instruction\n"
            "    target_repo: paralax-ia/module-name\n"
            "    file: module_name/prompts.py\n"
            "    symbol: INSTRUCTION\n"
            '    description: "Instrução de prompt do agente ou componente LLM"\n'
            "---\n\n"
            "# SPEC-001: Título da Funcionalidade\n\n"
            "## 1. Contexto e Motivação\n\n"
            "## 2. Escopo e Repositórios Afetados\n\n"
            "## 3. Contratos de Interface\n\n"
            "### 3.1. Viabilidade Técnica e Compatibilidade de SDKs\n"
            "- Dependências externas e versões mínimas exigidas.\n"
            "- Protocolo e restrições conhecidas.\n"
            "- Plano de Fallback Arquitetural.\n\n"
            "## 4. Critérios de Aceitação (Gherkin)\n"
        )

    modified_content = re.sub(
        r"spec_id:\s*SPEC-\d+", f"spec_id: {next_id}", template_content
    )
    modified_content = re.sub(
        r'title:\s*["\'].*?["\']', f'title: "{title}"', modified_content
    )
    modified_content = re.sub(
        r"^#\s*SPEC-\d+:.*$",
        f"# {next_id}: {title}",
        modified_content,
        flags=re.MULTILINE,
    )
    if "status:" in modified_content:
        modified_content = re.sub(
            r"status:\s*[A-Z_]+", "status: DRAFT", modified_content
        )
    else:
        modified_content = modified_content.replace("---", "---\nstatus: DRAFT", 1)

    specs_parent = specs_dir.resolve().parent.name
    if specs_parent and not specs_parent.endswith(("-hub", "-spec-hub", "specs")):
        modified_content = modified_content.replace("module-name", specs_parent)

    target_file.write_text(modified_content, encoding="utf-8")
    return target_file


def locate_repo_dir(
    repo_name: str,
    workspace_root: Path,
    manifest_path: Path | None = None,
) -> Path | None:
    """Localiza o diretório físico de um repositório no workspace.

    Args:
        repo_name: Identificador do repositório (ex: 'customer-support-vehicles').
        workspace_root: Diretório raiz do workspace.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        Path para o repositório ou None se não encontrado.
    """
    short_name = repo_name.split("/")[-1]
    candidates = [
        workspace_root / short_name,
        workspace_root / repo_name,
        workspace_root.parent / short_name,
    ]
    if manifest_path is not None and manifest_path.parent.is_dir():
        candidates.append(manifest_path.parent / short_name)
        candidates.append(manifest_path.parent.parent / short_name)

    for cand in candidates:
        if cand.is_dir():
            return cand
    return None


def find_relative_prompt_file(repo_dir: Path) -> str:
    """Localiza o arquivo principal de prompt relativo à raiz do repositório.

    Args:
        repo_dir: Diretório raiz do repositório.

    Returns:
        Caminho relativo do arquivo de prompt encontrado ou 'prompts.py'.
    """
    for py_file in repo_dir.rglob("prompts.py"):
        rel = py_file.relative_to(repo_dir)
        parts = rel.parts
        if any(p in {".git", ".venv", "__pycache__", "tests"} for p in parts):
            continue
        return str(rel)
    return "prompts.py"


def match_repo_prompt_file(
    target_repos: list[Any],
    workspace_root: Path,
    manifest_path: Path | None,
) -> tuple[str, str]:
    """Localiza o primeiro repo alvo e o caminho relativo do arquivo de prompts.

    Args:
        target_repos: Lista de repositórios alvos do frontmatter.
        workspace_root: Diretório raiz do workspace.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        Tupla com (nome_do_repositorio, caminho_relativo_do_arquivo).
    """
    for item in target_repos:
        repo_name = item.get("repo", "") if isinstance(item, dict) else str(item)
        repo_dir = locate_repo_dir(repo_name, workspace_root, manifest_path)
        if repo_dir:
            return repo_name, find_relative_prompt_file(repo_dir)
    return "", "prompts.py"


def match_canonical_prompt(
    declared_name: str,
    discovered: list[str],
    clean_short: str,
) -> str | None:
    """Encontra o nome canônico descoberto correspondente ao declarado.

    Args:
        declared_name: Nome do prompt declarado na especificação.
        discovered: Lista de prompts descobertos no repositório.
        clean_short: Nome curto do repositório normalizado.

    Returns:
        Nome canônico encontrado ou None.
    """
    if not discovered:
        return None
    if declared_name in discovered:
        return declared_name

    decl_prefix = declared_name.split("/")[0]
    for disc in discovered:
        disc_prefix = disc.split("/")[0]
        has_match = (
            disc_prefix == decl_prefix
            or disc_prefix in clean_short
            or clean_short in disc_prefix
            or len(discovered) == 1
        )
        if has_match:
            return disc
    return None


def resolve_canonical_prompt_for_item(
    item: dict[str, Any],
    workspace_root: Path,
    manifest_path: Path | None,
) -> tuple[dict[str, Any], bool]:
    """Ajusta o nome do prompt declarado se houver divergência com o descoberto.

    Args:
        item: Dicionário descritor do prompt.
        workspace_root: Raiz do workspace.
        manifest_path: Caminho do manifest.yaml opcional.

    Returns:
        Tupla com o item e flag indicando se houve alteração.
    """
    declared_name = str(item.get("name", ""))
    matched_repo = str(item.get("target_repo", ""))
    if not declared_name or not matched_repo:
        return item, False

    target_dir = locate_repo_dir(matched_repo, workspace_root, manifest_path)
    if not target_dir or not target_dir.is_dir():
        return item, False

    discovered = discover_prompts_in_repository(target_dir)
    clean_short = matched_repo.split("/")[-1].replace("-", "_")
    canonical = match_canonical_prompt(declared_name, discovered, clean_short)
    if canonical and canonical != declared_name:
        item["name"] = canonical
        return item, True

    return item, False


def enrich_declared_prompts(
    raw_prompts: list[Any],
    target_repos: list[Any],
    workspace_root: Path,
    manifest_path: Path | None,
) -> tuple[list[dict[str, Any]], bool]:
    """Enriquece prompts do frontmatter que possam estar apenas como strings.

    Args:
        raw_prompts: Lista de prompts brutos extraídos do frontmatter.
        target_repos: Repositórios alvos declarados na especificação.
        workspace_root: Raiz do workspace.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        Tupla com a lista de prompts enriquecidos e a flag de needs_update.
    """
    enriched: list[dict[str, Any]] = []
    needs_update = False
    for item in raw_prompts:
        if isinstance(item, dict) and item.get("name"):
            item_resolved, updated = resolve_canonical_prompt_for_item(
                item, workspace_root, manifest_path
            )
            if updated:
                needs_update = True
            enriched.append(item_resolved)
            continue
        if not isinstance(item, str) or not item.strip():
            continue
        prompt_name = item.strip()
        matched_repo, prompt_file = match_repo_prompt_file(
            target_repos, workspace_root, manifest_path
        )
        enriched.append(
            {
                "name": prompt_name,
                "target_repo": matched_repo,
                "file": prompt_file,
                "symbol": "INSTRUCTION",
                "description": f"Instrução governada de prompt '{prompt_name}'",
            }
        )
        needs_update = True
    return enriched, needs_update


def should_discover_repo_prompts(repo_item: Any, body_text: str) -> bool:
    """Verifica se um repositório alvo deve passar por autodescoberta de prompts.

    Args:
        repo_item: Dicionário ou string do repositório no frontmatter.
        body_text: Texto do corpo da especificação técnica.

    Returns:
        True se o papel for 'ai-agent' ou o corpo da spec mencionar prompts/instrução.
    """
    role = repo_item.get("role", "") if isinstance(repo_item, dict) else ""
    if role == "ai-agent":
        return True
    return bool(
        re.search(r"\bprompts?\.py\b", body_text, re.IGNORECASE)
        or re.search(r"\binstruction\b", body_text, re.IGNORECASE)
        or re.search(r"\blangfuse\b", body_text, re.IGNORECASE)
    )


def discover_prompts_for_single_repo(
    repo_name: str,
    workspace_root: Path,
    manifest_path: Path | None,
) -> list[dict[str, Any]]:
    """Descobre e estrutura metadados de prompts para um único repositório.

    Args:
        repo_name: Nome do repositório alvo.
        workspace_root: Raiz do workspace.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        Lista de dicionários de prompts descobertos.
    """
    repo_dir = locate_repo_dir(repo_name, workspace_root, manifest_path)
    if not repo_dir or not repo_dir.is_dir():
        return []
    names = discover_prompts_in_repository(repo_dir)
    rel_file = find_relative_prompt_file(repo_dir)
    prompts: list[dict[str, Any]] = []
    for name in names:
        prompts.append(
            {
                "name": name,
                "target_repo": repo_name,
                "file": rel_file,
                "symbol": "INSTRUCTION",
                "description": f"Instruções governadas de prompt para {repo_name}",
            }
        )
    return prompts


def discover_target_repo_prompts(
    target_repos: list[Any],
    body_text: str,
    workspace_root: Path,
    manifest_path: Path | None,
) -> list[dict[str, Any]]:
    """Descobre prompts em repositórios alvos caso a spec não os declare explicitamente.

    Args:
        target_repos: Lista de repositórios alvos da especificação.
        body_text: Corpo textual da especificação técnica.
        workspace_root: Raiz do workspace.
        manifest_path: Caminho opcional do manifest.yaml.

    Returns:
        Lista de dicionários de prompts descobertos.
    """
    discovered: list[dict[str, Any]] = []
    for item in target_repos:
        if not should_discover_repo_prompts(item, body_text):
            continue
        repo_name = item.get("repo", "") if isinstance(item, dict) else str(item)
        repo_prompts = discover_prompts_for_single_repo(
            repo_name=repo_name,
            workspace_root=workspace_root,
            manifest_path=manifest_path,
        )
        discovered.extend(repo_prompts)
    return discovered


def ensure_spec_has_prompts(
    spec_path: Path,
    workspace_root: Path = Path("."),
    manifest_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Garante que a especificação técnica contenha declaração formal de prompts.

    Args:
        spec_path: Caminho da especificação Markdown no disco.
        workspace_root: Raiz do workspace para descoberta de repositórios.
        manifest_path: Caminho opcional para o manifest.yaml.

    Returns:
        Lista de dicionários contendo os metadados dos prompts governados declarados.
    """
    if not spec_path.is_file():
        return []

    raw_text = spec_path.read_text(encoding="utf-8")
    frontmatter, body = extract_yaml_frontmatter(raw_text)
    raw_prompts = frontmatter.get("prompts", [])
    if isinstance(raw_prompts, str):
        raw_prompts = [raw_prompts]

    target_repos = frontmatter.get("target_repositories", [])
    if isinstance(target_repos, dict):
        target_repos = [target_repos]

    if raw_prompts:
        enriched_prompts, needs_update = enrich_declared_prompts(
            raw_prompts=raw_prompts,
            target_repos=target_repos,
            workspace_root=workspace_root,
            manifest_path=manifest_path,
        )
    else:
        enriched_prompts = discover_target_repo_prompts(
            target_repos=target_repos,
            body_text=body,
            workspace_root=workspace_root,
            manifest_path=manifest_path,
        )
        needs_update = bool(enriched_prompts)

    if needs_update and enriched_prompts:
        frontmatter["prompts"] = enriched_prompts
        new_yaml = yaml.safe_dump(
            frontmatter, sort_keys=False, allow_unicode=True
        ).strip()
        updated_text = f"---\n{new_yaml}\n---\n{body}"
        spec_path.write_text(updated_text, encoding="utf-8")

    return enriched_prompts


UBIQUITOUS_TERM_PATTERN = re.compile(
    r"(?:[-*]\s+|\b)\*\*([A-Za-z0-9_\s-]+):\*\*\s+([^\n]+)"
)


def find_capability_file(capability_id: str, search_roots: list[Path]) -> Path | None:
    """Procura o arquivo capability.yaml correspondente à capability_id.

    Args:
        capability_id: Identificador da capability (ex: agent-workflow-platform).
        search_roots: Lista de diretórios raiz para busca.

    Returns:
        Path para capability.yaml se encontrado ou None.
    """
    for root in search_roots:
        cand = root / "capabilities" / capability_id / "capability.yaml"
        if cand.is_file():
            return cand
        cand_hub = root / "harness-spec-hub" / "capabilities" / capability_id / "capability.yaml"
        if cand_hub.is_file():
            return cand_hub
    return None


def extract_ubiquitous_terms_from_markdown(text: str) -> dict[str, str]:
    """Extrai termos da linguagem ubíqua e suas definições a partir do markdown da spec.

    Args:
        text: Corpo do documento da especificação técnica.

    Returns:
        Dicionário mapeando termo para definição.
    """
    terms: dict[str, str] = {}
    for match in UBIQUITOUS_TERM_PATTERN.finditer(text):
        term = match.group(1).strip()
        defn = match.group(2).strip()
        if term and defn and len(term) < 50:
            terms[term] = defn
    return terms


def resolve_or_create_capability(
    capability_id: str,
    scope: str,
    ws_root: Path,
    search_dirs: list[Path],
) -> tuple[BusinessCapability, Path]:
    """Resolve o arquivo capability.yaml existente ou cria a instância base.

    Args:
        capability_id: Identificador da capability.
        scope: Escopo declarado na spec (ex: platform).
        ws_root: Raiz do workspace.
        search_dirs: Diretórios candidatos de busca.

    Returns:
        Tupla (instância BusinessCapability, Path do arquivo).
    """
    capability_file = find_capability_file(capability_id, search_dirs)
    if capability_file is not None:
        return load_business_capability(capability_file), capability_file

    target_dir = ws_root / "capabilities" / capability_id
    target_dir.mkdir(parents=True, exist_ok=True)
    new_file = target_dir / "capability.yaml"
    cap = BusinessCapability(
        version="1.0",
        capability_id=capability_id,
        name=capability_id.replace("-", " ").title(),
        scope=scope,
    )
    return cap, new_file


def update_capability_specs(
    capability: BusinessCapability,
    spec_id: str,
    title: str,
) -> list[str]:
    """Atualiza a lista de specs na capability garantindo status APPROVED.

    Args:
        capability: Instância da capability a atualizar.
        spec_id: Identificador da spec.
        title: Título da spec.

    Returns:
        Lista com spec_id adicionado ou vazio se já existia.
    """
    existing_entries = [
        s for s in capability.specs if isinstance(s, dict) and s.get("spec_id") == spec_id
    ]
    if not existing_entries:
        capability.specs.append({"spec_id": spec_id, "title": title, "status": "APPROVED"})
        return [spec_id]

    for entry in existing_entries:
        entry["status"] = "APPROVED"
        entry["title"] = title
    return []


def update_capability_terms(
    capability: BusinessCapability,
    terms: dict[str, str],
) -> list[str]:
    """Adiciona novos termos extraídos à linguagem ubíqua da capability.

    Args:
        capability: Instância da capability a atualizar.
        terms: Dicionário de termos e definições.

    Returns:
        Lista de novos termos adicionados.
    """
    added_terms: list[str] = []
    for term, defn in terms.items():
        if term not in capability.ubiquitous_language:
            capability.ubiquitous_language[term] = defn
            added_terms.append(term)
    return added_terms


def sync_capability_map_for_spec(
    spec_file: Path,
    author_agent: str = "antigravity",
    workspace_root: Path | None = None,
) -> CapabilitySyncResult:
    """Sincroniza o mapa de capacidades (DDD) com base na especificação técnica aprovada.

    Args:
        spec_file: Arquivo Markdown da especificação técnica.
        author_agent: Identificador do agente autor da spec.
        workspace_root: Raiz opcional do workspace ou spec-hub.

    Returns:
        CapabilitySyncResult contendo resumo das adições e atualizações realizadas.
    """
    if not spec_file.is_file():
        return CapabilitySyncResult(capability_id="", updated=False)

    content = spec_file.read_text(encoding="utf-8")
    frontmatter, body = extract_yaml_frontmatter(content)
    if not frontmatter or not isinstance(frontmatter, dict):
        return CapabilitySyncResult(capability_id="", updated=False)

    capability_id = str(frontmatter.get("capability") or "").strip()
    if not capability_id:
        return CapabilitySyncResult(capability_id="", updated=False)

    spec_id = str(frontmatter.get("spec_id") or spec_file.stem)
    title = str(frontmatter.get("title") or spec_file.stem)
    author = author_agent or str(frontmatter.get("author_agent") or "antigravity")
    scope = str(frontmatter.get("scope") or "platform")

    ws_root = workspace_root or spec_file.parent.parent
    search_dirs = [ws_root, spec_file.parent.parent, Path(".")]

    capability, capability_file = resolve_or_create_capability(
        capability_id=capability_id,
        scope=scope,
        ws_root=ws_root,
        search_dirs=search_dirs,
    )

    added_specs = update_capability_specs(capability, spec_id=spec_id, title=title)
    terms = extract_ubiquitous_terms_from_markdown(body)
    added_terms = update_capability_terms(capability, terms=terms)

    save_business_capability(capability, capability_file)

    return CapabilitySyncResult(
        capability_id=capability_id,
        updated=True,
        added_terms=added_terms,
        added_specs=added_specs or [spec_id],
        sync_agent=author,
        diff_summary=f"Sincronizada spec {spec_id} e {len(added_terms)} termos na capability {capability_id}",
    )


def approve_spec(
    spec_file: Path,
    workspace_root: Path | None = None,
    manifest_path: Path | None = None,
    author_agent: str | None = None,
    sync_capabilities: bool = True,
) -> bool:
    """Aprova spec (Gate 2: APPROVED), enriquecendo prompts governados e sincronizando capacidades.

    Args:
        spec_file: Caminho para o arquivo da especificação.
        workspace_root: Raiz opcional do workspace para autodescoberta de prompts.
        manifest_path: Caminho opcional do manifest.yaml.
        author_agent: Identificador opcional do agente autor da spec.
        sync_capabilities: Se True, executa a sincronização do mapa de capacidades.

    Returns:
        True se a transição foi realizada com sucesso, False caso o arquivo inexista.
    """
    if not spec_file.is_file():
        return False

    ws_root = workspace_root or spec_file.parent.parent
    ensure_spec_has_prompts(
        spec_file, workspace_root=ws_root, manifest_path=manifest_path
    )

    content = spec_file.read_text(encoding="utf-8")
    if not re.search(r"status:\s*", content, re.IGNORECASE):
        updated = re.sub(r"^---\n", "---\nstatus: APPROVED\n", content, count=1)
    else:
        updated = re.sub(
            r"status:\s*[A-Za-z_-]+",
            "status: APPROVED",
            content,
            flags=re.IGNORECASE,
        )

    spec_file.write_text(updated, encoding="utf-8")

    if sync_capabilities:
        sync_capability_map_for_spec(
            spec_file=spec_file,
            author_agent=author_agent or "antigravity",
            workspace_root=ws_root,
        )

    return True


def resolve_specs_directory(
    specs_dir: Path | None = None,
    manifest_path: Path | None = None,
    workspace_root: Path = Path("."),
) -> Path:
    """Resolve o diretório canônico de especificações no ecossistema.

    Args:
        specs_dir: Diretório de specs explicitamente fornecido.
        manifest_path: Caminho opcional do manifest.yaml.
        workspace_root: Raiz do workspace.

    Returns:
        Path para o diretório de especificações resolvido.
    """
    if specs_dir is not None:
        return specs_dir

    resolved_manifest = manifest_path or find_manifest_path(
        workspace_root=workspace_root
    )
    if resolved_manifest is not None:
        hub_specs = resolved_manifest.parent / "specs"
        if hub_specs.is_dir() or (resolved_manifest.parent / ".git").is_dir():
            return hub_specs

    resolved_root = workspace_root.resolve()
    for child in sorted(resolved_root.iterdir()) if resolved_root.is_dir() else []:
        if child.is_dir() and child.name.endswith("-spec-hub"):
            cand = child / "specs"
            if cand.is_dir():
                return cand

    return workspace_root / "specs"


def resolve_spec_file_path(
    spec_target: Path | str,
    specs_dir: Path | None = None,
    manifest_path: Path | None = None,
    workspace_root: Path = Path("."),
) -> Path | None:
    """Localiza o arquivo de especificação por caminho exato, nome ou ID.

    Args:
        spec_target: Caminho do arquivo, nome (ex: SPEC-001.md) ou ID.
        specs_dir: Diretório de especificações opcional.
        manifest_path: Caminho opcional para o manifest.yaml.
        workspace_root: Raiz do workspace.

    Returns:
        Path para o arquivo se localizado, ou None se inexistente.
    """
    path_obj = Path(spec_target)
    if path_obj.is_file():
        return path_obj

    resolved_dir = resolve_specs_directory(
        specs_dir=specs_dir,
        manifest_path=manifest_path,
        workspace_root=workspace_root,
    )
    if not resolved_dir.is_dir():
        return None

    direct_in_dir = resolved_dir / path_obj.name
    if direct_in_dir.is_file():
        return direct_in_dir

    target_str = str(spec_target).strip()
    target_id_match = SPEC_ID_REGEX.search(target_str)
    search_prefix = target_id_match.group(0).upper() if target_id_match else target_str

    for candidate in resolved_dir.iterdir():
        if not candidate.is_file() or not candidate.name.endswith(".md"):
            continue
        if candidate.name.startswith(search_prefix) or search_prefix in candidate.name:
            return candidate

    return None


@dataclass(slots=True)
class SpecRefineOutcome:
    """Resultado da operação de refinamento in-flight de uma especificação.

    Attributes:
        spec_id: Identificador da especificação refinada.
        spec_path: Caminho para o arquivo da especificação no disco.
        frozen_tasks: Lista de identificadores de subtarefas congeladas.
        pending_tasks: Lista de identificadores de subtarefas pendentes ou adicionadas.
        success: Indica se o refinamento foi concluído com sucesso.
        feedback: Mensagem descritiva ou saída produzida pelo agente.
    """

    spec_id: str
    spec_path: Path
    frozen_tasks: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    success: bool = True
    feedback: str = ""


def get_frozen_and_pending_tasks(
    tasks: dict[str, SubTask] | SpecRun,
) -> tuple[list[SubTask], list[SubTask]]:
    """Segrega subtarefas entre congeladas (já concluídas) e pendentes (refináveis).

    Tarefas com status READY ou APPROVED são consideradas congeladas e imutáveis,
    pois já tiveram seu código validado por sensores e/ou Pull Requests abertos.
    Tarefas com status PENDING, IN_PROGRESS ou FAILED permanecem abertas.

    Args:
        tasks: Dicionário contendo as subtarefas ou o próprio objeto SpecRun.

    Returns:
        Tupla contendo `(lista_tarefas_congeladas, lista_tarefas_pendentes)`.
    """
    task_dict = tasks.tasks if isinstance(tasks, SpecRun) else tasks
    frozen = [
        t
        for t in task_dict.values()
        if t.status in (TaskState.READY, TaskState.APPROVED)
    ]
    pending = [
        t
        for t in task_dict.values()
        if t.status not in (TaskState.READY, TaskState.APPROVED)
    ]
    return frozen, pending


def build_spec_refine_prompt(
    spec_path: Path,
    spec_content: str,
    frozen_tasks: list[SubTask],
    pending_tasks: list[SubTask],
    user_instruction: str,
) -> str:
    """Constrói o prompt estruturado para o agente de IA refinar a spec in-flight.

    Args:
        spec_path: Caminho do arquivo da especificação no sistema de arquivos.
        spec_content: Conteúdo integral atual do arquivo Markdown.
        frozen_tasks: Lista de subtarefas já concluídas/congeladas.
        pending_tasks: Lista de subtarefas pendentes ou futuras.
        user_instruction: Instrução textual do usuário sobre o que mudar.

    Returns:
        Prompt detalhado em Markdown orientando o agente a reescrever a spec.
    """
    frozen_lines = []
    for t in frozen_tasks:
        pr_info = f" | PR #{t.pr_number}" if t.pr_number else ""
        ver_info = f" | Versão: {t.expected_version}" if t.expected_version else ""
        entry = (
            f"  - [{t.id}] Onda {t.wave} em `{t.repo}` "
            f"(Status: {t.status}{pr_info}{ver_info})"
        )
        frozen_lines.append(entry)
    frozen_summary = (
        "\n".join(frozen_lines) if frozen_lines else "  (No completed tasks so far)"
    )

    pending_lines = []
    for t in pending_tasks:
        pending_lines.append(
            f"  - [{t.id}] Wave {t.wave} in `{t.repo}` (Status: {t.status})"
        )
    pending_summary = (
        "\n".join(pending_lines) if pending_lines else "  (No pending tasks registered)"
    )

    frozen_ids = ", ".join([t.id for t in frozen_tasks]) or "none"

    prompt_parts = [
        "# SDD Technical Specification Refinement Request (In-Flight)",
        "",
        "You are the Software Architect responsible for the ecosystem.",
        (
            "The human operator requested a refinement/change in the technical "
            "specification below during the Approval Gateway."
        ),
        "",
        "## Target Specification File:",
        f"`{spec_path}`",
        "",
        "## Current Specification Content:",
        "```markdown",
        spec_content.strip(),
        "```",
        "",
        "## Current Subtasks State in State Tracker:",
        "### COMPLETED AND FROZEN SUBTASKS (DO NOT MODIFY ALREADY DELIVERED SCOPE):",
        frozen_summary,
        "",
        "### PENDING SUBTASKS / UPCOMING WAVES (OPEN FOR REFINEMENT):",
        pending_summary,
        "",
        "## Operator Requested Change Instruction:",
        user_instruction.strip(),
        "",
        "## Mandatory Refinement Rules:",
        (
            "1. PRESERVE COMPLETED WORK: It is strictly forbidden to regress, "
            "remove, or modify the scope, public interface contracts, or "
            f"acceptance criteria of already completed tasks ({frozen_ids})."
        ),
        (
            f"2. UPDATE THE FILE DIRECTLY ON DISK: Rewrite/edit the file "
            f"`{spec_path.name}` incorporating the requested changes:"
        ),
        (
            "   - Add or update Interface Contracts and Acceptance Criteria "
            "(Gherkin) for pending tasks or new waves."
        ),
        ("   - Update the Context and Motivation section reflecting recent decisions."),
        (
            "   - Adjust YAML Frontmatter (`target_repositories`) if new "
            "subtasks or modules are added for upcoming waves."
        ),
        (
            "   - Ensure the specification strictly complies with canonical "
            "ecosystem SDD format."
        ),
        (
            "3. MANDATORY PROMPT GOVERNANCE (SPEC-PROMPT-01): If any target "
            "repository is an AI agent (`role: ai-agent`) or if the spec touches "
            "instructions, system prompts, or files like `prompts.py`, you MUST "
            "declare all affected prompts in YAML Frontmatter under `prompts:` "
            "with `name`, `target_repo`, `file`, `symbol`, and `description`. "
            "Document the exact prompt text in English in Section 3.5."
        ),
        (
            "4. MANDATORY TECHNICAL FEASIBILITY AND SDK COMPATIBILITY: "
            "It is strictly prohibited to design architecture or public interface "
            "contracts assuming unsupported features in third-party or emerging "
            "SDKs (such as Google ADK, Gemini Live API, or WebSocket streaming) "
            "without verifying feasibility. For any real-time, audio, streaming, or "
            "emerging SDK integration: (a) Explicitly document required SDK "
            "dependencies, versions, and contract signatures in Section 3.1; "
            "(b) Specify protocol constraints (e.g., tool calling limitations in "
            "streaming mode, socket lifecycle, audio codecs); (c) If capability is "
            "not proven in codebase, specify a preliminary Wave 0 Spike task "
            "(`role: spike`) before feature implementation; (d) Define an "
            "architectural fallback in Section 3.1."
        ),
    ]
    return "\n".join(prompt_parts)


def merge_refined_spec(
    existing_spec: SpecRun,
    new_parsed: SpecRun,
) -> SpecRun:
    """Mescla a spec reescrita com o estado existente, protegendo tarefas prontas.

    Args:
        existing_spec: Estado atual persistido no StateStore (Redis).
        new_parsed: Novo estado parseado a partir do Markdown refinado.

    Returns:
        Instância de SpecRun mesclada e consistente.
    """
    merged_tasks: dict[str, SubTask] = {}

    for task_id, existing_task in existing_spec.tasks.items():
        if existing_task.status in (TaskState.READY, TaskState.APPROVED):
            merged_tasks[task_id] = existing_task

    for task_id, new_task in new_parsed.tasks.items():
        if task_id in merged_tasks:
            continue
        if task_id in existing_spec.tasks:
            old_task = existing_spec.tasks[task_id]
            merged_task = new_task.model_copy()
            merged_task.status = old_task.status
            merged_task.pr_number = old_task.pr_number
            merged_task.issue_number = old_task.issue_number
            merged_task.issue_url = old_task.issue_url
            merged_task.branch = old_task.branch or new_task.branch
            merged_tasks[task_id] = merged_task
        else:
            merged_tasks[task_id] = new_task

    merged_spec = new_parsed.model_copy()
    merged_spec.tasks = merged_tasks
    merged_spec.declared_status = existing_spec.declared_status or "APPROVED"
    merged_spec.status = (
        TaskState.APPROVED
        if existing_spec.status == TaskState.APPROVED
        else existing_spec.status
    )
    return merged_spec


def validate_spec_feasibility(content: str) -> tuple[bool, list[str]]:
    """Valida se a especificação atende às regras de viabilidade técnica.

    Args:
        content: Conteúdo integral em Markdown da especificação.

    Returns:
        Tupla com booleano (True se válida) e lista de avisos ou inconformidades.
    """
    issues: list[str] = []
    content_lower = content.lower()

    realtime_keywords = [
        "live api",
        "gemini live",
        "adk live",
        "websocket",
        "web socket",
        "audio streaming",
        "bidirecional",
    ]
    has_realtime = any(kw in content_lower for kw in realtime_keywords)

    if has_realtime:
        has_feasibility_section = (
            "viabilidade técnica" in content_lower
            or "compatibilidade de sdk" in content_lower
            or "technical feasibility" in content_lower
            or "3.1" in content
        )
        if not has_feasibility_section:
            issues.append(
                "A especificação menciona APIs de tempo real/streaming "
                "(ex: Live API/WebSocket) mas não possui a seção "
                "'3.1. Viabilidade Técnica e Compatibilidade de SDKs'."
            )

        has_fallback_or_spike = (
            "fallback" in content_lower
            or "spike" in content_lower
            or "onda 0" in content_lower
            or "wave: 0" in content_lower
            or "role: spike" in content_lower
        )
        if not has_fallback_or_spike:
            issues.append(
                "APIs de tempo real/streaming requerem um plano de contingência "
                "(plano de fallback ou subtarefa de Spike na Onda 0)."
            )

    return len(issues) == 0, issues
