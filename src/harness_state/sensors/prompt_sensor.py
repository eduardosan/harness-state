"""Sensor determinístico de governança de prompts (SPEC-PROMPT-01).

Bloqueia terminantemente:
* ``PRM001``: Alteração de arquivos de prompt sem declaração na spec.
* ``PRM002``: Prompts declarados ausentes no Langfuse como draft.

A saída segue o formato padronizado (arquivo:linha:coluna: CODIGO mensagem).
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from harness_state.prompt_manager import (
    LangfusePromptManager,
    PromptManagementError,
)

PROMPT_FILE_PATTERNS = [
    re.compile(
        r"(?:^|/)(?:[a-zA-Z0-9_-]*prompt[a-zA-Z0-9_-]*)\.(?:py|txt|json|yaml|yml)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|/)prompts/.*\.(?:py|txt|md|json|yaml|yml)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|/)templates/.*prompt.*\.(?:py|txt|md|json|yaml|yml)$",
        re.IGNORECASE,
    ),
]

IGNORED_PROMPT_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "tests",
    ".harness",
    "specs",
    ".github",
}

PROMPT_RULES = {
    "PRM001": "Prompt file changed without declaration in spec",
    "PRM002": "Prompt declared in spec but not found in Langfuse as draft",
}


@dataclass(slots=True)
class PromptViolation:
    """Representa uma violação de governança de prompts detectada pelo sensor.

    Attributes:
        file_path: Caminho do arquivo analisado.
        line_number: Linha onde a violação foi detectada.
        col_number: Coluna aproximada da violação.
        code: Código identificador da regra (PRM001, PRM002).
        message: Mensagem explicativa da violação.
    """

    file_path: str
    line_number: int
    col_number: int
    code: str
    message: str

    def format_output(self) -> str:
        """Formata a violação no padrão consumível por format_feedback.sh.

        Returns:
            String no formato 'arquivo:linha:coluna: CODIGO mensagem'.
        """
        return (
            f"{self.file_path}:{self.line_number}:{self.col_number}: "
            f"{self.code} {self.message}"
        )


class PromptGovernanceSensor:
    """Validador e sensor de integridade para o ciclo de vida de prompts."""

    def __init__(
        self,
        project_root: Path,
        prompt_manager: Any | None = None,
    ) -> None:
        """Inicializa o sensor com o diretório raiz do projeto.

        Args:
            project_root: Raiz do repositório a ser inspecionado.
            prompt_manager: Instância opcional de LangfusePromptManager (mockable).
        """
        self.project_root = project_root.resolve()
        self.prompt_manager = prompt_manager or LangfusePromptManager()

    def get_changed_files(self) -> list[str]:
        """Obtém a lista de arquivos alterados ou não rastreados no Git local.

        Returns:
            Lista de caminhos de arquivos modificados no workspace.
        """
        git_dir = self.project_root / ".git"
        if not git_dir.is_dir():
            return []

        changed: set[str] = set()
        status_proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if status_proc.returncode == 0:
            for line in status_proc.stdout.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    changed.add(parts[1].strip())

        diff_proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD~1"],
            cwd=self.project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if diff_proc.returncode == 0:
            for line in diff_proc.stdout.splitlines():
                stripped = line.strip()
                if stripped:
                    changed.add(stripped)

        return sorted(changed)

    def validate(self, declared_prompts: list[Any]) -> list[PromptViolation]:
        """Valida conformidade das alterações contra as specs e o Langfuse.

        Args:
            declared_prompts: Nomes de prompts formalmente declarados na spec.

        Returns:
            Lista de violações detectadas pelo sensor.
        """
        violations: list[PromptViolation] = []
        changed_files = self.get_changed_files()
        prompt_files = detect_prompt_files_in_diff(changed_files)

        repo_prompts = filter_prompts_for_repo(
            declared_prompts, self.project_root.name
        )
        normalized_prompts = [
            p["name"] if isinstance(p, dict) else str(p)
            for p in repo_prompts
            if p
        ]

        if prompt_files and not normalized_prompts:
            for p_file in prompt_files:
                violations.append(
                    PromptViolation(
                        file_path=p_file,
                        line_number=1,
                        col_number=1,
                        code="PRM001",
                        message=(
                            f"Arquivo de prompt alterado '{p_file}' sem declaração "
                            "no campo 'prompts' da spec. "
                            "Declare os prompts na spec para governança Langfuse."
                        ),
                    )
                )

        if (
            normalized_prompts
            and self.prompt_manager.is_configured
        ):
            for prompt_name in normalized_prompts:
                self._check_langfuse_draft(prompt_name, violations)

        return violations

    def _check_langfuse_draft(
        self, prompt_name: str, violations: list[PromptViolation]
    ) -> None:
        """Verifica presença do prompt no Langfuse tratando exceções em flat chain.

        Args:
            prompt_name: Nome do prompt declarado na spec.
            violations: Lista acumuladora onde PRM002 é registrada.
        """
        has_error = False
        error_msg = ""
        try:
            self.prompt_manager.fetch_prompt(prompt_name)
        except PromptManagementError as exc:
            has_error = True
            error_msg = str(exc)

        if has_error:
            violations.append(
                PromptViolation(
                    file_path="specs",
                    line_number=1,
                    col_number=1,
                    code="PRM002",
                    message=(
                        f"Prompt '{prompt_name}' declarado na especificação não foi "
                        f"localizado no Langfuse: {error_msg}. "
                        "Declare o prompt no frontmatter da task (campo `prompts:`) "
                        "e execute `harness bug run` ou o fechamento da spec para "
                        "que o ciclo sincronize automaticamente o draft no Langfuse "
                        "(governança SPEC-PROMPT-01)."
                    ),
                )
            )


def is_prompt_file(file_path_str: str) -> bool:
    """Verifica se o caminho do arquivo corresponde a padrões canônicos de prompts."""
    normalized = file_path_str.replace("\\", "/")
    parts = set(normalized.split("/"))
    if parts & IGNORED_PROMPT_PARTS:
        return False
    if (
        normalized.endswith(("current_task_prompt.md", "task_prompt.md"))
    ):
        return False
    for pattern in PROMPT_FILE_PATTERNS:
        if pattern.search(normalized):
            return True
    return False


def detect_prompt_files_in_diff(changed_files: list[str]) -> list[str]:
    """Filtra a lista de arquivos alterados retornando apenas os que definem prompts."""
    matched: list[str] = []
    for f in changed_files:
        if is_prompt_file(f):
            matched.append(f)
    return matched


def is_ignored_prompt_scan_path(file_path: Path, ignored_parts: set[str]) -> bool:
    """Verifica se o caminho pertence a diretórios ignorados na varredura."""
    return any(part in file_path.parts for part in ignored_parts)


def collect_prompt_ids_from_text(
    content: str,
    patterns: list[re.Pattern[str]],
    discovered: set[str],
) -> None:
    """Extrai identificadores de prompt do código-fonte e adiciona ao conjunto."""
    for pat in patterns:
        for match in pat.finditer(content):
            prompt_id = match.group(1).strip()
            if "/" in prompt_id or "_" in prompt_id:
                discovered.add(prompt_id)


def discover_prompts_in_repository(project_root: Path) -> list[str]:
    """Descobre nomes de prompts referenciados no repositório por convenção.

    Examina arquivos Python em busca de chamadas Langfuse e atribuições de nomes.

    Args:
        project_root: Raiz do repositório a ser escaneado.

    Returns:
        Lista ordenada e sem duplicatas com os nomes de prompt localizados.
    """
    if not project_root.is_dir():
        return []

    patterns = [
        re.compile(r'prompt_name\s*=\s*["\']([^"\']+)["\']'),
        re.compile(r'get_prompt\(\s*["\']([^"\']+)["\']'),
        re.compile(r'fetch_prompt\(\s*["\']([^"\']+)["\']'),
        re.compile(r'get_prompt\(\s*prompt_name\s*=\s*["\']([^"\']+)["\']'),
    ]

    discovered: set[str] = set()
    ignored_parts = {".git", ".venv", "__pycache__", ".pytest_cache", "tests"}

    for file_path in project_root.rglob("*.py"):
        if is_ignored_prompt_scan_path(file_path, ignored_parts):
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        collect_prompt_ids_from_text(content, patterns, discovered)

    if not discovered:
        for file_path in project_root.rglob("*.py"):
            if is_ignored_prompt_scan_path(file_path, ignored_parts):
                continue
            cand_rel = str(file_path.relative_to(project_root))
            if is_prompt_file(cand_rel):
                clean_repo = project_root.name.replace("-", "_")
                discovered.add(f"{clean_repo}/instruction")
                break

    return sorted(discovered)


def is_sdd_spec_markdown(content: str) -> bool:
    """Verifica se o conteúdo de um arquivo markdown é uma especificação SDD."""
    stripped = content.strip()
    return (
        stripped.startswith(("---", "# SPEC-"))
        or "# Task:" in stripped
        or "## SDD Specification" in stripped
    )


def extract_instruction_from_python_source(
    content: str,
    variable_name: str,
) -> str | None:
    """Busca o valor atribuído a uma constante de instrução em código Python."""
    candidate_vars = [variable_name]
    for alt in ("INSTRUCTION", "SYSTEM_PROMPT", "PROMPT", "AGENT_INSTRUCTION"):
        if alt not in candidate_vars:
            candidate_vars.append(alt)

    for var in candidate_vars:
        triple_pattern = re.compile(
            rf'(?:^{var}\s*=\s*)(?:"""([\s\S]*?)"""|\'\'\'([\s\S]*?)\'\'\')',
            re.MULTILINE,
        )
        match = triple_pattern.search(content)
        if match:
            text = match.group(1) if match.group(1) is not None else match.group(2)
            return text.strip()

        single_pattern = re.compile(
            rf'(?:^{var}\s*=\s*)(["\'])([\s\S]*?)\1',
            re.MULTILINE,
        )
        single_match = single_pattern.search(content)
        if single_match:
            return single_match.group(2).strip()

    return None


def extract_prompt_text_from_file(
    file_path: Path,
    variable_name: str = "INSTRUCTION",
) -> str:
    """Extrai o conteúdo textual de prompt de um arquivo de código ou texto."""
    if not file_path.is_file():
        return ""

    try:
        content = file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""

    if file_path.suffix.lower() not in (".py",):
        if is_sdd_spec_markdown(content):
            return ""
        return content.strip()

    extracted = extract_instruction_from_python_source(content, variable_name)
    if extracted is not None:
        return extracted

    return content.strip()


def prompt_belongs_to_repo(p: Any, repo_name: str, clean_repo: str) -> bool:
    """Verifica se um item de prompt pertence ao repositório alvo."""
    if isinstance(p, dict):
        p_repo = str(p.get("target_repo", ""))
        p_repo_short = p_repo.split("/")[-1] if p_repo else ""
        return not p_repo or p_repo == repo_name or p_repo_short == repo_name

    p_str = str(p)
    p_prefix = p_str.split("/")[0]
    return p_prefix == clean_repo or p_prefix in repo_name or repo_name in p_prefix


def filter_prompts_for_repo(prompts: list[Any], repo_name: str) -> list[Any]:
    """Filtra prompts declarados mantendo apenas os atribuídos ao repositório alvo."""
    has_target_repo = any(
        isinstance(p, dict) and p.get("target_repo") for p in prompts
    )
    if not has_target_repo:
        return list(prompts)

    clean_repo = repo_name.replace("-", "_")
    return [p for p in prompts if prompt_belongs_to_repo(p, repo_name, clean_repo)]


def sync_missing_declared_prompts(
    project_root: Path,
    manager: LangfusePromptManager,
    prompts_to_sync: list[Any],
) -> list[tuple[str, int]]:
    """Sincroniza prompts declarados ausentes no Langfuse a partir dos arquivos locais.

    Args:
        project_root: Raiz do diretório do projeto ou spoke.
        manager: Gerenciador de prompts do Langfuse.
        prompts_to_sync: Lista de prompts que devem estar registrados no Langfuse.

    Returns:
        Lista de tuplas contendo (nome_do_prompt, versao_criada).
    """
    synced: list[tuple[str, int]] = []
    repo_prompts = filter_prompts_for_repo(prompts_to_sync, project_root.name)
    for p_item in repo_prompts:
        p_name = p_item["name"] if isinstance(p_item, dict) else str(p_item)
        _, _, exists = fetch_prompt_from_manager(manager, p_name)
        if exists:
            continue
        local_file = find_local_prompt_file_for_name(project_root, p_name)
        if not local_file:
            continue
        text = extract_prompt_text_from_file(local_file)
        if not text:
            continue
        version = manager.push_draft(p_name, text, label="draft")
        synced.append((p_name, version))
    return synced


def match_single_prompt_item(
    p_item: Any,
    p_file: str,
    is_single: bool,
) -> str | None:
    """Verifica se um item de prompt corresponde ao arquivo modificado."""
    if isinstance(p_item, dict):
        declared_file = p_item.get("file", "")
        p_name = str(p_item.get("name", ""))
        has_matching_file = declared_file and (
            declared_file == p_file or p_file.endswith(declared_file)
        )
        if has_matching_file:
            return p_name
        p_prefix = p_name.split("/")[0]
        if p_prefix and p_prefix in p_file:
            return p_name
        return None

    p_str = str(p_item)
    p_prefix = p_str.split("/")[0]
    if p_prefix and p_prefix in p_file:
        return p_str
    return None


def resolve_prompts_for_file(
    p_file: str,
    prompts_to_sync: list[Any],
) -> list[str]:
    """Identifica quais prompts do repositório correspondem ao arquivo alterado."""
    is_single = len(prompts_to_sync) == 1
    matches: list[str] = []
    for p_item in prompts_to_sync:
        matched_name = match_single_prompt_item(p_item, p_file, is_single)
        if matched_name:
            matches.append(matched_name)

    if not matches and is_single:
        single = prompts_to_sync[0]
        single_name = single["name"] if isinstance(single, dict) else str(single)
        matches.append(single_name)

    return matches


def sync_modified_prompts_as_draft(
    project_root: Path,
    prompt_manager: Any | None = None,
    target_prompts: list[Any] | None = None,
) -> list[tuple[str, int]]:
    """Sincroniza arquivos de prompt modificados como novas versões draft no Langfuse."""
    manager = prompt_manager
    if not manager or not getattr(manager, 'is_configured', False):
        return []

    sensor = PromptGovernanceSensor(project_root=project_root, prompt_manager=manager)
    changed_files = sensor.get_changed_files()
    prompt_files = detect_prompt_files_in_diff(changed_files)

    raw_prompts = (
        target_prompts
        if target_prompts
        else discover_prompts_in_repository(project_root)
    )
    if not raw_prompts:
        return []

    prompts_to_sync = filter_prompts_for_repo(raw_prompts, project_root.name)
    if not prompts_to_sync:
        return []

    if not prompt_files:
        return sync_missing_declared_prompts(project_root, manager, prompts_to_sync)

    synced: list[tuple[str, int]] = []
    for p_file in prompt_files:
        full_path = project_root / p_file
        text = extract_prompt_text_from_file(full_path)
        if not text:
            continue

        matching_prompts = resolve_prompts_for_file(p_file, prompts_to_sync)
        for p_name in matching_prompts:
            version = manager.push_draft(p_name, text, label="draft")
            synced.append((p_name, version))

    return synced


def find_prompt_file_in_subfolder(
    project_root: Path,
    subfolder: str,
) -> Path | None:
    """Procura arquivo de prompt diretamente dentro de uma subpasta específica."""
    folder_path = project_root / subfolder
    if not folder_path.is_dir():
        return None
    for child in folder_path.iterdir():
        child_rel = str(child.relative_to(project_root))
        if child.is_file() and is_prompt_file(child_rel):
            return child
    return None


def is_subfolder_matching_project(project_root: Path, subfolder: str) -> bool:
    """Verifica se a subpasta ou prefixo do prompt corresponde ao repositório."""
    clean_repo = project_root.name.replace("-", "_")
    return (
        subfolder in clean_repo
        or clean_repo in subfolder
        or subfolder in project_root.name
    )


def scan_for_prompt_file_in_tree(project_root: Path) -> Path | None:
    """Varre a árvore de arquivos procurando o primeiro arquivo de prompt válido."""
    for candidate in project_root.rglob("*.*"):
        if is_ignored_prompt_scan_path(candidate, IGNORED_PROMPT_PARTS):
            continue
        cand_rel = str(candidate.relative_to(project_root))
        if candidate.is_file() and is_prompt_file(cand_rel):
            return candidate
    return None


def find_local_prompt_file_for_name(
    project_root: Path,
    prompt_name: str,
) -> Path | None:
    """Localiza o arquivo local correspondente ao nome do prompt no Langfuse."""
    if not project_root.is_dir():
        return None

    parts = prompt_name.split("/")
    subfolder = parts[0] if len(parts) > 1 else ""
    if subfolder:
        found_sub = find_prompt_file_in_subfolder(project_root, subfolder)
        if found_sub is not None:
            return found_sub
        if not is_subfolder_matching_project(project_root, subfolder):
            return None

    return scan_for_prompt_file_in_tree(project_root)


def fetch_prompt_from_manager(
    manager: LangfusePromptManager,
    prompt_name: str,
) -> tuple[str, int, bool]:
    """Busca o prompt no Langfuse priorizando o label 'production' com fallback.

    Args:
        manager: Instância do LangfusePromptManager.
        prompt_name: Nome do prompt no Langfuse.

    Returns:
        Tupla (conteúdo, versão, sucesso).
    """
    production_found = False
    content = ""
    version = 0
    try:
        content, version = manager.fetch_prompt(prompt_name, label="production")
        production_found = True
    except PromptManagementError:
        production_found = False

    if production_found:
        return content, version, True

    try:
        content, version = manager.fetch_prompt(prompt_name)
        return content, version, True
    except PromptManagementError:
        return "", 0, False


def write_pulled_prompt_to_local_file(
    manager: LangfusePromptManager,
    local_file: Path,
    prompt_content: str,
) -> bool:
    """Atualiza o arquivo local de fallback com o conteúdo baixado do Langfuse.

    Args:
        manager: Instância do LangfusePromptManager.
        local_file: Caminho do arquivo local.
        prompt_content: Conteúdo textual do prompt.

    Returns:
        True se a escrita foi bem-sucedida, False caso contrário.
    """
    if local_file.suffix.lower() == ".py":
        try:
            return manager.update_local_fallback(local_file, prompt_content)
        except PromptManagementError:
            return False

    try:
        local_file.write_text(prompt_content, encoding="utf-8")
        return True
    except OSError:
        return False


def pull_prompts_from_langfuse_ssot(
    project_root: Path,
    prompt_manager: LangfusePromptManager | None = None,
    target_prompts: list[str] | None = None,
) -> list[tuple[str, int, str]]:
    """Garante que os arquivos locais reflitam a versão do Langfuse antes de alterações.

    O Langfuse é a Fonte Única da Verdade (SSOT). Antes de qualquer modificação,
    a versão mais recente aprovada/produtiva é sincronizada no código local.

    Args:
        project_root: Diretório raiz do spoke ou projeto.
        prompt_manager: Instância de LangfusePromptManager configurada.
        target_prompts: Lista opcional de prompts específicos para baixar.

    Returns:
        Lista de tuplas contendo (prompt_name, version_number, local_file_path).
    """
    manager = prompt_manager or LangfusePromptManager()
    if not manager.is_configured:
        return []

    if target_prompts is not None and len(target_prompts) == 0:
        return []

    prompts_to_pull = (
        target_prompts
        if target_prompts is not None
        else discover_prompts_in_repository(project_root)
    )
    if not prompts_to_pull:
        return []

    synced: list[tuple[str, int, str]] = []
    for p_name in prompts_to_pull:
        local_file = find_local_prompt_file_for_name(project_root, p_name)
        if local_file is None:
            continue

        prompt_content, prompt_version, ok = fetch_prompt_from_manager(manager, p_name)
        if not ok or not prompt_content:
            continue

        if write_pulled_prompt_to_local_file(manager, local_file, prompt_content):
            rel_path = str(local_file.relative_to(project_root))
            synced.append((p_name, prompt_version, rel_path))

    return synced
