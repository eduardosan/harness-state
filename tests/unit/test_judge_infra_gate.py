"""Testes do skip explícito do Gate 5 para entregas não-código (SPEC-004 B3)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from harness_state.judge import evaluate_spec_diff


def _write_spec(tmp_path: Path, frontmatter: str) -> Path:
    spec = tmp_path / "spec.md"
    spec.write_text(f"{frontmatter}\n# Especificação\n\nRequisitos...\n")
    return spec


SPEC_CODE = (
    "---\nspec_id: SPEC-004\ntitle: bugfixes\n---\n# Especificação\n\nRequisitos..."
)
SPEC_NON_CODE = (
    "---\nspec_id: SPEC-004\ntitle: registro\ntype: infra\n"
    "non_code_deliverables: true\n"
    "---\n# Especificação\n\nRequisitos..."
)


def test_gate_skips_when_no_diff(tmp_path: Path) -> None:
    """Business Rule: diffs vazio → score None com skip; LLM não é chamado."""
    spec = _write_spec(tmp_path, SPEC_CODE)
    diffs = tmp_path / "diffs.patch"
    diffs.write_text("")

    with patch("harness_state.judge.build_judge_model") as mock_model:
        result = evaluate_spec_diff(spec_path=spec, diffs_path=diffs)

    mock_model.assert_not_called()
    assert result.compliance_score is None
    assert "skip" in result.summary.lower()
    assert result.status == "APPROVED"


def test_gate_skips_for_non_code_spec(tmp_path: Path) -> None:
    """Business Rule: spec non_code_deliverables pula o juiz, mesmo com diff."""
    spec = _write_spec(tmp_path, SPEC_NON_CODE)
    diffs = tmp_path / "diffs.patch"
    diffs.write_text("diff --git a/doc.md b/doc.md\n--- a/doc.md\n+++ b/doc.md\n")

    with patch("harness_state.judge.build_judge_model") as mock_model:
        result = evaluate_spec_diff(spec_path=spec, diffs_path=diffs)

    mock_model.assert_not_called()
    assert result.compliance_score is None
    assert "skip" in result.summary.lower()


def test_gate_still_judges_code_specs(tmp_path: Path) -> None:
    """Business Rule: spec de código com diff presente segue ao judge (sem skip)."""
    spec = _write_spec(tmp_path, SPEC_CODE)
    diffs = tmp_path / "diffs.patch"
    diffs.write_text("diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n")

    with patch("harness_state.judge.build_judge_model") as mock_model:
        mock_model.side_effect = ValueError("sentinela: caminho do judge atingido")
        with pytest.raises(ValueError, match="sentinela"):
            evaluate_spec_diff(spec_path=spec, diffs_path=diffs)

    mock_model.assert_called_once()
