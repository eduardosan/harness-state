"""Suíte de avaliação por regra da Fase 2 de Python Fluente (sequências, dicts, I/O)."""

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


PHASE2_SPECS = [
    "SPEC-PY-02-sequences-and-comprehensions.md",
    "SPEC-PY-03-dicts-and-sets.md",
    "SPEC-PY-04-text-and-bytes.md",
]

@pytest.mark.parametrize("spec_filename", PHASE2_SPECS)
def test_phase2_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 2 devem existir e seguir o molde canonico.

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
        'Prefer list comprehensions or generator expressions over map/filter combined with lambda; comprehensions must be free of side effects.',
        "names = [row.split(',')[0] for row in rows if row.strip()]\n",
        "names = list(map(lambda r: r.split(',')[0], filter(lambda r: r, rows)))\n",
    ),
    (
        'Use modern dict handling (setdefault/defaultdict/UserDict) and never subclass built-in dict directly.',
        'from collections import defaultdict\n\ncounts: dict[str, int] = defaultdict(int)\nfor row in rows:\n    counts[row] += 1\n',
        'class CountedDict(dict):\n    def bump(self, key):\n        self[key] = self.get(key, 0) + 1\n',
    ),
    (
        'Always pass an explicit encoding when opening text files (Unicode sandwich).',
        "from pathlib import Path\n\ndef read_lines(path: Path) -> list[str]:\n    with path.open(encoding='utf-8') as handle:\n        return [line.strip() for line in handle]\n",
        'def read_lines(path):\n    return open(path).read().splitlines()\n',
    ),
    (
        'Prefer generator functions over loading entire large collections in memory when streaming file lines.',
        "def rows(path):\n    with path.open(encoding='utf-8') as handle:\n        for line in handle:\n            if line.strip():\n                yield line.strip()\n",
        "def rows(path):\n    data = open(path, encoding='utf-8').read()\n    return data.splitlines()\n",
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
            (
                "1. Read the SINGLE rule stated in the criteria; it is the "
                "only subject of this evaluation."
            ),
            (
                "2. Check whether the snippet demonstrably complies with "
                "that one rule as written."
            ),
            (
                "3. Ignore the absence of any other best practice, other "
                "operator methods, other validated attributes, other "
                "metaprogramming hierarchy levels or defensive checks not "
                "required by the rule."
            ),
            (
                "4. Score 1.0 when the rule is followed; deduct points ONLY "
                "for a direct violation of that same rule."
            ),
        ],
        evaluation_params=[
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ],
        model=model,
        threshold=0.9,
    )


def build_phase2_metric(model: OpenAIModel) -> GEval:
    """Compat: metrica agregada da fase (mantida p/ testes de estrutura)."""
    return build_single_rule_metric(
        model,
        RULE_CASES[0][0],
        "Fluent Python Phase 2 Rule 1",
    )



def test_phase2_metric_factory_uses_single_rule_and_strict_threshold() -> None:
    """Business Rule: cada metrica de avaliacao carrega UMA regra com
    threshold 0.9 e nome da fase — granularidade e o contrato anti-aleucinacao."""
    metric = build_single_rule_metric(
        build_judge_model(), "Test rule text.", "Fluent Python Phase 2 Rule X"
    )
    assert metric.threshold == 0.9
    criteria = metric.criteria or ""
    assert "Test rule text." in criteria
    assert "Phase 2" in metric.name


def test_phase2_real_llm_approves_and_discriminates_each_rule() -> None:
    """Business Rule: para TODAS as regras da Fase 2 o LLM real do harness
    aprova por maioria a micro-amostra exemplar e pontua estritamente menor
    o anti-padrao da mesma regra — avaliacao granular, verificavel por regra.

    A agregacao por regra acumula falhas e uma unica violacao aborta a
    suite — gate real, sem parcialidade.
    """
    failures: list[str] = []
    for index, (rule, good, bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 2 Rule {index}"
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

