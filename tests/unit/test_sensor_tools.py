"""Testes unitários para ferramentas de sensores utilizadas pelo Coder Runtime."""

import subprocess
from pathlib import Path

from harness_state.runtimes.sensor_tools import (
    run_complexity_sensor,
    run_tdd_test,
    run_verification_sensor,
)


def test_sensor_tools_retorna_tupla_status_e_feedback(tmp_path: Path) -> None:
    """Business Rule: as ferramentas de sensores devem retornar status booleano e mensagem descritiva."""
    passed, feedback = run_complexity_sensor(tmp_path, max_complexity=15)
    assert isinstance(passed, bool)
    assert isinstance(feedback, str)


def test_run_tdd_test_retorna_true_quando_pytest_passa(tmp_path: Path) -> None:
    """Business Rule: run_tdd_test deve reportar sucesso quando pytest sair com código zero."""
    test_file = tmp_path / "test_dummy.py"
    test_file.write_text("def test_ok(): assert True\n", encoding="utf-8")

    def mock_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="1 passed in 0.01s", stderr="")

    passed, feedback = run_tdd_test(test_file, runner=mock_runner)
    assert passed is True
    assert "1 passed" in feedback


def test_run_tdd_test_retorna_false_quando_pytest_falha(tmp_path: Path) -> None:
    """Business Rule: run_tdd_test deve reportar falha quando pytest retornar código não zero."""
    test_file = tmp_path / "test_dummy.py"
    test_file.write_text("def test_fail(): assert False\n", encoding="utf-8")

    def mock_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="AssertionError")

    passed, feedback = run_tdd_test(test_file, runner=mock_runner)
    assert passed is False
    assert "AssertionError" in feedback


def test_run_verification_sensor_executa_just_verify(tmp_path: Path) -> None:
    """Business Rule: run_verification_sensor deve acionar just verify no diretório informado."""
    executed_commands: list[list[str]] = []

    def mock_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        executed_commands.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="Verification succeeded", stderr="")

    passed, feedback = run_verification_sensor(tmp_path, runner=mock_runner)
    assert passed is True
    assert "Verification succeeded" in feedback
    assert executed_commands[0] == ["just", "verify"]
