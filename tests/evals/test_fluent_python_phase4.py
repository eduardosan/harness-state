"""Suíte de avaliação por regra da Fase 4 de Python Fluente (async, concorrência, propriedades, meta)."""

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


PHASE4_SPECS = [
    "SPEC-PY-11-iterators-generators-and-context.md",
    "SPEC-PY-12-concurrency-and-async.md",
    "SPEC-PY-13-dynamic-attributes-and-metaprogramming.md",
]

@pytest.mark.parametrize("spec_filename", PHASE4_SPECS)
def test_phase4_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 4 devem existir e seguir o molde canonico.

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
        'In async code never block the event loop (no time.sleep or blocking file I/O in coroutines); use asyncio.TaskGroup and explicit asyncio.timeout for fan-out.',
        'import asyncio\n\n\nasync def fetch_all(urls):\n    async with asyncio.timeout(10), asyncio.TaskGroup() as tg:\n        tasks = [tg.create_task(fetch(u)) for u in urls]\n    return [t.result() for t in tasks]\n',
        'import time\n\n\nasync def fetch_all(urls):\n    return [fetch(u) and time.sleep(0.5) for u in urls]\n',
    ),
    (
        'Choose the concurrency model by the bottleneck: ProcessPoolExecutor for CPU-bound work, asyncio/threads for I/O-bound work.',
        'from concurrent.futures import ProcessPoolExecutor\n\n\ndef hash_all(paths):\n    with ProcessPoolExecutor(max_workers=4) as pool:\n        return list(pool.map(hash_file, paths))\n',
        'from concurrent.futures import ThreadPoolExecutor\n\n\ndef hash_all(paths):\n    with ThreadPoolExecutor(max_workers=4) as pool:\n        return list(pool.map(hash_file, paths))\n',
    ),
    (
        'Repeated attribute validation must use a reusable descriptor with __set_name__ plus @property, not procedural get_/set_ pairs.',
        "class Positive:\n    def __set_name__(self, owner, name):\n        self.public = name\n        self.private = f'_{name}'\n\n    def __get__(self, obj, objtype=None):\n        return getattr(obj, self.private, None)\n\n    def __set__(self, obj, value):\n        if value <= 0:\n            raise ValueError('must be positive')\n        setattr(obj, self.private, value)\n\n\nclass Connection:\n    port = Positive()\n\n    def __init__(self, port: int) -> None:\n        self.port = port\n\n    @property\n    def label(self) -> str:\n        return f'connection:{self.port}'\n",
        'class Connection:\n    def get_port(self):\n        return self._port\n\n    def set_port(self, value):\n        self._port = value\n',
    ),
    (
        'Follow the metaprogramming hierarchy (class decorator -> __init_subclass__ -> metaclass), preferring __init_subclass__ over a custom metaclass for simple registration.',
        "class Plugin:\n    registry: dict[str, type] = {}\n\n    def __init_subclass__(cls, slug: str, **kwargs) -> None:\n        super().__init_subclass__(**kwargs)\n        Plugin.registry[slug] = cls\n\n\nclass CsvExport(Plugin, slug='csv'):\n    pass\n",
        "class PluginMeta(type):\n    registry = {}\n\n    def __new__(mcls, name, bases, ns, slug=None):\n        cls = super().__new__(mcls, name, bases, ns)\n        if slug:\n            mcls.registry[slug] = cls\n        return cls\n\n\nclass Plugin(metaclass=PluginMeta):\n    pass\n\n\nclass CsvExport(Plugin, slug='csv'):\n    pass\n",
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


def build_phase4_metric(model: OpenAIModel) -> GEval:
    """Compat: metrica agregada da fase (mantida p/ testes de estrutura)."""
    return build_single_rule_metric(
        model,
        RULE_CASES[0][0],
        "Fluent Python Phase 4 Rule 1",
    )



def test_phase4_metric_factory_uses_single_rule_and_strict_threshold() -> None:
    """Business Rule: cada metrica de avaliacao carrega UMA regra com
    threshold 0.9 e nome da fase — granularidade e o contrato anti-aleucinacao."""
    metric = build_single_rule_metric(
        build_judge_model(), "Test rule text.", "Fluent Python Phase 4 Rule X"
    )
    assert metric.threshold == 0.9
    criteria = metric.criteria or ""
    assert "Test rule text." in criteria
    assert "Phase 4" in metric.name


def test_phase4_real_llm_approves_idiomatic_snippets() -> None:
    """Business Rule: sanity calibração — o LLM do harness não pode reprovar o
    conjunto de micro-exemplares idiomáticos das regras da Fase 4."""
    failures: list[str] = []
    for index, (rule, good, _bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 4 Rule {index}"
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


def test_phase4_real_llm_forced_choice_discriminates_each_rule() -> None:
    """Business Rule: para TODAS as regras da Fase 4 o juiz identifica o
    segmento idiomático em escolha forçada A/B — discriminação confiável,
    dado que o score absoluto de um 7B mostrou-se instável nos previews
    (ora severo, ora carimbo total)."""
    failures: list[str] = []
    for index, (rule, good, bad) in enumerate(RULE_CASES, start=1):
        name = f"Fluent Python Phase 4 Rule {index}"
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
