"""Gerenciamento de allowlist de repositórios para o hub e spokes."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class RepoNotAllowedError(Exception):
    """Exceção lançada quando o repositório não consta na allowlist."""


@dataclass(frozen=True)
class TargetRepoConfig:
    """Configuração de um repositório alvo na allowlist.

    Attributes:
        repo: Nome completo do repositório (ex: org/repo).
        language: Linguagem principal do projeto.
        base_branch: Branch base para submissão de PRs.
    """

    repo: str
    language: str
    base_branch: str = "main"


def get_repo_config(allowlist_path: Path, repo_name: str) -> TargetRepoConfig:
    """Obtém a configuração de um repositório alvo a partir da allowlist.

    Args:
        allowlist_path: Caminho para o arquivo repos.yml.
        repo_name: Nome completo do repositório buscado.

    Returns:
        Instância de TargetRepoConfig correspondente.

    Raises:
        RepoNotAllowedError: Se o repositório não estiver configurado.
    """
    if not allowlist_path.is_file():
        raise RepoNotAllowedError(
            f"Arquivo de allowlist não encontrado: {allowlist_path}"
        )

    with open(allowlist_path, "r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    repos = data.get("repos", [])
    for entry in repos:
        if entry.get("repo") == repo_name:
            return TargetRepoConfig(
                repo=entry["repo"],
                language=entry.get("language", "python"),
                base_branch=entry.get("base_branch", "main"),
            )

    raise RepoNotAllowedError(f"Repositório não autorizado na allowlist: {repo_name}")
