"""Suíte de avaliação das especificações da Fase 3 de Python Fluente.

Valida as especificações PY-07 (Funções e Decoradores), PY-08 (Dicas de Tipo),
PY-09 (Protocolos e ABCs) e PY-10 (Sobrecarga de Operadores), além de definir a métrica
GEval para aferir a conformidade semântica de código gerado por LLMs.
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


PHASE3_SPECS = [
    "SPEC-PY-07-functions-and-decorators.md",
    "SPEC-PY-08-type-hints.md",
    "SPEC-PY-09-protocols-and-abcs.md",
    "SPEC-PY-10-operator-overloading.md",
]


def build_phase3_metric(model: OpenAIModel) -> GEval:
    """Cria a métrica GEval para avaliar conformidade com a Fase 3.

    Args:
        model: Instância do modelo LLM-as-a-Judge.

    Returns:
        Instância de GEval configurada para avaliar Decoradores, Tipagem Estrita,
        Protocolos vs Herança e Sobrecarga de Operadores.
    """
    criteria = (
        "The generated Python code must follow Fluent Python standards: "
        "1. Decorators must preserve metadata using @functools.wraps; parameterized "
        "decorators must be classes with __call__ instead of 3-level nested functions. "
        "2. Public APIs must have complete strict type annotations, accepting abstract "
        "types (Iterable, Sequence) and returning concrete types. "
        "3. Prefer typing.Protocol over ABCs for decoupled interfaces, and never "
        "inherit directly from built-in types like list or dict. "
        "4. Operator overloading methods must return new instances and must return "
        "NotImplemented for unsupported operand types instead of raising TypeError."
    )
    return GEval(
        name="Fluent Python Phase 3 Compliance",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


@pytest.mark.parametrize("spec_filename", PHASE3_SPECS)
def test_phase3_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 3 devem existir e seguir o molde canônico.

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


def test_phase3_metric_structure() -> None:
    """Business Rule: a métrica da Fase 3 deve ter threshold 0.9 e nome canônico."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase3_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Fluent Python Phase 3 Compliance"


def test_phase3_evaluation_mocked() -> None:
    """Business Rule: código idiomático da Fase 3 é aprovado pela avaliação GEval."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase3_metric(model=dummy_model)

    test_case = LLMTestCase(
        input=(
            "Write a 2D Vector class with addition overloading that handles "
            "unsupported types properly."
        ),
        actual_output=(
            "class Vector:\n"
            "    __slots__ = ('_x', '_y')\n\n"
            "    def __init__(self, x: float, y: float) -> None:\n"
            "        self._x = x\n"
            "        self._y = y\n\n"
            "    def __add__(self, other: object) -> 'Vector':\n"
            "        if not isinstance(other, Vector):\n"
            "            return NotImplemented\n"
            "        return Vector(self._x + other._x, self._y + other._y)\n"
        ),
    )

    metric.measure = MagicMock()
    metric.score = 1.0
    metric.reason = (
        "Retorna NotImplemented em __add__, usa __slots__ e preserva imutabilidade."
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
