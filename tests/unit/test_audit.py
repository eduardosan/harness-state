"""Testes unitários para o auditor de integridade e mascaramento de dados sensíveis (SPEC-009E)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_state.audit import audit_sensitive_data, list_tracked_text_files


def test_audit_sensitive_data_flags_forbidden_ips(tmp_path: Path) -> None:
    """Business Rule: Detecta e aponta ocorrência de IPs reais de servidores internos."""
    bad_file = tmp_path / "README.md"
    bad_file.write_text(
        "Conecte no servidor 192.168.20.5 para o banco de dados.",
        encoding="utf-8",
    )

    with patch("harness_state.audit.list_tracked_text_files", return_value=[bad_file]):
        offenders = audit_sensitive_data(tmp_path)
        assert len(offenders) == 1
        assert "README.md" in offenders[0]
        assert "192.168.20.5" in offenders[0]


def test_audit_sensitive_data_flags_forbidden_hosts(tmp_path: Path) -> None:
    """Business Rule: Detecta e aponta ocorrência de hostnames internos não mascarados."""
    bad_doc = tmp_path / "docs.md"
    bad_doc.write_text(
        "Host do cluster: pve2.for.mat.br na porta 8443", encoding="utf-8"
    )

    with patch("harness_state.audit.list_tracked_text_files", return_value=[bad_doc]):
        offenders = audit_sensitive_data(tmp_path)
        assert len(offenders) == 1
        assert "pve2.for.mat.br" in offenders[0]


def test_audit_sensitive_data_flags_raw_github_tokens(tmp_path: Path) -> None:
    """Business Rule: Detecta e aponta tokens reais de serviço ou pessoais (ghs_ / ghp_)."""
    bad_env_example = tmp_path / "config.example.yaml"
    bad_env_example.write_text(
        "token: ghs_123456789012345678901234567890\n", encoding="utf-8"
    )

    with patch(
        "harness_state.audit.list_tracked_text_files",
        return_value=[bad_env_example],
    ):
        offenders = audit_sensitive_data(tmp_path)
        assert len(offenders) == 1
        assert "ghs_" in offenders[0]


def test_audit_sensitive_data_passes_clean_documentation(tmp_path: Path) -> None:
    """Business Rule: Aprova arquivos que usam placeholders conforme especificação §7."""
    clean_doc = tmp_path / "SETUP.md"
    clean_doc.write_text(
        """
server:
  host: "{{INTERNAL_HOST}}"
  port: "{{PORT}}"
  token: "{{GITHUB_TOKEN}}"
""",
        encoding="utf-8",
    )

    with patch("harness_state.audit.list_tracked_text_files", return_value=[clean_doc]):
        offenders = audit_sensitive_data(tmp_path)
        assert offenders == []


def test_list_tracked_text_files_filters_extensions(tmp_path: Path) -> None:
    """Business Rule: Filtra apenas arquivos de texto elegíveis ignorando binários."""
    mock_proc = MagicMock(
        returncode=0,
        stdout="README.md\nsrc/code.py\nimage.png\nMakefile\n",
    )
    with patch("subprocess.run", return_value=mock_proc):
        files = list_tracked_text_files(tmp_path)
        file_names = [f.name for f in files]
        assert "README.md" in file_names
        assert "code.py" in file_names
        assert "Makefile" in file_names
        assert "image.png" not in file_names
