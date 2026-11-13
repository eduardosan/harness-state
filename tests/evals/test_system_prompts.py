"""Suíte de avaliação de prompts de sistema com DeepEval (Spec/Prompt CI)."""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

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


def test_python_guidelines_evaluation_mocked() -> None:
    """Business Rule: O avaliador DeepEval deve aprovar codigo conforme as regras."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_guidelines_metric(model=dummy_model)

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

    metric.measure = MagicMock()
    metric.score = 1.0
    metric.reason = "Codigo plano, sem funcoes ou try-excepts aninhados."
    metric.is_successful = MagicMock(return_value=True)

    metric.measure(test_case)
    assert metric.is_successful() is True
    prompt_score = metric.score
    prompt_threshold = metric.threshold
    assert (
        prompt_score is not None
        and prompt_threshold is not None
        and prompt_score >= prompt_threshold
    )


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
    """Business Rule: Avaliacao deve reprovar codigo que mascare falha de binario."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_rca_metric(model=dummy_model)
    test_case = LLMTestCase(
        input="Fix missing gcloud CLI binary in CI runner during log fetching.",
        actual_output=("try:\n    subprocess.run(cmd)\nexcept OSError:\n    pass\n"),
    )
    metric.measure = MagicMock()
    metric.score = 0.0
    metric.reason = "Violation: masked OSError instead of resolving binary."
    metric.is_successful = MagicMock(return_value=False)

    metric.measure(test_case)
    assert metric.is_successful() is False
    low_score = metric.score
    low_threshold = metric.threshold
    assert (
        low_score is not None
        and low_threshold is not None
        and low_score < low_threshold
    )


def test_spec_guidelines_file_exists_and_valid() -> None:
    """Business Rule: Diretrizes de spec devem conter regras de viabilidade."""
    spec_guidelines_path = Path("specs/prompts/spec_guidelines.md")
    assert spec_guidelines_path.is_file()
    content = spec_guidelines_path.read_text(encoding="utf-8")
    assert "Viabilidade Técnica e Compatibilidade de SDKs" in content
    assert "Sem Alucinação de Paridade de Recursos" in content
    assert "Protocolo de Spike (Onda 0)" in content
    assert "Plano de Fallback Arquitetural" in content
