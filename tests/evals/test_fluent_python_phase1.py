"""Suíte de avaliação das especificações da Fase 1 de Python Fluente.

Valida as especificações PY-01 (Modelo de Dados), PY-05 (Classes de Dados)
e PY-06 (Referências e Mutabilidade), além de definir a métrica GEval
para aferir a conformidade semântica de código gerado por LLMs.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

# Garante desativacao de telemetria externa do DeepEval
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


PHASE1_SPECS = [
    "SPEC-PY-01-data-model.md",
    "SPEC-PY-05-data-class-builders.md",
    "SPEC-PY-06-references-and-mutability.md",
]


def build_phase1_metric(model: OpenAIModel) -> GEval:
    """Cria a métrica GEval para avaliar conformidade com a Fase 1.

    Args:
        model: Instância do modelo LLM-as-a-Judge.

    Returns:
        Instância de GEval configurada para avaliar Data Model, Dataclasses
        e Ausência de Padrões Mutáveis Perigosos.
    """
    criteria = (
        "The generated Python code must follow Fluent Python standards: "
        "1. Never use mutable default parameter values (e.g., list=[]); use None. "
        "2. Domain entities must use @dataclass(slots=True, kw_only=True) with "
        "field(default_factory=...) for mutable attributes, or NamedTuple. "
        "3. Classes representing domain objects or collections must implement "
        "appropriate Python Data Model dunders like __repr__ and __len__."
    )
    return GEval(
        name="Fluent Python Phase 1 Compliance",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


@pytest.mark.parametrize("spec_filename", PHASE1_SPECS)
def test_phase1_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 1 devem existir e seguir o molde canônico.

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


def test_phase1_metric_structure() -> None:
    """Business Rule: a métrica da Fase 1 deve ter threshold 0.9 e nome canônico."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase1_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Fluent Python Phase 1 Compliance"


def test_phase1_evaluation_mocked() -> None:
    """Business Rule: código idiomático da Fase 1 é aprovado pela avaliação GEval."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase1_metric(model=dummy_model)

    test_case = LLMTestCase(
        input="Write a customer class with an order list and add_order method.",
        actual_output=(
            "from dataclasses import dataclass, field\n\n"
            "@dataclass(slots=True, kw_only=True)\n"
            "class Customer:\n"
            "    id: int\n"
            "    name: str\n"
            "    orders: list[str] = field(default_factory=list)\n\n"
            "    def add_order(self, order_id: str) -> None:\n"
            "        self.orders.append(order_id)\n"
        ),
    )

    metric.measure = MagicMock()
    metric.score = 1.0
    metric.reason = "Usa @dataclass(slots=True, kw_only=True) e default_factory."
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
