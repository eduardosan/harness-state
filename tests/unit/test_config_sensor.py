"""Testes unitários para o sensor de higiene de configuração (SPEC-CFG-01)."""

from pathlib import Path
from unittest.mock import patch

from harness_state.sensors.config_sensor import (
    check_forbidden_files,
    is_ignored_by_git,
    is_tracked_by_git,
    run_config_sensor,
    scan_file_for_config_violations,
)


def test_check_forbidden_files_detects_env_and_config(tmp_path: Path) -> None:
    """Business Rule: Detecta arquivos de config proibidos pelo padrão 12-Factor."""
    (tmp_path / ".env").write_text("CRM_URL=http://test\n", encoding="utf-8")
    (tmp_path / "config.yaml").write_text("key: val\n", encoding="utf-8")
    (tmp_path / "config.json").write_text("{}", encoding="utf-8")

    violations = check_forbidden_files(tmp_path)
    codes = [v.code for v in violations]
    files = [str(v.file_path) for v in violations]

    assert len(violations) == 3
    assert all(code == "CFG001" for code in codes)
    assert ".env" in files
    assert "config.yaml" in files
    assert "config.json" in files


def test_scan_file_detects_real_domain_in_code(tmp_path: Path) -> None:
    """Business Rule: Bloqueia domínios de infraestrutura real no código."""
    code_file = tmp_path / "client.py"
    code_file.write_text(
        "CRM_BASE_URL = 'https://crm.paralax.ia.br/api/v1'\n",
        encoding="utf-8",
    )

    violations = scan_file_for_config_violations(code_file, tmp_path)
    assert len(violations) == 1
    assert violations[0].code == "CFG002"
    assert "crm.paralax.ia.br" in violations[0].message


def test_scan_file_detects_real_config_in_test_files(tmp_path: Path) -> None:
    """Business Rule: Bloqueia configurações reais em testes (exige genéricos)."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    test_file = tests_dir / "test_client.py"
    test_file.write_text(
        "def test_client():\n"
        "    url = 'https://crm.paralax.ia.br/api'\n"
        "    client = Client(url=url)\n",
        encoding="utf-8",
    )

    violations = scan_file_for_config_violations(test_file, tmp_path)
    assert len(violations) == 1
    assert violations[0].code == "CFG003"
    assert "Testes DEVEM usar configurações genéricas" in violations[0].message


def test_scan_file_detects_real_ip_in_test_files(tmp_path: Path) -> None:
    """Business Rule: Bloqueia IPs de infraestrutura real em arquivos de testes."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    test_file = tests_dir / "test_redis.py"
    test_file.write_text(
        "def test_redis():\n    host = '192.168.20.99'\n",
        encoding="utf-8",
    )

    violations = scan_file_for_config_violations(test_file, tmp_path)
    assert len(violations) == 1
    assert violations[0].code == "CFG003"
    assert "192.168.20.99" in violations[0].message


def test_scan_file_allows_generic_mock_configs_in_test(tmp_path: Path) -> None:
    """Business Rule: Aprova testes com dados genéricos e não rastreáveis."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(exist_ok=True)
    test_file = tests_dir / "test_safe.py"
    test_file.write_text(
        "def test_safe():\n"
        "    url = 'http://mock-service:8080'\n"
        "    local = 'http://localhost:8000'\n"
        "    token = 'fake-token-123'\n",
        encoding="utf-8",
    )

    violations = scan_file_for_config_violations(test_file, tmp_path)
    assert len(violations) == 0


def test_scan_file_detects_real_secret_keys(tmp_path: Path) -> None:
    """Business Rule: Bloqueia chaves de API secretas com formato real hardcoded."""
    code_file = tmp_path / "service.py"
    code_file.write_text(
        "LANGFUSE_SECRET = 'sk-lf-9876543210abcdef0123456789abcdef'\n",
        encoding="utf-8",
    )

    violations = scan_file_for_config_violations(code_file, tmp_path)
    assert len(violations) == 1
    assert violations[0].code == "CFG004"
    assert "Chave de API secreta real hardcoded detectada" in violations[0].message


def test_run_config_sensor_integration(tmp_path: Path) -> None:
    """Business Rule: Executa varredura recursiva completa e agrega violações."""
    (tmp_path / ".env").write_text("SECRET=123\n", encoding="utf-8")
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text(
        "HOST = 'https://paralax.ia.br'\n", encoding="utf-8"
    )

    violations = run_config_sensor(tmp_path)
    assert len(violations) == 2
    codes = {v.code for v in violations}
    assert "CFG001" in codes
    assert "CFG002" in codes


def test_is_ignored_by_git_pure_python_without_subprocess(tmp_path: Path) -> None:
    """Business Rule: A detecção de gitignore deve ser pura em Python sem subprocess."""
    gitignore = tmp_path / ".gitignore"
    gitignore.write_text(
        "# Comentário\n\n.env\n*.local\nsecrets/\n",
        encoding="utf-8",
    )
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar", encoding="utf-8")
    local_file = tmp_path / "config.local"
    local_file.write_text("SECRET=1", encoding="utf-8")
    unignored = tmp_path / "app.py"
    unignored.write_text("print(1)", encoding="utf-8")

    with patch(
        "subprocess.run",
        side_effect=RuntimeError("subprocess.run must not be called"),
    ):
        assert is_ignored_by_git(env_file, tmp_path) is True
        assert is_ignored_by_git(local_file, tmp_path) is True
        assert is_ignored_by_git(unignored, tmp_path) is False


def test_is_tracked_by_git_handles_missing_or_corrupt_index_safely(
    tmp_path: Path,
) -> None:
    """Business Rule: Rastreamento git não deve invocar subprocess e lida com falhas."""
    dummy_file = tmp_path / "file.txt"
    dummy_file.write_text("test", encoding="utf-8")

    with patch(
        "subprocess.run",
        side_effect=RuntimeError("subprocess.run must not be called"),
    ):
        # Repositório sem .git
        assert is_tracked_by_git(dummy_file, tmp_path) is False

        # Repositório com .git/index corrompido
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "index").write_bytes(b"INVALID_HEADER")
        assert is_tracked_by_git(dummy_file, tmp_path) is False