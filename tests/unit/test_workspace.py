"""Testes unitários para operações de workspace e sincronização de repositórios."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_state.workspace import (
    find_manifest_path,
    init_all_repositories,
    preflight_spec_workspace,
    prompt_create_new_repository,
    sync_workspace_repositories,
)


def create_fake_manifest(tmp_path: Path) -> Path:
    """Cria um arquivo manifest.yaml simulado para testes.

    Args:
        tmp_path: Diretório temporário fornecido pelo pytest.

    Returns:
        Path para o manifest.yaml gerado.
    """
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(
        "version: '1.0'\n"
        "project: 'test-project'\n"
        "repositories:\n"
        "  - name: 'repo-one'\n"
        "    repo: 'test-org/repo-one'\n"
        "    role: 'sdk'\n"
        "    language: 'python'\n"
        "  - name: 'repo-two'\n"
        "    repo: 'test-org/repo-two'\n"
        "    role: 'ai-agent'\n"
        "    language: 'python'\n",
        encoding="utf-8",
    )
    return manifest_file


def test_find_manifest_path_in_explicit_location(tmp_path: Path) -> None:
    """Business Rule: Localizar manifesto no caminho explícito fornecido."""
    manifest_file = create_fake_manifest(tmp_path)
    found = find_manifest_path(workspace_root=tmp_path, explicit_path=manifest_file)
    assert found == manifest_file


def test_find_manifest_path_in_sibling_spec_hub(tmp_path: Path) -> None:
    """Business Rule: Autodescobrir manifest.yaml em pasta spec-hub irmã."""
    hub_dir = tmp_path / "test-spec-hub"
    hub_dir.mkdir(parents=True)
    manifest_file = hub_dir / "manifest.yaml"
    manifest_file.write_text("version: '1.0'\nrepositories: []\n", encoding="utf-8")

    sub_repo = tmp_path / "my-agent"
    sub_repo.mkdir()

    found = find_manifest_path(workspace_root=sub_repo)
    assert found == manifest_file


def test_clone_missing_repositories_via_ssh(tmp_path: Path) -> None:
    """Business Rule: O comando clone deve baixar via SSH os repos faltantes."""
    manifest_file = create_fake_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        statuses = sync_workspace_repositories(
            manifest_path=manifest_file,
            workspace_root=workspace,
            use_https=False,
        )

        assert len(statuses) == 2
        assert statuses[0].name == "repo-one"
        assert statuses[0].status == "cloned"
        assert statuses[1].name == "repo-two"
        assert statuses[1].status == "cloned"

        assert mock_run.call_count == 2
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "git@github.com:test-org/repo-one.git" in first_call_args


def test_clone_skips_existing_repositories(tmp_path: Path) -> None:
    """Business Rule: Repositórios já presentes não devem ser re-clonados."""
    manifest_file = create_fake_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    repo_one_dir = workspace / "repo-one" / ".git"
    repo_one_dir.mkdir(parents=True)

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        statuses = sync_workspace_repositories(
            manifest_path=manifest_file,
            workspace_root=workspace,
            use_https=False,
        )

        assert len(statuses) == 2
        assert statuses[0].status == "existing"
        assert statuses[1].status == "cloned"


def test_init_all_clones_missing_and_installs_harness(tmp_path: Path) -> None:
    """Business Rule: init --all deve auto-clonar antes de iniciar harness."""
    manifest_file = create_fake_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with (
        patch("subprocess.run") as mock_run,
        patch("harness_state.workspace.install_module_harness") as mock_install,
    ):
        mock_run.return_value = MagicMock(returncode=0)
        mock_install.return_value = MagicMock(installed_skills=["skill1"])

        results = init_all_repositories(
            manifest_path=manifest_file,
            workspace_root=workspace,
            use_https=False,
        )

        assert len(results) == 2
        assert mock_install.call_count == 2


def test_preflight_git_fetch_ensures_freshness(tmp_path: Path) -> None:
    """Business Rule: Pré-voo de specs deve executar git fetch nos spokes."""
    manifest_file = create_fake_manifest(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    (workspace / "repo-one" / ".git").mkdir(parents=True)
    (workspace / "repo-two" / ".git").mkdir(parents=True)

    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text(
        "---\nid: SPEC-001\nstatus: DRAFT\n---\n# Spec 1", encoding="utf-8"
    )

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = preflight_spec_workspace(
            spec_path=spec_file,
            manifest_path=manifest_file,
            workspace_root=workspace,
        )

        assert result.success is True
        assert mock_run.call_count == 2
        cmd = mock_run.call_args_list[0][0][0]
        assert "git" in cmd
        assert "fetch" in cmd


def test_create_new_repo_with_human_approval() -> None:
    """Business Rule: Criar novo repo requer confirmação antes do gh repo create."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        approved = prompt_create_new_repository(
            repo_name="new-agent",
            org="test-org",
            role="ai-agent",
            language="python",
            approval_callback=lambda _: True,
        )

        assert approved is True
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "repo" in cmd
        assert "create" in cmd


def test_create_new_repo_aborts_without_human_approval() -> None:
    """Business Rule: Rejeição humana aborta criação do repo com segurança."""
    with patch("subprocess.run") as mock_run:
        approved = prompt_create_new_repository(
            repo_name="new-agent",
            org="test-org",
            role="ai-agent",
            language="python",
            approval_callback=lambda _: False,
        )

        assert approved is False
        mock_run.assert_not_called()
