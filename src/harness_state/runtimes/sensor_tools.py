"""Ferramentas tipadas de sensores para runtimes de agentes (Pydantic AI Coder).

Fornece funções desacopladas para verificação de TDD, complexidade cognitiva
e execução do sensor unificado de pipeline (`just verify`).
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from harness_state.sensors.complexity_sensor import (
    DEFAULT_MAX_COMPLEXITY,
)
from harness_state.sensors.complexity_sensor import (
    run_complexity_sensor as execute_complexity_scan,
)

SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]


def run_tdd_test(
    test_path: Path,
    runner: SubprocessRunner | None = None,
) -> tuple[bool, str]:
    """Executa um teste unitário via pytest e retorna o resultado.

    Args:
        test_path: Caminho do arquivo de teste.
        runner: Função opcional compatível com `subprocess.run`.

    Returns:
        Tupla `(sucesso, feedback_ou_stdout)`.
    """
    exec_runner = runner or subprocess.run
    cmd = ["pytest", str(test_path), "-v"]
    try:
        proc = exec_runner(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"Falha ao executar pytest para {test_path}: {exc}"

    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()


def run_verification_sensor(
    repo_dir: Path,
    runner: SubprocessRunner | None = None,
) -> tuple[bool, str]:
    """Executa o pipeline unificado de verificação do harness (`just verify`).

    Args:
        repo_dir: Diretório raiz do módulo ou spoke.
        runner: Função opcional compatível com `subprocess.run`.

    Returns:
        Tupla `(sucesso, feedback_ou_stdout)`.
    """
    exec_runner = runner or subprocess.run
    cmd = ["just", "verify"]
    try:
        proc = exec_runner(
            cmd,
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        return False, f"Falha ao disparar `just verify` em {repo_dir}: {exc}"

    output = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, output.strip()


def run_complexity_sensor(
    repo_dir: Path,
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> tuple[bool, str]:
    """Executa a análise de complexidade cognitiva do complexipy sobre o repositório.

    Args:
        repo_dir: Diretório raiz a ser auditado.
        max_complexity: Limite de complexidade cognitiva tolerado.

    Returns:
        Tupla `(sucesso, feedback_com_sugestoes_ou_ok)`.
    """
    violations = execute_complexity_scan(
        targets=[str(repo_dir)],
        max_complexity=max_complexity,
        root_dir=repo_dir,
    )
    if not violations:
        return True, "Complexidade cognitiva dentro do limite permitido."

    lines: list[str] = [
        f"Detectadas {len(violations)} violações de complexidade cognitiva (> {max_complexity}):"
    ]
    for violation in violations:
        lines.append(
            f"  - {violation.file_path}:{violation.line}:{violation.column} "
            f"[{violation.rule}] {violation.suggestion_text}"
        )
    return False, "\n".join(lines)
