"""Suíte de avaliação das especificações da Fase 3 de Python Fluente.

Valida as especificações PY-07 (Funções e Decoradores), PY-08 (Dicas de Tipo),
PY-09 (Protocolos e ABCs) e PY-10 (Sobrecarga de Operadores), além de definir a métrica
GEval para aferir a conformidade semântica de código gerado por LLMs.
"""

import os
from pathlib import Path

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from harness_state.judge import build_judge_model, measure_metric_with_majority

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


IDIOMATIC_SAMPLE = """from collections.abc import Iterable
from functools import wraps
from typing import Protocol


class SizedLike(Protocol):
    def __len__(self) -> int: ...


class Vector:
    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def __add__(self, other: object) -> "Vector":
        if not isinstance(other, Vector):
            return NotImplemented
        return Vector(self.x + other.x, self.y + other.y)


def timed(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return wrapper


class Retry:
    def __init__(self, times: int) -> None:
        self.times = times

    def __call__(self, func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for _ in range(self.times):
                return func(*args, **kwargs)

        return wrapper


def total(values: Iterable[float]) -> float:
    return sum(values)"""

ANTI_PATTERN_SAMPLE = """def retry(times):
    def decorator(func):
        def inner(*args, **kwargs):
            for _ in range(times):
                return func(*args, **kwargs)
        return inner
    return decorator


class Stack(list):
    def push(self, item):
        self.append(item)

    def __add__(self, other):
        raise TypeError("unsupported")"""

def test_phase3_real_llm_approves_idiomatic_sample() -> None:
    """Business Rule: o LLM do harness avalia de verdade o código-exemplar da
    Fase 3 (todas as regras da métrica presentes) e o aprova por maioria."""
    metric = build_phase3_metric(model=build_judge_model())
    case = LLMTestCase(
        input="Implement vector addition, a timing decorator that preserves metadata, a parameterized retry decorator and a decoupled sized protocol with strict annotations.",
        actual_output=IDIOMATIC_SAMPLE,
    )

    score, success, reason = measure_metric_with_majority(metric, case)
    assert success, f"juiz rejeitou código-exemplar: score={score} reason={reason}"
    assert score >= int((metric.threshold or 0.9) * 100)
    assert reason


def test_phase3_real_llm_discriminates_anti_pattern() -> None:
    """Business Rule: o mesmo juiz dá score estritamente menor ao anti-padrão
    da Fase 3 — a avaliação exercita o LLM e prova discriminação real."""
    case_input = "Implement vector addition, a timing decorator that preserves metadata, a parameterized retry decorator and a decoupled sized protocol with strict annotations."
    metric_good = build_phase3_metric(model=build_judge_model())
    metric_bad = build_phase3_metric(model=build_judge_model())

    score_good, _, _ = measure_metric_with_majority(
        metric_good, LLMTestCase(input=case_input, actual_output=IDIOMATIC_SAMPLE)
    )
    score_bad, _, _ = measure_metric_with_majority(
        metric_bad, LLMTestCase(input=case_input, actual_output=ANTI_PATTERN_SAMPLE)
    )
    assert score_bad < score_good, (
        f"juiz não discriminou o anti-padrão: bom={score_good} ruim={score_bad}"
    )
