"""Suíte de avaliação por regra da Fase 3 de Python Fluente (decoradores, tipos, operadores)."""

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

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

# As suítes de avaliação exercitam o LLM real do harness. Em runners sem
# endpoint (ex.: test.yml em ubuntu-latest) a suíte se autopula; o gate
# roda nos releases (job fluent-python-eval / preview dispatchado).
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

@pytest.mark.parametrize("spec_filename", PHASE3_SPECS)
def test_phase3_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 3 devem existir e seguir o molde canonico.

    Cada spec deve conter as secoes: Fonte, Regras normativas,
    Anti-padrao -> forma idiomatica, Enforcement e Excecoes,
    alem de indicar a origem [Livro] ou [Politica].
    """
    spec_path = Path("specs/python") / spec_filename
    assert spec_path.is_file(), f"Arquivo nao encontrado: {spec_path}"

    content = spec_path.read_text(encoding="utf-8")
    assert "## 1. Fonte" in content
    assert "## 2. Regras normativas" in content
    assert "## 3. Anti-padrão → forma idiomática" in content
    assert "## 4. Enforcement" in content
    assert "## 5. Exceções" in content
    assert "[Livro]" in content or "[Política]" in content


RULE_CASES: list[tuple[str, str, str]] = [
    (
        'Simple decorators must wrap with @functools.wraps; parameterized decorators must be implemented as a class with __call__ instead of three-level nested functions.',
        'from functools import wraps\n\n\nclass Retry:\n    def __init__(self, times: int) -> None:\n        self.times = times\n\n    def __call__(self, func):\n        @wraps(func)\n        def wrapper(*args, **kwargs):\n            for _ in range(self.times):\n                try:\n                    return func(*args, **kwargs)\n                except OSError:\n                    continue\n        return wrapper\n',
        'def retry(times):\n    def decorator(func):\n        def inner(*args, **kwargs):\n            for _ in range(times):\n                return func(*args, **kwargs)\n        return inner\n    return decorator\n',
    ),
    (
        'Public APIs need complete strict annotations, accepting abstract types like typing.Iterable and returning concrete types.',
        'from collections.abc import Iterable\n\n\ndef total(values: Iterable[float]) -> float:\n    return sum(values)\n',
        'def total(values):\n    return sum(values)\n',
    ),
    (
        'Prefer typing.Protocol over ABCs for decoupled interfaces and never subclass built-in types like list or dict for domain classes.',
        'from typing import Protocol\n\n\nclass SizedLike(Protocol):\n    def __len__(self) -> int: ...\n\n\ndef first_item(collection: SizedLike) -> object:\n    return collection[0]\n',
        'import abc\n\n\nclass Base(abc.ABC):\n    @abc.abstractmethod\n    def run(self): ...\n\n\nclass Stack(list):\n    def push(self, item):\n        self.append(item)\n',
    ),
    (
        'Operator overloading must return new instances and must return NotImplemented for unsupported operand types instead of raising TypeError.',
        "class Vector:\n    def __init__(self, x: float, y: float) -> None:\n        self.x, self.y = x, y\n\n    def __add__(self, other: object) -> 'Vector':\n        if not isinstance(other, Vector):\n            return NotImplemented\n        return Vector(self.x + other.x, self.y + other.y)\n",
        "class Vector:\n    def __init__(self, x, y):\n        self.x, self.y = x, y\n\n    def __add__(self, other):\n        if not isinstance(other, Vector):\n            raise TypeError('unsupported operand')\n        self.x += other.x\n        return self\n",
    ),
]


def build_single_rule_metric(
    model: OpenAIModel, rule: str, name: str
) -> GEval:
    """Cria uma GEval de regra única para avaliar conformidade pontual.

    Multiplas regras em uma só criteria induzem juizes 7B a pontuarem
    ausencias de demonstracao como violacoes; cada metrica aqui carrega
    exatamente UMA norma da fase, com micro-amostra dedicada.

    Args:
        model: Instancia OpenAIModel apontada ao endpoint do harness.
        rule: Texto da regra normativa unica a fiscalizar.
        name: Nome da metrica (visivel no relatorio DeepEval).

    Returns:
        Instancia GEval com threshold 0.9 e params input+output.
    """
    return GEval(
        name=name,
        criteria=(
            "Evaluate the generated Python code strictly against this single "
            "rule; do not penalize the absence of other good practices: " + rule
        ),
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ],
        model=model,
        threshold=0.9,
    )


def build_phase3_metric(model: OpenAIModel) -> GEval:
    """Compat: metrica agregada da fase (mantida p/ testes de estrutura)."""
    return build_single_rule_metric(
        model,
        RULE_CASES[0][0],
        "Fluent Python Phase 3 Rule 1",
    )



def test_phase3_metric_factory_uses_single_rule_and_strict_threshold() -> None:
    """Business Rule: cada metrica de avaliacao carrega UMA regra com
    threshold 0.9 e nome da fase — granularidade e o contrato anti-aleucinacao."""
    metric = build_single_rule_metric(
        build_judge_model(), "Test rule text.", "Fluent Python Phase 3 Rule X"
    )
    assert metric.threshold == 0.9
    criteria = metric.criteria or ""
    assert "Test rule text." in criteria
    assert "Phase 3" in metric.name


def test_phase3_real_llm_approves_and_discriminates_each_rule() -> None:
    """Business Rule: para TODAS as regras da Fase 3 o LLM real do harness
    aprova por maioria a micro-amostra exemplar e pontua estritamente menor
    o anti-padrao da mesma regra — avaliacao granular, verificavel por regra.

    A agregacao por regra acumula falhas e uma unica violacao aborta a
    suite — gate real, sem parcialidade.
    """
    failures: list[str] = []
    for index, (rule, good, bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 3 Rule {index}"
        metric_good = build_single_rule_metric(build_judge_model(), rule, name)
        metric_bad = build_single_rule_metric(build_judge_model(), rule, name + " (anti)")
        case_input = "Implement the snippet described, following the rule."

        score_good, success_good, reason_good = measure_metric_with_majority(
            metric_good, LLMTestCase(input=case_input, actual_output=good)
        )
        score_bad, _, reason_bad = measure_metric_with_majority(
            metric_bad, LLMTestCase(input=case_input, actual_output=bad), votes=1
        )
        if not success_good:
            failures.append(
                f"{name}: exemplar reprovado score={score_good} reason={reason_good}"
            )
        if not score_bad < score_good:
            failures.append(
                f"{name}: anti-padrão não discriminado bom={score_good} "
                f"ruim={score_bad} reason={reason_bad}"
            )
    assert not failures, "\n".join(failures)

