"""Suíte de avaliação por regra da Fase 2 de Python Fluente (sequências, dicts, I/O)."""

import os
from pathlib import Path

import pytest
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from harness_state.judge import (
    aggregate_functional_votes,
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
            "Assess the code against exactly ONE guideline, stated below. "
            "Guideline: " + rule +
            " Judge only compliance with this guideline. The size or "
            "structure of the code is irrelevant: a snippet may contain "
            "any number of functions and classes."
        ),
        evaluation_steps=[
            "1. Identify the one guideline stated in the criteria.",
            "2. Decide whether the code follows or violates that guideline.",
            (
                "3. Do not penalize the absence of anything unrelated to "
                "the guideline; never require the snippet to be a "
                "single function."
            ),
            (
                "4. Score 1.0 if the guideline is followed; deduct points "
                "only for a direct violation of it."
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


def test_phase2_real_llm_approves_idiomatic_snippets() -> None:
    """Business Rule: sanity calibração — o LLM do harness não pode reprovar o
    conjunto de micro-exemplares idiomáticos das regras da Fase 2."""
    failures: list[str] = []
    for index, (rule, good, _bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 2 Rule {index}"
        metric = build_single_rule_metric(build_judge_model(), rule, name)
        score, success, reason = measure_metric_with_majority(
            metric,
            LLMTestCase(
                input="Implement the snippet described, following the rule.",
                actual_output=good,
            ),
        )
        if not success:
            failures.append(f"{name}: score={score} reason={reason}")
    assert not failures, "exemplares reprovados:\n" + "\n".join(failures)


def test_phase2_real_llm_forced_choice_discriminates_each_rule() -> None:
    """Business Rule: para TODAS as regras da Fase 2 o juiz identifica o
    segmento idiomático em escolha forçada A/B — discriminação confiável,
    dado que o score absoluto de um 7B mostrou-se instável nos previews
    (ora severo, ora carimbo total)."""
    failures: list[str] = []
    for index, (rule, good, bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 2 Rule {index}"
        if index % 2 == 1:
            choice = "A"
            snippets = f"Segment A:\n{good}\n\nSegment B:\n{bad}\n"
        else:
            choice = "B"
            snippets = f"Segment A:\n{bad}\n\nSegment B:\n{good}\n"
        prompt = (
            "Guideline: " + rule + "\n\n" + snippets + "\n"
            "Exactly one segment follows the guideline and exactly one "
            "violates it. Respond with only the letter of the compliant "
            "segment."
        )
        votes: list[tuple[int, bool, str]] = []
        for _ in range(3):
            generated = build_judge_model().generate(prompt)
            raw = str(generated[0]) if isinstance(generated, tuple) else str(generated)
            first_token = raw.strip().upper()[:1]
            ok = first_token == choice
            votes.append((100 if ok else 0, ok, raw.strip()[:60]))
        score, success, reason = aggregate_functional_votes(votes)
        if not success:
            failures.append(
                f"{name}: esperado={choice} votos={reason} "
                f"(score={score})"
            )
    assert not failures, "escolha forçada falhou:\n" + "\n".join(failures)
