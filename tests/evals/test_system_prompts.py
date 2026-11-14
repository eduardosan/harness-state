"""Suíte de avaliação de prompts de sistema com DeepEval (Spec/Prompt CI)."""

import os
from pathlib import Path

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from harness_state.judge import (
    build_judge_model,
    measure_metric_with_majority,
)

# Garante que telemetria externa do DeepEval permanece desativada
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

# As suítes de avaliação exigem um endpoint LLM configurado. Em runners sem
# LLM (ex.: `test.yml` em ubuntu-latest) a suíte inteira é pulada com aviso,
# mantendo o gate real apenas no `spec-ci.yml` (self-hosted, vars LLM_*).
pytestmark = pytest.mark.skipif(
    not (
        os.environ.get("OPENAI_BASE_URL", "")
        or os.environ.get("LLM_BASE_URL", "")
        or os.environ.get("LLM_INTERNAL_BASE_URL", "")
    ),
    reason="sem endpoint LLM configurado (OPENAI_BASE_URL/LLM_*_BASE_URL)",
)



def build_guidelines_metric(model: OpenAIModel) -> GEval:
    """Cria a metrica GEval para avaliar conformidade de diretrizes Python.

    Args:
        model: Modelo instanciado para avaliar o output.

    Returns:
        Instancia de GEval com o criterio de proibicao de funcoes e try aninhados.
    """
    criteria = (
        "The generated Python code must strictly follow engineering rules: "
        "it must not contain nested functions, must not contain nested "
        "try-except blocks, and must be clean and PEP 8 compliant."
    )
    return GEval(
        name="Python Guidelines Compliance",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


def test_python_guidelines_prompt_metric_structure() -> None:
    """Business Rule: A metrica de diretrizes deve avaliar sem aninhamentos."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_guidelines_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Python Guidelines Compliance"


def test_python_guidelines_file_exists_and_valid() -> None:
    """Business Rule: O arquivo de diretrizes Python deve existir e conter as regras."""
    spec_path = Path("specs/prompts/python_guidelines.md")
    assert spec_path.is_file()
    content = spec_path.read_text(encoding="utf-8")
    assert "Sem Funções Aninhadas" in content
    assert "Sem Try-Excepts Aninhados" in content
    assert "Business Rule:" in content


def test_python_guidelines_real_llm_approves_compliant_code() -> None:
    """Business Rule: o LLM do harness avalia de fato código conforme as
    diretrizes Python (sem aninhamentos, PEP 8) e aprova por maioria de votos."""
    metric = build_guidelines_metric(model=build_judge_model())
    test_case = LLMTestCase(
        input=(
            "Write a python function that connects to a database "
            "and handles exceptions."
        ),
        actual_output=(
            "import sqlite3\n\n"
            "def connect_db(db_path: str):\n"
            "    try:\n"
            "        return sqlite3.connect(db_path)\n"
            "    except sqlite3.Error as exc:\n"
            "        raise RuntimeError(f'DB error: {exc}') from exc\n"
        ),
    )

    score, success, reason = measure_metric_with_majority(metric, test_case)
    assert success, f"juiz rejeitou código conforme: score={score} reason={reason}"
    assert score >= int((metric.threshold or 0.9) * 100)
    assert reason


def build_rca_metric(model: OpenAIModel) -> GEval:
    """Cria a metrica GEval para avaliar investigacao de causa raiz e anti-mascaramento.

    Args:
        model: Modelo instanciado para atuar como juiz.

    Returns:
        Instancia de GEval configurada para fiscalizar RCA e 5 Whys.
    """
    criteria = (
        "Evaluate whether the solution addresses the root cause of the problem "
        "rather than masking errors with superficial try-except blocks, silent "
        "suppressions, or unneeded test mocks. Deduct all points if errors are masked."
    )
    return GEval(
        name="Root Cause Analysis and Exception Masking Prevention",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


def test_rca_guidelines_file_exists_and_valid() -> None:
    """Business Rule: Diretrizes de RCA devem conter Ishikawa e 5 Whys."""
    spec_path = Path("specs/prompts/rca_guidelines.md")
    assert spec_path.is_file()
    content = spec_path.read_text(encoding="utf-8")
    assert "Proibição de Mascaramento" in content
    assert "Diagrama de Ishikawa" in content
    assert "5 Porquês" in content


def test_rca_metric_structure() -> None:
    """Business Rule: A metrica de RCA deve ter limiar estrito de 0.9."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_rca_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Root Cause Analysis and Exception Masking Prevention"


def test_rca_evaluation_rejects_exception_masking() -> None:
    """Business Rule: o LLM real reprova por maioria a máscara de falha de
    binário com `except: pass` — a métrica de RCA discrimina, não carimba."""
    metric = build_rca_metric(model=build_judge_model())
    test_case = LLMTestCase(
        input="Fix missing gcloud CLI binary in CI runner during log fetching.",
        actual_output=(
            "try:\n    subprocess.run(cmd)\nexcept OSError:\n    pass\n"
        ),
    )

    score, success, reason = measure_metric_with_majority(metric, test_case)
    assert not success, f"juiz aprovou mascaramento: score={score} reason={reason}"
    assert score < int((metric.threshold or 0.9) * 100)
