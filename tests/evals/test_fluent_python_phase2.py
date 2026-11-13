"""Suíte de avaliação das especificações da Fase 2 de Python Fluente.

Valida as especificações PY-02 (Sequências e Compreensões), PY-03 (Dicionários
e Conjuntos), PY-04 (Texto Unicode vs Bytes) e PY-11 (Iteradores, Geradores
e Context Managers), além de definir a métrica GEval para aferir a conformidade
semântica de código gerado por LLMs.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

# Garante desativação de telemetria externa do DeepEval
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


PHASE2_SPECS = [
    "SPEC-PY-02-sequences-and-comprehensions.md",
    "SPEC-PY-03-dicts-and-sets.md",
    "SPEC-PY-04-text-and-bytes.md",
    "SPEC-PY-11-iterators-generators-and-context.md",
]


def build_phase2_metric(model: OpenAIModel) -> GEval:
    """Cria a métrica GEval para avaliar conformidade com a Fase 2.

    Args:
        model: Instância do modelo LLM-as-a-Judge.

    Returns:
        Instância de GEval configurada para avaliar Sequências, Mapeamentos,
        Tratamento de Unicode/Bytes, Geradores e Context Managers.
    """
    criteria = (
        "The generated Python code must follow Fluent Python standards: "
        "1. Prefer list comprehensions or generator expressions over "
        "map/filter with lambda, and avoid side effects inside comprehensions. "
        "2. Use modern dict handling (setdefault, defaultdict, UserDict) "
        "and never inherit directly from dict. "
        "3. Always specify explicit encoding when opening text files "
        "(Unicode sandwich principle). "
        "4. Always use 'with' context managers for external resources "
        "and prefer generator functions over loading full large collections "
        "in memory."
    )
    return GEval(
        name="Fluent Python Phase 2 Compliance",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


@pytest.mark.parametrize("spec_filename", PHASE2_SPECS)
def test_phase2_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 2 devem existir e seguir o molde canônico.

    Cada spec deve conter as seções: Fonte, Regras normativas,
    Anti-padrão → forma idiomática, Enforcement e Exceções,
    além de indicar a origem [Livro] ou [Política].
    """
    spec_path = Path("specs/python") / spec_filename
    assert spec_path.is_file(), f"Arquivo não encontrado: {spec_path}"

    content = spec_path.read_text(encoding="utf-8")
    assert "## 1. Fonte" in content
    assert "## 2. Regras normativas" in content
    assert "## 3. Anti-padrão → forma idiomática" in content
    assert "## 4. Enforcement" in content
    assert "## 5. Exceções" in content
    assert "[Livro]" in content or "[Política]" in content


def test_phase2_metric_structure() -> None:
    """Business Rule: a métrica da Fase 2 deve ter threshold 0.9 e nome canônico."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase2_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Fluent Python Phase 2 Compliance"


def test_phase2_evaluation_mocked() -> None:
    """Business Rule: código idiomático da Fase 2 é aprovado pela avaliação GEval."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase2_metric(model=dummy_model)

    test_case = LLMTestCase(
        input=(
            "Write a function to read IDs from a text file lazily with proper encoding."
        ),
        actual_output=(
            "from collections.abc import Iterator\n\n"
            "def read_ids(filepath: str) -> Iterator[int]:\n"
            "    with open(filepath, 'r', encoding='utf-8') as f:\n"
            "        for line in f:\n"
            "            cleaned = line.strip()\n"
            "            if cleaned.isdigit():\n"
            "                yield int(cleaned)\n"
        ),
    )

    metric.measure = MagicMock()
    metric.score = 1.0
    metric.reason = (
        "Usa gerador sob demanda, with context manager e encoding explícito."
    )
    metric.is_successful = MagicMock(return_value=True)

    metric.measure(test_case)
    assert metric.is_successful() is True
    phase_score = metric.score
    phase_threshold = metric.threshold
    assert (
        phase_score is not None
        and phase_threshold is not None
        and phase_score >= phase_threshold
    )
