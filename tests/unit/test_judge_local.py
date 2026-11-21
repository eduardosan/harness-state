"""Testes unitários para o local self-judge e validação dupla (SPEC-009G)."""

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from harness_state.cli import main as cli_main
from harness_state.judge import (
    FUNCTIONAL_GATE_RULES,
    LocalJudgeEvaluation,
    evaluate_local_diff,
    validate_normative_rules,
)
from harness_state.runtimes.coder_prompts import (
    CODER_SELF_JUDGE_INSTRUCTION,
    JUDGE_FAST_EVALUATION_INSTRUCTION,
)


def test_prompts_spec_009g_registered() -> None:
    """Business Rule: Os prompts CODER_SELF_JUDGE_INSTRUCTION e JUDGE_FAST_EVALUATION_INSTRUCTION devem estar registrados."""
    assert "Gate Integrity & Test Preservation" in CODER_SELF_JUDGE_INSTRUCTION
    assert "No Error Masking" in CODER_SELF_JUDGE_INSTRUCTION
    assert "Public Contract Preservation" in CODER_SELF_JUDGE_INSTRUCTION
    assert ".harness/verification-summary.json" in CODER_SELF_JUDGE_INSTRUCTION

    assert "Sovereign LLM-as-a-Judge" in JUDGE_FAST_EVALUATION_INSTRUCTION
    assert len(FUNCTIONAL_GATE_RULES) >= 3


def test_evaluate_local_diff_returns_evaluation_instance(tmp_path: Path) -> None:
    """Business Rule: evaluate_local_diff deve retornar uma instância de LocalJudgeEvaluation."""
    eval_result = evaluate_local_diff(repo_dir=tmp_path)
    assert isinstance(eval_result, LocalJudgeEvaluation)
    assert eval_result.is_approved is True
    assert "consolidated single-vote" in JUDGE_FAST_EVALUATION_INSTRUCTION


def test_validate_normative_rules_detects_error_masking() -> None:
    """Business Rule: Qualquer mascaramento de erro (except: pass) deve falhar imediatamente na Regra 2."""
    diff_with_masking = (
        "--- a/src/service.py\n"
        "+++ b/src/service.py\n"
        "@@ -10,4 +10,7 @@\n"
        "+try:\n"
        "+    risky_operation()\n"
        "+except Exception:\n"
        "+    pass\n"
    )
    passed, violations = validate_normative_rules(diff_with_masking)
    assert not passed
    assert any("Regra 2" in v or "Error Masking" in v for v in violations)


def test_validate_normative_rules_detects_weakened_assertions() -> None:
    """Business Rule: Qualquer assert enfraquecido (ex: assert True) deve falhar imediatamente na Regra 1."""
    diff_with_weak_assert = (
        "--- a/tests/test_service.py\n"
        "+++ b/tests/test_service.py\n"
        "@@ -20,3 +20,3 @@\n"
        "-assert result == expected_data\n"
        "+assert True\n"
    )
    passed, violations = validate_normative_rules(diff_with_weak_assert)
    assert not passed
    assert any("Regra 1" in v or "Integrity" in v for v in violations)


def test_validate_normative_rules_passes_on_clean_diff() -> None:
    """Business Rule: Diffs em conformidade com as regras devem passar na validação normativa."""
    clean_diff = (
        "--- a/src/service.py\n"
        "+++ b/src/service.py\n"
        "@@ -10,3 +10,5 @@\n"
        "+def compute_metrics(x: int) -> int:\n"
        "+    return x * 2\n"
    )
    passed, violations = validate_normative_rules(clean_diff)
    assert passed
    assert len(violations) == 0


def test_evaluate_local_diff_emits_verification_summary(tmp_path: Path) -> None:
    """Business Rule: A auto-avaliação do agente deve emitir o arquivo .harness/verification-summary.json."""
    summary_file = tmp_path / ".harness" / "verification-summary.json"
    clean_diff = (
        "--- a/src/service.py\n"
        "+++ b/src/service.py\n"
        "@@ -1,2 +1,4 @@\n"
        "+def valid_addition(a: int, b: int) -> int:\n"
        "+    return a + b\n"
    )

    evaluation = evaluate_local_diff(
        diff_text=clean_diff,
        out_file=summary_file,
    )
    assert evaluation.is_approved
    assert summary_file.is_file()

    data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert data["status"] == "APPROVED"
    assert data["compliance_score"] == 100
    assert "rules" in data
    assert len(data["violations"]) == 0


def test_evaluate_local_diff_rejects_and_writes_summary_on_failure(tmp_path: Path) -> None:
    """Business Rule: Em caso de violação, o verification-summary.json registra status REJECTED."""
    summary_file = tmp_path / ".harness" / "verification-summary.json"
    bad_diff = (
        "--- a/src/service.py\n"
        "+++ b/src/service.py\n"
        "@@ -1,2 +1,5 @@\n"
        "+try:\n"
        "+    db_call()\n"
        "+except:\n"
        "+    pass\n"
    )

    evaluation = evaluate_local_diff(
        diff_text=bad_diff,
        out_file=summary_file,
    )
    assert not evaluation.is_approved
    assert summary_file.is_file()

    data = json.loads(summary_file.read_text(encoding="utf-8"))
    assert data["status"] == "REJECTED"
    assert data["compliance_score"] < 100
    assert len(data["violations"]) > 0


def test_cli_harness_judge_local_command(tmp_path: Path) -> None:
    """Business Rule: O comando CLI harness judge --local deve executar o self-judge e retornar 0 para diff limpo."""
    runner = CliRunner()
    clean_diff = "diff --git a/file.py b/file.py\n+x = 1\n"
    summary_file = tmp_path / ".harness" / "verification-summary.json"

    with patch("harness_state.judge.get_git_diff", return_value=clean_diff):
        result = runner.invoke(
            cli_main,
            ["judge", "--local", "--out-file", str(summary_file)],
        )
        assert result.exit_code == 0
        assert "Auto-avaliação do Judge Local: APROVADO" in result.output
        assert summary_file.is_file()


def test_cli_harness_judge_local_fails_on_violation(tmp_path: Path) -> None:
    """Business Rule: O comando CLI harness judge --local deve retornar 1 quando houver violação."""
    runner = CliRunner()
    bad_diff = (
        "--- a/file.py\n"
        "+++ b/file.py\n"
        "+except Exception:\n"
        "+    pass\n"
    )
    summary_file = tmp_path / ".harness" / "verification-summary.json"

    with patch("harness_state.judge.get_git_diff", return_value=bad_diff):
        result = runner.invoke(
            cli_main,
            ["judge", "--local", "--out-file", str(summary_file)],
        )
        assert result.exit_code == 1
        assert "REJEITADO" in result.output
        assert summary_file.is_file()
