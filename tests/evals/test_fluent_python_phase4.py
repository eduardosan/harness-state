"""Suíte de avaliação das especificações da Fase 4 de Python Fluente.

Valida as especificações PY-12 (Concorrência e Programação Assíncrona)
e PY-13 (Atributos Dinâmicos, Descritores e Metaprogramação), além de definir a métrica
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


PHASE4_SPECS = [
    "SPEC-PY-12-concurrency-and-async.md",
    "SPEC-PY-13-dynamic-attributes-and-metaprogramming.md",
]


def build_phase4_metric(model: OpenAIModel) -> GEval:
    """Cria a métrica GEval para avaliar conformidade com a Fase 4.

    Args:
        model: Instância do modelo LLM-as-a-Judge.

    Returns:
        Instância de GEval configurada para avaliar Concorrência Estruturada
        (TaskGroup/ProcessPool), @property, Descritores e __init_subclass__.
    """
    criteria = (
        "The generated Python code must follow Fluent Python standards: "
        "1. In asynchronous code, never perform blocking I/O inside the event loop; "
        "use asyncio.TaskGroup for structured concurrency and explicit timeouts. "
        "2. Choose concurrency models according to the bottleneck: ProcessPoolExecutor "
        "for CPU-bound tasks, ThreadPoolExecutor/asyncio for I/O-bound tasks. "
        "3. Use @property for computed attributes and reusable Descriptors with "
        "__set_name__ for repeated validation; avoid procedural get_/set_ methods. "
        "4. Follow the metaprogramming hierarchy: class decorator -> "
        "__init_subclass__ -> metaclass, preferring __init_subclass__ over metaclasses."
    )
    return GEval(
        name="Fluent Python Phase 4 Compliance",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )




@pytest.mark.parametrize("spec_filename", PHASE4_SPECS)
def test_phase4_spec_files_exist_and_follow_template(spec_filename: str) -> None:
    """Business Rule: specs da Fase 4 devem existir e seguir o molde canônico.

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


def test_phase4_metric_structure() -> None:
    """Business Rule: a métrica da Fase 4 deve ter threshold 0.9 e nome canônico."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_phase4_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Fluent Python Phase 4 Compliance"


def test_phase4_real_llm_approves_idiomatic_sample() -> None:
    """Business Rule: o LLM do harness avalia de verdade o código idiomático da
    Fase 4 e o aprova por maioria de 3 votos no endpoint configurado."""
    model = build_judge_model()
    metric = build_phase4_metric(model=model)
    case = LLMTestCase(
        input="concurrent URL fetching with structured concurrency.",
        actual_output=(
            "import asyncio\n\nasync def fetch_all(urls: list[str]) -> dict[str, str]:\n    results: dict[str, str] = {}\n    async with asyncio.TaskGroup() as tg, asyncio.timeout(10):\n        tasks = {url: tg.create_task(fetch(url)) for url in urls}\n    for url, task in tasks.items():\n        results[url] = task.result()\n    return results\n"
        ),
    )

    score, success, reason = measure_metric_with_majority(metric, case)
    assert success, f"juiz rejeitou código idiomático: score={score} reason={reason}"
    assert score >= int((metric.threshold or 0.9) * 100)
    assert reason


def test_phase4_real_llm_discriminates_anti_pattern() -> None:
    """Business Rule: o mesmo juiz marca nota estritamente menor no anti-padrão
    da Fase 4 — a avaliação exercita o LLM e prova discriminação, não carimbo."""
    model = build_judge_model()
    metric_good = build_phase4_metric(model=model)
    metric_bad = build_phase4_metric(model=model)
    good = LLMTestCase(
        input="concurrent URL fetching with structured concurrency.",
        actual_output=(
            "import asyncio\n\nasync def fetch_all(urls: list[str]) -> dict[str, str]:\n    results: dict[str, str] = {}\n    async with asyncio.TaskGroup() as tg, asyncio.timeout(10):\n        tasks = {url: tg.create_task(fetch(url)) for url in urls}\n    for url, task in tasks.items():\n        results[url] = task.result()\n    return results\n"
        ),
    )
    bad = LLMTestCase(
        input="concurrent URL fetching with structured concurrency.",
        actual_output=(
            "import time\n\nasync def fetch_all(urls):\n    out = []\n    for url in urls:\n        time.sleep(1)\n        out.append(fetch(url))\n    return out\n\nclass Config:\n    def get_port(self): return self._port\n    def set_port(self, value): self._port = value\n"
        ),
    )

    score_good, _, _ = measure_metric_with_majority(metric_good, good)
    score_bad, _, _ = measure_metric_with_majority(metric_bad, bad)
    assert score_bad < score_good, (
        f"juiz não discriminou o anti-padrão: bom={score_good} ruim={score_bad}"
    )
