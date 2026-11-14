"""Módulo para sincronização e instalação sob demanda do Superpowers do upstream."""

import os
import shutil
import subprocess
from pathlib import Path

from harness_state.installer import (
    copy_skill_group,
    get_catalog_root,
    install_agent_guidelines,
)

DEFAULT_SUPERPOWERS_REPO = "https://github.com/obra/superpowers.git"


def get_default_superpowers_cache_dir() -> Path:
    """Retorna o diretório padrão de cache para o repositório do Superpowers.

    Returns:
        Path para `~/.cache/harness-state/superpowers` ou valor da variável de
        ambiente canônica `HARNESS_SUPERPOWERS_CACHE_DIR`, aceitando a env legada
        `FLYWHEEL_SUPERPOWERS_CACHE_DIR` como fallback de compatibilidade.
    """
    env_cache = os.environ.get(
        "HARNESS_SUPERPOWERS_CACHE_DIR"
    ) or os.environ.get("FLYWHEEL_SUPERPOWERS_CACHE_DIR")
    if env_cache:
        return Path(env_cache).expanduser().resolve()
    return Path.home() / ".cache" / "harness-state" / "superpowers"


def sync_superpowers_upstream(
    cache_dir: Path | None = None,
    repo_url: str = DEFAULT_SUPERPOWERS_REPO,
) -> Path:
    """Clona ou atualiza o repositório upstream do Superpowers em um cache local.

    Args:
        cache_dir: Diretório de cache opcional. Se omitido, usa o padrão do usuário.
        repo_url: URL do repositório Git upstream.

    Returns:
        Path apontando para o diretório de cache atualizado.

    Raises:
        RuntimeError: Se a operação do Git falhar.
    """
    resolved_cache = cache_dir or get_default_superpowers_cache_dir()

    if (resolved_cache / ".git").is_dir():
        cmd = ["git", "-C", str(resolved_cache), "pull", "--ff-only"]
        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if res.returncode != 0:
            cmd_reset = [
                "git",
                "-C",
                str(resolved_cache),
                "fetch",
                "--depth",
                "1",
                "origin",
            ]
            subprocess.run(cmd_reset, capture_output=True, text=True, check=False)
            cmd_hard = [
                "git",
                "-C",
                str(resolved_cache),
                "reset",
                "--hard",
                "origin/main",
            ]
            subprocess.run(cmd_hard, capture_output=True, text=True, check=False)
        return resolved_cache

    resolved_cache.parent.mkdir(parents=True, exist_ok=True)
    if resolved_cache.exists():
        shutil.rmtree(resolved_cache)

    cmd_clone = [
        "git",
        "clone",
        "--depth",
        "1",
        repo_url,
        str(resolved_cache),
    ]
    res_clone = subprocess.run(cmd_clone, capture_output=True, text=True, check=False)
    if res_clone.returncode != 0:
        raise RuntimeError(
            f"Falha ao clonar Superpowers de {repo_url}: {res_clone.stderr}"
        )

    return resolved_cache


def install_superpowers_from_upstream(
    project_root: Path,
    cache_dir: Path | None = None,
    repo_url: str = DEFAULT_SUPERPOWERS_REPO,
) -> list[str]:
    """Baixa as skills do repositório upstream do Superpowers e integra ao módulo.

    Instala as skills do Superpowers em `.claude/skills/`, copia a skill de
    orquestração `federated-sdd` e atualiza as diretrizes em `AGENTS.md` e `CLAUDE.md`.

    Args:
        project_root: Raiz do módulo onde as skills serão instaladas.
        cache_dir: Diretório de cache opcional para o clone do upstream.
        repo_url: URL do repositório Git do Superpowers.

    Returns:
        Lista de caminhos relativos de arquivos instalados ou atualizados.
    """
    resolved_root = project_root.resolve()
    target_skills_dir = resolved_root / ".claude" / "skills"
    target_skills_dir.mkdir(parents=True, exist_ok=True)

    cached_repo = sync_superpowers_upstream(cache_dir=cache_dir, repo_url=repo_url)
    upstream_skills_dir = cached_repo / "skills"

    installed_files: list[str] = []
    installed_files.extend(
        copy_skill_group(upstream_skills_dir, target_skills_dir, resolved_root)
    )

    catalog_root = get_catalog_root()
    federated_sdd_dir = catalog_root / "skills" / "common" / "federated-sdd"
    if federated_sdd_dir.is_dir():
        dest_federated = target_skills_dir / "federated-sdd"
        if dest_federated.exists():
            shutil.rmtree(dest_federated)
        shutil.copytree(federated_sdd_dir, dest_federated)
        for sub_file in sorted(dest_federated.rglob("*")):
            if sub_file.is_file():
                installed_files.append(str(sub_file.relative_to(resolved_root)))

    guidelines_files = install_agent_guidelines(resolved_root)
    installed_files.extend(guidelines_files)

    return installed_files