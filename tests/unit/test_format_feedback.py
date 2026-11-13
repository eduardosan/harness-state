"""Testes do middleware de feedback dos sensores (format_feedback.sh).

Executam o artefato versionado no catalogo de pipeline contra os mesmos
contratos observados pelo agentic-flywheel.
"""

import subprocess
from pathlib import Path

import pytest

SENSOR = "src/harness_state/catalog/pipeline/sensors/format_feedback.sh"


@pytest.fixture()
def repo_root() -> Path:
    """Retorna a raiz do repositorio harness-state.

    Returns:
        Caminho absoluto da raiz do repositorio.
    """
    return Path(__file__).resolve().parents[2]


def run_sensor(repo_root: Path, tool: str, shell_cmd: str):
    """Executa o wrapper de feedback sobre um comando shell.

    Args:
        repo_root: Raiz do repositorio do flywheel.
        tool: Nome da ferramenta repassado ao wrapper.
        shell_cmd: Comando shell cujo stdout/stderr sera interceptado.

    Returns:
        O ``CompletedProcess`` do wrapper.
    """
    return subprocess.run(
        [str(repo_root / SENSOR), tool, "--", "bash", "-c", shell_cmd],
        capture_output=True,
        text=True,
        check=False,
    )


def test_success_passes_through_silently(repo_root: Path) -> None:
    """Business Rule: sensor aprovado nao polui o contexto do agente.

    Quando o comando termina com codigo 0, o wrapper repassa o codigo 0 e nao
    emite o bloco ``[HARNESS SENSOR FEEDBACK]``, preservando tokens do modelo.
    """
    result = run_sensor(repo_root, "lint", "echo all good")
    assert result.returncode == 0
    assert "HARNESS SENSOR FEEDBACK" not in result.stdout


def test_failure_keeps_exit_code_and_marks_rejected(repo_root: Path) -> None:
    """Business Rule: falha do sensor reprova o diff e preserva o exit code.

    O Aider decide se deve tentar autocorrecao pelo codigo de saida; por isso o
    wrapper devolve o mesmo codigo nao-zero do comando original e marca o
    status como REJECTED.
    """
    result = run_sensor(repo_root, "lint", "echo boom; exit 3")
    assert result.returncode == 3
    assert "[HARNESS SENSOR FEEDBACK]" in result.stdout
    assert "STATUS: REJECTED" in result.stdout


def test_ruff_violation_is_prescriptive(repo_root: Path) -> None:
    """Business Rule: violacao de lint vira instrucao prescritiva localizada.

    Saida do ruff no formato ``arquivo:linha:coluna: CODIGO mensagem`` deve ser
    convertida em tipo, alvo (arquivo:linha) e regra, mais acao requerida.
    """
    cmd = "echo 'src/app.py:14:5: F401 `os` imported but unused'; exit 1"
    result = run_sensor(repo_root, "lint", cmd)
    assert "VIOLATION TYPE: Lint" in result.stdout
    assert "TARGET: src/app.py:14" in result.stdout
    assert "RULE: F401" in result.stdout
    assert "ACTION REQUIRED:" in result.stdout


def test_architecture_violation_is_classified(repo_root: Path) -> None:
    """Business Rule: quebra de fronteira arquitetural e tipo proprio.

    Saida do import-linter com contrato ``BROKEN`` deve virar violacao do tipo
    ``Architectural Boundary`` apontando para o guia de arquitetura.
    """
    cmd = (
        "echo 'Controllers cannot import drivers BROKEN';"
        "echo '- src.controllers.order -> src.db.driver (l.14)'; exit 1"
    )
    result = run_sensor(repo_root, "arch", cmd)
    assert "VIOLATION TYPE: Architectural Boundary" in result.stdout
    assert "architecture.md" in result.stdout
    assert "(l.14)" in result.stdout


def test_pytest_failure_is_classified(repo_root: Path) -> None:
    """Business Rule: falha de teste informa o teste e o motivo.

    Linhas ``FAILED caminho::teste - motivo`` do pytest viram violacao do tipo
    ``Test Failure`` com alvo e motivo, sem despejar o log completo.
    """
    cmd = "echo 'FAILED tests/unit/test_x.py::test_a - assert 1 == 2'; exit 1"
    result = run_sensor(repo_root, "test", cmd)
    assert "VIOLATION TYPE: Test Failure" in result.stdout
    assert "TARGET: tests/unit/test_x.py::test_a" in result.stdout
    assert "assert 1 == 2" in result.stdout


def test_extra_violations_are_counted_not_dumped(repo_root: Path) -> None:
    """Business Rule: feedback curto para caber no contexto do modelo 7B.

    Apenas a primeira violacao e detalhada; as demais aparecem como contagem,
    evitando estourar o orcamento de tokens do agente.
    """
    cmd = (
        "echo 'a.py:1:1: F401 x'; echo 'b.py:2:1: F401 y';"
        "echo 'c.py:3:1: E501 z'; exit 1"
    )
    result = run_sensor(repo_root, "lint", cmd)
    assert "TARGET: a.py:1" in result.stdout
    assert "b.py" not in result.stdout
    assert "ADDITIONAL VIOLATIONS: 2" in result.stdout


def test_unclassified_failure_shows_tail_only(repo_root: Path) -> None:
    """Business Rule: falha desconhecida nunca e silenciada.

    Se nenhum padrao for reconhecido, o wrapper devolve ``Unclassified`` com o
    final da saida bruta limitado a 20 linhas.
    """
    cmd = "for i in $(seq 1 50); do echo line$i; done; exit 1"
    result = run_sensor(repo_root, "lint", cmd)
    assert "VIOLATION TYPE: Unclassified" in result.stdout
    assert "line50" in result.stdout
    assert "line1\n" not in result.stdout


def test_complexipy_violation_is_classified_as_cognitive_complexity(
    repo_root: Path,
) -> None:
    """Business Rule: sugestão do complexipy vira feedback de Cognitive Complexity.

    Saída emitida pelo ``complexity_sensor.py`` contendo ``Complexipy suggestion``
    deve ser classificada como ``Cognitive Complexity`` e preservar a sugestão de
    refatoração na regra enviada como input ao agente LLM.
    """
    cmd = (
        "echo \"src/app.py:42:9: C001 Function 'process' has cognitive complexity "
        "21 (max allowed: 15). Complexipy suggestion [C001]: Flatten nested "
        "condition block with guard clauses (lines 42-60, est. -4 -> 17). "
        'Help: Invert the outer condition and exit early."; exit 1'
    )
    result = run_sensor(repo_root, "lint", cmd)
    assert result.returncode == 1
    assert "VIOLATION TYPE: Cognitive Complexity" in result.stdout
    assert "TARGET: src/app.py:42" in result.stdout
    assert "Complexipy suggestion [C001]: Flatten nested condition" in result.stdout
    assert "SUGGESTED CORRECTION: Apply the complexipy refactoring" in result.stdout


def test_just_command_ignores_extra_file_arguments(repo_root: Path) -> None:
    """Business Rule: Aider repassa arquivos para just; argumentos extras descartados.

    Quando o Aider chama ``format_feedback.sh lint -- just lint arquivo.py``, o
    wrapper deve invocar apenas ``just lint``, impedindo que o just interprete o
    arquivo como uma receita inexistente.
    """
    sensor_path = repo_root / SENSOR
    # Se just nao existir localmente, o teste valida que nao tenta rodar o
    # arquivo como receita
    result = subprocess.run(
        [str(sensor_path), "lint", "--", "just", "lint", "extra_file.py"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "extra_file.py" not in result.stdout
