"""Testes unitários para o módulo allowlist (SPEC-009E)."""

from pathlib import Path

import pytest

from harness_state.allowlist import (
    RepoNotAllowedError,
    TargetRepoConfig,
    get_repo_config,
)


def test_get_repo_config_success(tmp_path: Path) -> None:
    """Business Rule: Recupera a configuração válida do repositório autorizado."""
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text(
        """
repos:
  - repo: paralax-ia/evo-crm
    language: python
    base_branch: main
  - repo: paralax-ia/gateway-go
    language: go
    base_branch: develop
""",
        encoding="utf-8",
    )

    config = get_repo_config(repos_file, "paralax-ia/evo-crm")
    assert isinstance(config, TargetRepoConfig)
    assert config.repo == "paralax-ia/evo-crm"
    assert config.language == "python"
    assert config.base_branch == "main"

    config_go = get_repo_config(repos_file, "paralax-ia/gateway-go")
    assert config_go.language == "go"
    assert config_go.base_branch == "develop"


def test_get_repo_config_not_found_raises(tmp_path: Path) -> None:
    """Business Rule: Dispara RepoNotAllowedError quando o repositório não consta na lista."""
    repos_file = tmp_path / "repos.yml"
    repos_file.write_text("repos: []\n", encoding="utf-8")

    with pytest.raises(RepoNotAllowedError) as exc_info:
        get_repo_config(repos_file, "unauthorized/repo")

    assert "Repositório não autorizado" in str(exc_info.value)


def test_get_repo_config_missing_file_raises(tmp_path: Path) -> None:
    """Business Rule: Dispara RepoNotAllowedError se o arquivo repos.yml não existir."""
    missing_file = tmp_path / "non_existent_repos.yml"

    with pytest.raises(RepoNotAllowedError) as exc_info:
        get_repo_config(missing_file, "some/repo")

    assert "Arquivo de allowlist não encontrado" in str(exc_info.value)
