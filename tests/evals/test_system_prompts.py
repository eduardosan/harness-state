"""Suíte de avaliação de prompts de sistema com DeepEval (Spec/Prompt CI)."""

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

# Garante que telemetria externa do DeepEval permanece desativada
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



GUIDELINE_CASES: list[tuple[str, str, str]] = [
    (
        "The code must not contain nested function definitions.",
        (
            "def outer(x: int) -> int:\n    return x + 1\n\n\n"
            "def main() -> int:\n    return outer(1)\n"
        ),
        (
            "def outer(x: int) -> int:\n"
            "    def helper(y: int) -> int:\n"
            "        return y + 1\n\n    return helper(x)\n"
        ),
    ),
    (
        "The code must not contain nested try-except blocks.",
        (
            "import sqlite3\n\n\ndef connect(db_path: str) -> sqlite3.Connection:\n"
            "    try:\n        return sqlite3.connect(db_path)\n"
            "    except sqlite3.Error as exc:\n"
            "        raise RuntimeError(str(exc)) from exc\n"
        ),
        (
            "def read(path):\n    try:\n"
            "        try:\n"
            "            return open(path, encoding='utf-8').read()\n"
            "        except ValueError:\n            return ''\n"
            "    except OSError:\n        return ''\n"
        ),
    ),
]


def test_python_guidelines_real_llm_forced_choice_discriminates() -> None:
    """Business Rule: para cada diretriz estrutural Python (sem função
    aninhada; sem try/except aninhado) o LLM do harness identifica o segmento
    idiomático em escolha forçada A/B com maioria de 3 votos. Estilo/PEP8
    pertence ao gate determinístico (ruff); ao LLM cabe o estrutural — e o
    score absoluto provou-se bimodal em previews, daí a escolha forçada."""
    from harness_state.judge import aggregate_functional_votes

    failures: list[str] = []
    for index, (rule, good, bad) in enumerate(GUIDELINE_CASES, start=1):
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
            ok = raw.strip().upper()[:1] == choice
            votes.append((100 if ok else 0, ok, raw.strip()[:60]))
        _, success, reason = aggregate_functional_votes(votes)
        if not success:
            failures.append(f"Rule {index}: esperado={choice} votos={reason}")
    assert not failures, "escolha forçada falhou:\n" + "\n".join(failures)


def build_rca_metric(model: OpenAIModel) -> GEval:
    """Cria a metrica GEval para avaliar investigacao de causa raiz e anti-mascaramento.

    Args:
        model: Modelo instanciado para atuar como juiz.

    Returns:
        Instancia de GEval configurada para fiscalizar RCA e 5 Whys.
    """
    criteria = (
        "Evaluate whether the solution addresses the root cause of the problem "
        "rather than masking errors with superficial try-except blocks, silent "
        "suppressions, or unneeded test mocks. Deduct all points if errors are masked."
    )
    return GEval(
        name="Root Cause Analysis and Exception Masking Prevention",
        criteria=criteria,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


def test_rca_guidelines_file_exists_and_valid() -> None:
    """Business Rule: Diretrizes de RCA devem conter Ishikawa e 5 Whys."""
    spec_path = Path("specs/prompts/rca_guidelines.md")
    assert spec_path.is_file()
    content = spec_path.read_text(encoding="utf-8")
    assert "Proibição de Mascaramento" in content
    assert "Diagrama de Ishikawa" in content
    assert "5 Porquês" in content


def test_rca_metric_structure() -> None:
    """Business Rule: A metrica de RCA deve ter limiar estrito de 0.9."""
    dummy_model = OpenAIModel(
        model="agentic-qwen",
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_rca_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Root Cause Analysis and Exception Masking Prevention"


def test_rca_evaluation_rejects_exception_masking() -> None:
    """Business Rule: o LLM real reprova por maioria a máscara de falha de
    binário com `except: pass` — a métrica de RCA discrimina, não carimba."""
    metric = build_rca_metric(model=build_judge_model())
    test_case = LLMTestCase(
        input="Fix missing gcloud CLI binary in CI runner during log fetching.",
        actual_output=(
            "try:\n    subprocess.run(cmd)\nexcept OSError:\n    pass\n"
        ),
    )

    score, success, reason = measure_metric_with_majority(metric, test_case)
    assert not success, f"juiz aprovou mascaramento: score={score} reason={reason}"
    assert score < int((metric.threshold or 0.9) * 100)
