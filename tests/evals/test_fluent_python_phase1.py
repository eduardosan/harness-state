"""Suíte de avaliação por regra da Fase 1 de Python Fluente (PY-01/05/06)."""

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


PHASE1_SPECS = [
    "SPEC-PY-01-data-model.md",
    "SPEC-PY-05-data-class-builders.md",
    "SPEC-PY-06-references-and-mutability.md",
]

@pytest.mark.parametrize("spec_filename", PHASE1_SPECS)
def test_phase1_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 1 devem existir e seguir o molde canonico.

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
        'Never use mutable default parameter values (e.g., def f(items=[])); use None and build the list inside the body.',
        'def collect(items: list[str] | None = None) -> list[str]:\n    return list(items) if items is not None else []\n',
        "def collect(items: list[str] = []) -> list[str]:\n    items.append('x')\n    return items\n",
    ),
    (
        'Domain entities must use @dataclass(slots=True, kw_only=True) with field(default_factory=...) for mutable attributes (or NamedTuple), instead of hand-rolled dict subclasses.',
        'from dataclasses import dataclass, field\n\n\n@dataclass(slots=True, kw_only=True)\nclass Order:\n    id: int\n    items: list[str] = field(default_factory=list)\n',
        "class Order(dict):\n    def __init__(self, id, items=None):\n        self['items'] = items or []\n",
    ),
    (
        'Classes representing collections must implement Python Data Model dunders (e.g., __len__, __repr__) instead of Java-style accessor methods.',
        'class Cart:\n    def __init__(self) -> None:\n        self._items: list[str] = []\n\n    def __len__(self) -> int:\n        return len(self._items)\n\n    def __repr__(self) -> str:\n        return f"Cart({len(self)})"\n',
        'class Cart:\n    def __init__(self) -> None:\n        self._items: list[str] = []\n\n    def get_size(self):\n        return len(self._items)\n',
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
        evaluation_steps=[
            "1. Read the SINGLE rule stated in the criteria; it is the only "
            "subject of this evaluation.",
            "2. Check whether the snippet demonstrably complies with that one "
            "rule as written.",
            "3. Ignore the absence of any other best practice, other "
            "operator methods, other validated attributes, other "
            "metaprogramming hierarchy levels or defensive checks not "
            "required by the rule.",
            "4. Score 1.0 when the rule is followed; deduct points ONLY for "
            "a direct violation of that same rule.",
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ],
        model=model,
        threshold=0.9,
    )


def build_phase1_metric(model: OpenAIModel) -> GEval:
    """Compat: metrica agregada da fase (mantida p/ testes de estrutura)."""
    return build_single_rule_metric(
        model,
        RULE_CASES[0][0],
        "Fluent Python Phase 1 Rule 1",
    )



def test_phase1_metric_factory_uses_single_rule_and_strict_threshold() -> None:
    """Business Rule: cada metrica de avaliacao carrega UMA regra com
    threshold 0.9 e nome da fase — granularidade e o contrato anti-aleucinacao."""
    metric = build_single_rule_metric(
        build_judge_model(), "Test rule text.", "Fluent Python Phase 1 Rule X"
    )
    assert metric.threshold == 0.9
    criteria = metric.criteria or ""
    assert "Test rule text." in criteria
    assert "Phase 1" in metric.name


def test_phase1_real_llm_approves_and_discriminates_each_rule() -> None:
    """Business Rule: para TODAS as regras da Fase 1 o LLM real do harness
    aprova por maioria a micro-amostra exemplar e pontua estritamente menor
    o anti-padrao da mesma regra — avaliacao granular, verificavel por regra.

    A agregacao por regra acumula falhas e uma unica violacao aborta a
    suite — gate real, sem parcialidade.
    """
    failures: list[str] = []
    for index, (rule, good, bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 1 Rule {index}"
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

