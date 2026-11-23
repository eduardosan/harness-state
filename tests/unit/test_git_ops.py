"""Testes unitários para operações Git e suporte a repositórios locais/não-GitHub."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_state.git_ops import (
    ensure_task_issue,
    is_github_repo,
    publish_task_pr,
)


def test_is_github_repo_returns_true_for_github_remote(tmp_path: Path) -> None:
    """Business Rule: is_github_repo deve retornar True quando origin aponta para github.com."""
    fake_git = tmp_path / ".git"
    fake_git.mkdir()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "git@github.com:eduardosan/harness-slack-bot.git\n"

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        result = is_github_repo(tmp_path)
        assert result is True
        mock_run.assert_called_once_with(
            ["git", "remote", "get-url", "origin"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )


def test_is_github_repo_returns_false_for_internal_git_server(tmp_path: Path) -> None:
    """Business Rule: is_github_repo deve retornar False para servidores Git internos como 192.168.0.200."""
    fake_git = tmp_path / ".git"
    fake_git.mkdir()

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.stdout = "git+ssh://git@192.168.0.200/trab/ansible-hetzner-new.git/\n"

    with patch("subprocess.run", return_value=mock_proc):
        result = is_github_repo(tmp_path)
        assert result is False


def test_is_github_repo_returns_false_when_no_git_dir(tmp_path: Path) -> None:
    """Business Rule: is_github_repo deve retornar False se o diretório não tiver .git."""
    result = is_github_repo(tmp_path)
    assert result is False


def test_ensure_task_issue_skips_gh_for_non_github_repo(tmp_path: Path) -> None:
    """Business Rule: ensure_task_issue não deve invocar gh para repositórios fora do GitHub."""
    fake_git = tmp_path / ".git"
    fake_git.mkdir()

    with (
        patch("harness_state.git_ops.is_github_repo", return_value=False),
        patch("subprocess.run") as mock_run,
    ):
        num, url = ensure_task_issue(
            repo_dir=tmp_path,
            spec_id="SPEC-014",
            task_id="task-2",
            task_title="Infra Ansible",
        )
        assert num is None
        assert url is None
        mock_run.assert_not_called()


def test_publish_task_pr_skips_pr_creation_for_non_github_repo(tmp_path: Path) -> None:
    """Business Rule: publish_task_pr deve fazer push mas não criar PR via gh em repositório não-GitHub."""
    fake_git = tmp_path / ".git"
    fake_git.mkdir()

    push_proc = MagicMock()
    push_proc.returncode = 0
    push_proc.stdout = ""

    with (
        patch("harness_state.git_ops.is_github_repo", return_value=False),
        patch("subprocess.run", return_value=push_proc) as mock_run,
    ):
        pr_num, pr_url, msg = publish_task_pr(
            repo_dir=tmp_path,
            spec_id="SPEC-014",
            branch_name="agent/harness-spec-014-ansible-hetzner-new",
            spec_title="Infra Ansible",
        )
        assert pr_num is None
        assert pr_url is None
        assert "sem host GitHub" in msg
        mock_run.assert_called_once_with(
            ["git", "push", "-u", "origin", "agent/harness-spec-014-ansible-hetzner-new"],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=False,
        )
