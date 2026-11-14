"""Suíte de avaliação das especificações da Fase 1 de Python Fluente.

Valida as especificações PY-01 (Modelo de Dados), PY-05 (Classes de Dados)
e PY-06 (Referências e Mutabilidade), além de definir a métrica GEval
para aferir a conformidade semântica de código gerado por LLMs.
"""

import os
from pathlib import Path

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from harness_state.judge import build_judge_model, measure_metric_with_majority

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


IDIOMATIC_SAMPLE = """from dataclasses import dataclass, field


@dataclass(slots=True, kw_only=True)
class Customer:
    id: int
    name: str
    orders: list[str] = field(default_factory=list)
    notes: list[str] | None = None

    def add_order(self, order_id: str) -> None:
        self.orders.append(order_id)

    def __len__(self) -> int:
        return len(self.orders)

    def __repr__(self) -> str:
        return f"Customer(id={self.id}, orders={len(self.orders)})"


def collect(items: list[str] | None = None) -> list[str]:
    return list(items) if items is not None else []"""

ANTI_PATTERN_SAMPLE = """class Order(dict):
    def __init__(self, items=[], total=0):
        self.items = items
        self.total = total"""

def test_phase1_real_llm_approves_idiomatic_sample() -> None:
    """Business Rule: o LLM do harness avalia de verdade o código-exemplar da
    Fase 1 (todas as regras da métrica presentes) e o aprova por maioria."""
    metric = build_phase1_metric(model=build_judge_model())
    case = LLMTestCase(
        input="Create a Customer dataclass with an orders collection, a safe add_order API, no mutable default arguments, and a length dunder.",
        actual_output=IDIOMATIC_SAMPLE,
    )

    score, success, reason = measure_metric_with_majority(metric, case)
    assert success, f"juiz rejeitou código-exemplar: score={score} reason={reason}"
    assert score >= int((metric.threshold or 0.9) * 100)
    assert reason


def test_phase1_real_llm_discriminates_anti_pattern() -> None:
    """Business Rule: o mesmo juiz dá score estritamente menor ao anti-padrão
    da Fase 1 — a avaliação exercita o LLM e prova discriminação real."""
    case_input = "Create a Customer dataclass with an orders collection, a safe add_order API, no mutable default arguments, and a length dunder."
    metric_good = build_phase1_metric(model=build_judge_model())
    metric_bad = build_phase1_metric(model=build_judge_model())

    score_good, _, _ = measure_metric_with_majority(
        metric_good, LLMTestCase(input=case_input, actual_output=IDIOMATIC_SAMPLE)
    )
    score_bad, _, _ = measure_metric_with_majority(
        metric_bad, LLMTestCase(input=case_input, actual_output=ANTI_PATTERN_SAMPLE)
    )
    assert score_bad < score_good, (
        f"juiz não discriminou o anti-padrão: bom={score_good} ruim={score_bad}"
    )
