"""Operações unificadas de workspace, auto-clonagem e governança."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from harness_state.capabilities import RepoMetadata, load_manifest
from harness_state.installer import HarnessInitResult, install_module_harness


@dataclass(slots=True)
class WorkspaceRepoStatus:
    """Status da sincronização de um repositório no workspace.

    Attributes:
        name: Nome do repositório local.
        repo: Identificador remoto (ex: org/repo).
        status: Estado ('cloned', 'existing', 'failed').
        path: Caminho no disco.
        message: Mensagem detalhada de feedback.
    """

    name: str
    repo: str
    status: str
    path: Path
    message: str = ""


@dataclass(slots=True)
class PreflightResult:
    """Resultado da rotina de pré-voo de uma especificação.

    Attributes:
        success: Indica se todos os repositórios foram verificados com sucesso.
        updated_repos: Lista de repositórios que receberam git fetch.
        cloned_repos: Lista de repositórios clonados durante o pré-voo.
        errors: Lista de erros encontrados.
    """

    success: bool
    updated_repos: list[str] = field(default_factory=list)
    cloned_repos: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def find_spec_hub_manifest_in_dir(directory: Path) -> Path | None:
    """Procura um manifest.yaml dentro de subdiretórios spec-hub de um diretório.

    Args:
        directory: Diretório pai onde os subdiretórios serão inspecionados.

    Returns:
        Path para o manifest.yaml encontrado ou None.
    """
    for child in directory.iterdir():
        if not (child.is_dir() and "spec-hub" in child.name):
            continue
        candidate = child / "manifest.yaml"
        if candidate.is_file():
            return candidate
    return None


def find_manifest_path(
    workspace_root: Path | None = None,
    explicit_path: Path | None = None,
) -> Path | None:
    """Localiza o arquivo manifest.yaml no workspace ou nos diretórios vizinhos.

    Args:
        workspace_root: Diretório raiz do workspace (padrão: diretório atual).
        explicit_path: Caminho explícito opcional fornecido pelo usuário.

    Returns:
        Path válido para o manifest.yaml ou None se não for encontrado.
    """
    if explicit_path is not None and explicit_path.is_file():
        return explicit_path.resolve()

    root = (workspace_root or Path.cwd()).resolve()

    direct_candidate = root / "manifest.yaml"
    if direct_candidate.is_file():
        return direct_candidate

    child_manifest = find_spec_hub_manifest_in_dir(root)
    if child_manifest is not None:
        return child_manifest

    parent = root.parent
    sibling_manifest = find_spec_hub_manifest_in_dir(parent)
    if sibling_manifest is not None:
        return sibling_manifest

    parent_candidate = parent / "manifest.yaml"
    if parent_candidate.is_file():
        return parent_candidate

    return None


def clone_repository(
    repo_meta: RepoMetadata,
    workspace_root: Path,
    use_https: bool = False,
) -> WorkspaceRepoStatus:
    """Clona um repositório remoto para o workspace local caso não exista.

    Args:
        repo_meta: Metadados do repositório a ser clonado.
        workspace_root: Diretório raiz do workspace.
        use_https: Se True, utiliza o protocolo HTTPS em vez de SSH.

    Returns:
        WorkspaceRepoStatus com o resultado da operação.
    """
    target_dir = workspace_root / repo_meta.name
    if (target_dir / ".git").is_dir():
        return WorkspaceRepoStatus(
            name=repo_meta.name,
            repo=repo_meta.repo,
            status="existing",
            path=target_dir,
            message="Repositório já presente no workspace.",
        )

    if use_https:
        clone_url = f"https://github.com/{repo_meta.repo}.git"
    else:
        clone_url = f"git@github.com:{repo_meta.repo}.git"

    cmd = ["git", "clone", clone_url, str(target_dir)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    if proc.returncode == 0:
        target_dir.mkdir(parents=True, exist_ok=True)
        return WorkspaceRepoStatus(
            name=repo_meta.name,
            repo=repo_meta.repo,
            status="cloned",
            path=target_dir,
            message=f"Clonado com sucesso via {'HTTPS' if use_https else 'SSH'}.",
        )

    return WorkspaceRepoStatus(
        name=repo_meta.name,
        repo=repo_meta.repo,
        status="failed",
        path=target_dir,
        message=f"Falha ao clonar: {proc.stderr.strip()}",
    )


def sync_workspace_repositories(
    manifest_path: Path,
    workspace_root: Path,
    use_https: bool = False,
) -> list[WorkspaceRepoStatus]:
    """Sincroniza e clona todos os repositórios declarados no manifesto.

    Args:
        manifest_path: Caminho para o manifest.yaml.
        workspace_root: Diretório raiz do workspace local.
        use_https: Se True, clona via HTTPS.

    Returns:
        Lista de WorkspaceRepoStatus para cada repositório processado.
    """
    manifest_cfg = load_manifest(manifest_path)
    statuses: list[WorkspaceRepoStatus] = []

    for repo_meta in manifest_cfg.repositories:
        status = clone_repository(
            repo_meta=repo_meta,
            workspace_root=workspace_root,
            use_https=use_https,
        )
        statuses.append(status)

    return statuses


def init_all_repositories(
    manifest_path: Path,
    workspace_root: Path,
    use_https: bool = False,
    ci_mode: bool = False,
    force: bool = False,
) -> list[HarnessInitResult]:
    """Auto-clona repositórios ausentes e inicializa o harness em todos os declarados.

    Args:
        manifest_path: Caminho para o manifest.yaml.
        workspace_root: Diretório raiz do workspace.
        use_https: Se True, clona via HTTPS.
        ci_mode: Se True, provisiona apenas sensores para CI.
        force: Se True, sobrescreve arquivos existentes.

    Returns:
        Lista de HarnessInitResult de cada repositório inicializado.
    """
    sync_workspace_repositories(
        manifest_path=manifest_path,
        workspace_root=workspace_root,
        use_https=use_https,
    )

    manifest_cfg = load_manifest(manifest_path)
    init_results: list[HarnessInitResult] = []

    for repo_meta in manifest_cfg.repositories:
        repo_dir = workspace_root / repo_meta.name
        if not repo_dir.is_dir():
            continue

        result = install_module_harness(
            project_root=repo_dir,
            language=repo_meta.language,
            ci_mode=ci_mode,
            force=force,
        )
        init_results.append(result)

    return init_results


def preflight_spec_workspace(
    spec_path: Path,
    manifest_path: Path | None,
    workspace_root: Path,
    use_https: bool = False,
) -> PreflightResult:
    """Executa a rotina de pré-voo com git fetch e garantia de presença dos spokes.

    Args:
        spec_path: Caminho para o arquivo da especificação.
        manifest_path: Caminho opcional do manifest.yaml.
        workspace_root: Diretório raiz do workspace.
        use_https: Se True, clona via HTTPS quando necessário.

    Returns:
        PreflightResult contendo o resumo das verificações e atualizações.
    """
    resolved_manifest = manifest_path or find_manifest_path(
        workspace_root=workspace_root
    )
    if resolved_manifest is None or not resolved_manifest.is_file():
        return PreflightResult(
            success=False,
            errors=["Manifesto manifest.yaml não localizado para o pré-voo."],
        )

    manifest_cfg = load_manifest(resolved_manifest)
    updated: list[str] = []
    cloned: list[str] = []
    errors: list[str] = []

    for repo_meta in manifest_cfg.repositories:
        repo_dir = workspace_root / repo_meta.name
        if not (repo_dir / ".git").is_dir():
            clone_res = clone_repository(
                repo_meta=repo_meta,
                workspace_root=workspace_root,
                use_https=use_https,
            )
            if clone_res.status == "cloned":
                cloned.append(repo_meta.name)
                install_module_harness(
                    project_root=repo_dir,
                    language=repo_meta.language,
                )
            else:
                errors.append(f"Falha ao clonar {repo_meta.name}: {clone_res.message}")
                continue

        fetch_proc = subprocess.run(
            ["git", "-C", str(repo_dir), "fetch", "--all", "--tags", "--prune"],
            capture_output=True,
            text=True,
            check=False,
        )
        if fetch_proc.returncode == 0:
            updated.append(repo_meta.name)
        else:
            err_msg = fetch_proc.stderr.strip()
            errors.append(f"Falha no git fetch de {repo_meta.name}: {err_msg}")

    success = len(errors) == 0
    return PreflightResult(
        success=success,
        updated_repos=updated,
        cloned_repos=cloned,
        errors=errors,
    )


def default_human_approval_prompt(prompt_message: str) -> bool:
    """Apresenta um prompt de confirmação no console para o operador humano.

    Args:
        prompt_message: Mensagem explicativa apresentada ao usuário.

    Returns:
        True se o usuário confirmar ('y' ou 'yes'), False caso contrário.
    """
    print(prompt_message)
    response = input("Confirmar criação no GitHub? [y/N]: ").strip().lower()
    return response in ("y", "yes")


def prompt_create_new_repository(
    repo_name: str,
    org: str,
    role: str,
    language: str,
    private: bool = True,
    approval_callback: Callable[[str], bool] | None = None,
) -> bool:
    """Solicita aprovação humana formal (Gate 1) e cria novo repo via gh CLI.

    Args:
        repo_name: Nome do repositório a ser criado.
        org: Organização do GitHub.
        role: Papel arquitetural no ecossistema (ai-agent, sdk, etc.).
        language: Linguagem principal do repositório.
        private: Se True, cria repositório como privado.
        approval_callback: Callback opcional de confirmação (utilizado para testes).

    Returns:
        True se o repositório foi aprovado e criado, False se rejeitado ou com erro.
    """
    full_name = f"{org}/{repo_name}"
    message = (
        f"\n[GATE HUMANO 1] A especificação requer um novo repositório:\n"
        f"  • Repositório: {full_name}\n"
        f"  • Papel: {role}\n"
        f"  • Linguagem: {language}\n"
        f"  • Visibilidade: {'privada' if private else 'pública'}\n"
    )

    ask_func = approval_callback or default_human_approval_prompt
    if not ask_func(message):
        return False

    visibility_flag = "--private" if private else "--public"
    cmd = ["gh", "repo", "create", full_name, visibility_flag]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)

    return proc.returncode == 0
