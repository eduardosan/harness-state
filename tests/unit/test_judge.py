"""Testes do avaliador LLM-as-a-Judge para o Cross-Repo Harness Gate via DeepEval."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness_state.judge import (
    JUDGE_DEFAULT_MODEL,
    JUDGE_FALLBACK_MODEL,
    JudgeEvaluation,
    aggregate_functional_votes,
    build_fluent_python_metric,
    build_gate_metric,
    build_judge_model,
    evaluate_spec_diff,
    main,
    resolve_fallback_judge_model,
)


def test_build_judge_model_configuration() -> None:
    """Business Rule: O cliente de modelo deve ser configurado com endpoint e modelo."""
    model = build_judge_model(
        base_url="http://127.0.0.1:11435/v1",
        api_key="secret",
        model_name="agentic-qwen",
    )
    assert model.get_model_name() == "agentic-qwen"


def test_primary_judge_resolves_canonical_configured_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business Rule: a var canônica do GitHub alimenta o tier 1 do juiz.

    `LLM_JUDGE_MODEL` (var do servidor) tem precedência sobre os demais
    canais, garantindo que o judge resolva o id canônico do ecossistema em
    qualquer runner.
    """
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.setenv("LLM_JUDGE_MODEL", "opencode/glm-5.3-flash-free")

    model = build_judge_model()

    assert model.get_model_name() == "opencode/glm-5.3-flash-free"


def test_fallback_judge_resolves_ecosystem_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business Rule: a var `LLM_JUDGE_FALLBACK_MODEL` alimenta o tier 2.

    A var do GitHub (companion de `LLM_JUDGE_MODEL`) tem precedência sobre a
    var legada `JUDGE_FALLBACK_MODEL`; a constante é apenas recurso para
    ambientes sem configuração.
    """
    monkeypatch.setenv("LLM_JUDGE_FALLBACK_MODEL", "agentic-qwen")
    monkeypatch.setenv("JUDGE_FALLBACK_MODEL", "stale-legacy-model")

    fallback = resolve_fallback_judge_model()

    assert fallback == "agentic-qwen"


def test_fallback_judge_ignores_agent_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business Rule: sem vars de fallback, o tier 2 usa a constante do juiz —
    NUNCA `LLM_DEFAULT_MODEL`, que é o default dos agentes (id de provedor que
    pode nem existir no endpoint Ollama do juiz, como `opencode/...`)."""
    monkeypatch.delenv("JUDGE_FALLBACK_MODEL", raising=False)
    monkeypatch.delenv("LLM_JUDGE_FALLBACK_MODEL", raising=False)
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "opencode/glm-5.3-flash-free")

    fallback = resolve_fallback_judge_model()

    assert fallback == JUDGE_FALLBACK_MODEL == "agentic-qwen"


def test_build_judge_model_defaults_to_opencode_free_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business Rule: sem config, o tier 1 default do juiz é o id canônico OpenCode."""
    monkeypatch.delenv("JUDGE_MODEL", raising=False)
    monkeypatch.delenv("LLM_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    model = build_judge_model()

    assert model.get_model_name() == JUDGE_DEFAULT_MODEL
    assert model.get_model_name() == "opencode/glm-5.3-flash-free"


@patch("harness_state.judge.build_judge_model")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_uses_opencode_default_and_falls_back_to_qwen(
    mock_build_metric: MagicMock,
    mock_build_model: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Recursos esgotados no OpenCode degradam a agentic-qwen."""
    spec_file = tmp_path / "SPEC-010.md"
    spec_file.write_text("# SPEC-010\nRequisito: Endpoint GET /ping", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+def ping(): return 'pong'", encoding="utf-8")

    failing_metric = MagicMock()
    failing_metric.measure.side_effect = RuntimeError("Free tier esgotado (HTTP 403).")
    succeeding_metric = MagicMock()
    succeeding_metric.score = 0.96
    succeeding_metric.reason = "Avaliado com sucesso no tier de fallback."
    succeeding_metric.is_successful.return_value = True
    mock_build_metric.side_effect = [failing_metric, succeeding_metric]

    mock_build_model.side_effect = [MagicMock(name="primary"), MagicMock(name="fb")]

    result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        model="glm-5.3-flash-free",
        fallback_model="agentic-qwen",
    )

    assert result.status == "APPROVED"
    assert result.compliance_score == 96
    assert mock_build_model.call_count == 2
    assert mock_build_model.call_args_list[1].kwargs.get("model_name") == "agentic-qwen"


@patch("harness_state.judge.build_judge_model")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_does_not_retry_when_fallback_equals_primary(
    mock_build_metric: MagicMock,
    mock_build_model: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Nao ha retry com modelo de fallback identico ao primario."""
    spec_file = tmp_path / "SPEC-011.md"
    spec_file.write_text("# SPEC-011\nRequisito: Endpoint GET /ping", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+def ping(): return 'pong'", encoding="utf-8")

    failing_metric = MagicMock()
    failing_metric.measure.side_effect = RuntimeError("Endpoint invalido.")
    mock_build_metric.return_value = failing_metric

    result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        model="agentic-qwen",
        fallback_model="agentic-qwen",
    )

    assert result.status == "REJECTED"
    assert result.compliance_score == 0
    assert "Endpoint invalido" in result.summary
    assert mock_build_model.call_count == 1
    assert mock_build_metric.call_count == 1


def test_build_gate_metric_rubric() -> None:
    """Business Rule: A metrica de gate deve configurar o limiar rigoroso de 0.9."""
    dummy_model = build_judge_model(
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_gate_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Cross-Repo Specification Compliance"


@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_approved(
    mock_build_metric: MagicMock, tmp_path: Path
) -> None:
    """Business Rule: Implementacao conforme gera veredito APPROVED e score alto."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Endpoint GET /ping", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+def ping(): return 'pong'", encoding="utf-8")

    mock_metric = MagicMock()
    mock_metric.score = 0.96
    mock_metric.reason = "Todos os requisitos foram atendidos sem regressoes."
    mock_metric.is_successful.return_value = True
    mock_build_metric.return_value = mock_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.spec_id == "SPEC-001"
    assert eval_result.compliance_score == 96
    assert eval_result.status == "APPROVED"
    assert eval_result.violations == []
    assert len(eval_result.recommendations) == 1


@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_formatting_and_maintenance_is_approved(
    mock_build_metric: MagicMock, tmp_path: Path
) -> None:
    """Business Rule: Manutencao e PEP 8 sem regressao geram APPROVED com score 100."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Arquitetura", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+# formatted line\n", encoding="utf-8")

    mock_metric = MagicMock()
    mock_metric.score = 0.27
    mock_metric.reason = (
        "The provided code changes are minor formatting adjustments and do not "
        "introduce any new functionality or address any specific issues. The "
        "changes are consistent with PEP 8 style guidelines and do not affect "
        "the logic or behavior of the code. Therefore, the changes are not "
        "significant enough to warrant a score above 0."
    )
    mock_metric.is_successful.return_value = False
    mock_build_metric.return_value = mock_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert eval_result.compliance_score == 100
    assert eval_result.violations == []


@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_tag_release_unrelated_changes_is_approved(
    mock_build_metric: MagicMock, tmp_path: Path
) -> None:
    """Business Rule: Manutencao de release sem regressoes e aprovada pelo Gate."""
    spec_file = tmp_path / "code-evaluation-flow.md"
    spec_file.write_text("# Code Evaluation Flow\nRequisito: Judge", encoding="utf-8")
    diffs_file = tmp_path / "release_diff.patch"
    diffs_file.write_text("+# release maintenance\n", encoding="utf-8")

    mock_metric = MagicMock()
    mock_metric.score = 0.30
    mock_metric.reason = (
        "The actual output does not provide any code changes or modifications "
        "that adhere to the architecture and principles described in the "
        "specification. The changes made are not relevant to the evaluation "
        "criteria and do not demonstrate any maintenance, bug fixes, or "
        "enhancements as per the given test case parameters"
    )
    mock_metric.is_successful.return_value = False
    mock_build_metric.return_value = mock_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert eval_result.compliance_score == 100
    assert eval_result.violations == []


def test_build_fluent_python_metric_rubric() -> None:
    """Business Rule: A metrica de Python Fluente configura limiar 0.9 e rubrica."""
    dummy_model = build_judge_model(
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )
    metric = build_fluent_python_metric(model=dummy_model)
    assert metric.threshold == 0.9
    assert metric.name == "Fluent Python Idiomatic Compliance"


@patch("harness_state.judge.build_fluent_python_metric")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_staged_both_approved(
    mock_build_func: MagicMock,
    mock_build_fluent: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Avaliacao em etapas aprova quando funcional e fluente passam."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Entidade Pedido", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diff_patch = (
        "--- a/models.py\n"
        "+++ b/models.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+from dataclasses import dataclass\n"
        "+@dataclass\n"
        "+class Order: pass\n"
    )
    diffs_file.write_text(diff_patch, encoding="utf-8")

    mock_func_metric = MagicMock()
    mock_func_metric.score = 0.95
    mock_func_metric.reason = "Funcional aprovado."
    mock_func_metric.is_successful.return_value = True
    mock_build_func.return_value = mock_func_metric

    mock_fluent_metric = MagicMock()
    mock_fluent_metric.score = 0.90
    mock_fluent_metric.reason = "Uso correto de dataclasses."
    mock_fluent_metric.is_successful.return_value = True
    mock_build_fluent.return_value = mock_fluent_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert (
        eval_result.compliance_score is not None and eval_result.compliance_score >= 90
    )
    assert mock_build_func.called
    assert mock_build_fluent.called
    # Verifica que a chamada funcional recebeu a spec original e o diff completo
    called_func_case = mock_func_metric.measure.call_args[0][0]
    assert "# SPEC-001" in called_func_case.input
    assert "+@dataclass" in called_func_case.actual_output
    # Verifica que a chamada fluente recebeu diretrizes normativas e linhas adicionadas
    called_fluent_case = mock_fluent_metric.measure.call_args[0][0]
    assert "SPEC-PY-05" in called_fluent_case.input
    assert "@dataclass" in called_fluent_case.actual_output


@patch("harness_state.judge.build_fluent_python_metric")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_staged_fluent_rejected(
    mock_build_func: MagicMock,
    mock_build_fluent: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Falha na etapa de Python Fluente rejeita o veredito com tag."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Entidade Pedido", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diff_patch = (
        "--- a/models.py\n"
        "+++ b/models.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+from dataclasses import dataclass\n"
        "+@dataclass\n"
        "+class Order: pass\n"
    )
    diffs_file.write_text(diff_patch, encoding="utf-8")

    mock_func_metric = MagicMock()
    mock_func_metric.score = 0.95
    mock_func_metric.reason = "Funcional ok."
    mock_func_metric.is_successful.return_value = True
    mock_build_func.return_value = mock_func_metric

    mock_fluent_metric = MagicMock()
    mock_fluent_metric.score = 0.60
    mock_fluent_metric.reason = "Anti-padrao detectado na construcao da classe."
    mock_fluent_metric.is_successful.return_value = False
    mock_build_fluent.return_value = mock_fluent_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "REJECTED"
    assert any("[Python Fluente]" in v for v in eval_result.violations)


@patch("harness_state.judge.build_fluent_python_metric")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_ignores_utility_class_special_methods_false_positive(
    mock_build_func: MagicMock,
    mock_build_fluent: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Falsos positivos de special methods sao tolerados."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Sensor AST", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diff_patch = (
        "--- a/sensor.py\n"
        "+++ b/sensor.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+class AstSensor:\n"
        "+    def visit_node(self, node):\n"
        "+        pass\n"
    )
    diffs_file.write_text(diff_patch, encoding="utf-8")

    mock_func_metric = MagicMock()
    mock_func_metric.score = 1.0
    mock_func_metric.reason = "Funcional totalmente aderente."
    mock_func_metric.is_successful.return_value = True
    mock_build_func.return_value = mock_func_metric

    mock_fluent_metric = MagicMock()
    mock_fluent_metric.score = 0.20
    mock_fluent_metric.reason = (
        "The code does not implement special methods like __repr__ and __len__."
    )
    mock_fluent_metric.is_successful.return_value = False
    mock_build_fluent.return_value = mock_fluent_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert (
        eval_result.compliance_score is not None and eval_result.compliance_score >= 90
    )
    assert eval_result.violations == []


@patch("harness_state.judge.build_fluent_python_metric")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_skips_fluent_metric_when_not_applicable(
    mock_build_func: MagicMock,
    mock_build_fluent: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Diffs sem specs de Python Fluente ignoram etapa fluente."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Endpoint Ping", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+// go code", encoding="utf-8")

    mock_func_metric = MagicMock()
    mock_func_metric.score = 0.95
    mock_func_metric.reason = "Funcional aprovado."
    mock_func_metric.is_successful.return_value = True
    mock_build_func.return_value = mock_func_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert mock_build_func.called
    assert not mock_build_fluent.called


@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_rejected(
    mock_build_metric: MagicMock, tmp_path: Path
) -> None:
    """Business Rule: Violacoes nos diffs resultam em veredito REJECTED."""
    spec_file = tmp_path / "SPEC-002.md"
    spec_file.write_text(
        "# SPEC-002\nRequisito: Endpoint POST /order", encoding="utf-8"
    )
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+def health(): pass", encoding="utf-8")

    mock_metric = MagicMock()
    mock_metric.score = 0.40
    mock_metric.reason = "O endpoint POST /order nao foi implementado nos diffs."
    mock_metric.is_successful.return_value = False
    mock_build_metric.return_value = mock_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.spec_id == "SPEC-002"
    assert eval_result.compliance_score == 40
    assert eval_result.status == "REJECTED"
    assert len(eval_result.violations) == 1
    assert "POST /order" in eval_result.violations[0]


def test_evaluate_spec_diff_missing_spec_file(tmp_path: Path) -> None:
    """Business Rule: Arquivo de especificacao inexistente gera REJECTED com score 0."""
    missing_spec = tmp_path / "nao_existe.md"
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+code", encoding="utf-8")

    eval_result = evaluate_spec_diff(
        spec_path=missing_spec,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.compliance_score == 0
    assert eval_result.status == "REJECTED"
    assert "nao encontrado" in eval_result.summary


def test_evaluate_spec_diff_missing_diffs_file(tmp_path: Path) -> None:
    """Business Rule: Arquivo de diffs inexistente gera REJECTED com score 0."""
    spec_file = tmp_path / "SPEC-003.md"
    spec_file.write_text("# SPEC-003", encoding="utf-8")
    missing_diffs = tmp_path / "diffs_ausente.patch"

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=missing_diffs,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.compliance_score == 0
    assert eval_result.status == "REJECTED"
    assert "nao encontrado" in eval_result.summary


@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_exception_fallback(
    mock_build_metric: MagicMock, tmp_path: Path
) -> None:
    """Business Rule: Falhas inesperadas durante a medicao geram REJECTED seguro."""
    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# SPEC-004", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+code", encoding="utf-8")

    mock_metric = MagicMock()
    mock_metric.measure.side_effect = RuntimeError("Conexao recusada pelo modelo LLM.")
    mock_build_metric.return_value = mock_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.compliance_score == 0
    assert eval_result.status == "REJECTED"
    assert "Conexao recusada" in eval_result.summary


@patch("harness_state.judge.evaluate_spec_diff")
def test_main_cli_execution_approved(mock_eval: MagicMock, tmp_path: Path) -> None:
    """Business Rule: CLI do judge grava arquivo JSON de saida e outputs do Actions."""
    spec_file = tmp_path / "SPEC-005.md"
    spec_file.write_text("# SPEC-005", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+code", encoding="utf-8")
    out_json = tmp_path / "evaluation.json"
    gh_output = tmp_path / "github_output"

    mock_eval.return_value = JudgeEvaluation(
        spec_id="SPEC-005",
        compliance_score=94,
        status="APPROVED",
        summary="Aprovado com 94% de aderencia.",
        violations=[],
        recommendations=[],
    )

    exit_code = main(
        [
            "--spec",
            str(spec_file),
            "--diffs",
            str(diffs_file),
            "--spec-id",
            "SPEC-005",
            "--out-file",
            str(out_json),
            "--github-output",
            str(gh_output),
        ]
    )

    assert exit_code == 0
    assert out_json.is_file()
    saved = json.loads(out_json.read_text(encoding="utf-8"))
    assert saved["status"] == "APPROVED"
    assert saved["compliance_score"] == 94

    gh_text = gh_output.read_text(encoding="utf-8")
    assert "status=APPROVED" in gh_text
    assert "compliance_score=94" in gh_text


@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_with_tested_bugfix_implementation_is_approved(
    mock_build_metric: MagicMock, tmp_path: Path
) -> None:
    """Business Rule: Implementacao testada de bugfix/feature gera APPROVED com 100."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Arquitetura", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+def bug_plan(): pass\n", encoding="utf-8")

    mock_metric = MagicMock()
    mock_metric.score = 0.35
    mock_metric.reason = (
        "The provided code snippet includes a detailed implementation of a "
        "new feature in the bug_plan_cmd function, which now supports a "
        "continue_session parameter. The code also includes several unit tests "
        "to validate the behavior of the new feature, ensuring that it correctly "
        "handles different scenarios such as starting a new session, continuing "
        "an existing session, and handling positional arguments for the issue ID. "
        "The tests use the unittest.mock library to patch functions and simulate "
        "user input, and they assert the expected behavior."
    )
    mock_metric.is_successful.return_value = False
    mock_build_metric.return_value = mock_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert eval_result.compliance_score == 100
    assert eval_result.violations == []


@patch("harness_state.judge.build_fluent_python_metric")
@patch("harness_state.judge.build_gate_metric")
def test_evaluate_spec_diff_ignores_immutable_default_argument_false_positive(
    mock_build_func: MagicMock,
    mock_build_fluent: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: Alucinacoes de default imutavel como mutavel sao toleradas."""
    spec_file = tmp_path / "SPEC-001.md"
    spec_file.write_text("# SPEC-001\nRequisito: Bug Intake", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diff_patch = (
        "--- a/bug.py\n"
        "+++ b/bug.py\n"
        "@@ -0,0 +1,3 @@\n"
        "+def elicit(prompt: str, continue_session: bool | None = None):\n"
        "+    pass\n"
    )
    diffs_file.write_text(diff_patch, encoding="utf-8")

    mock_func_metric = MagicMock()
    mock_func_metric.score = 1.0
    mock_func_metric.reason = "Funcional totalmente aderente."
    mock_func_metric.is_successful.return_value = True
    mock_build_func.return_value = mock_func_metric

    mock_fluent_metric = MagicMock()
    mock_fluent_metric.score = 0.30
    mock_fluent_metric.reason = (
        "The code introduces a new parameter continue_session with a default value "
        "of False in the elicit_bug_plan_with_llm function, which is a mutable "
        "default argument anti-pattern. This violates SPEC-PY-06."
    )
    mock_fluent_metric.is_successful.return_value = False
    mock_build_fluent.return_value = mock_fluent_metric

    eval_result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        base_url="http://127.0.0.1:11435/v1",
        api_key="ollama",
    )

    assert eval_result.status == "APPROVED"
    assert eval_result.compliance_score == 100
    assert eval_result.violations == []


def test_compact_diff_for_functional_stage_passthrough_small_diff() -> None:
    """Business Rule: Diffs abaixo do orcamento da Etapa 1 seguem integros."""
    from harness_state.judge import compact_diff_for_functional_stage

    small_diff = "diff --git a/src/app.py b/src/app.py\n+++ b/src/app.py\n+x = 1\n"
    assert compact_diff_for_functional_stage(small_diff) == small_diff


def test_compact_diff_for_functional_stage_respects_global_budget() -> None:
    """Business Rule: O diff compactado da Etapa 1 respeita o orcamento de tokens."""
    from harness_state.judge import (
        MAX_FUNC_STAGE_TOTAL_CHARS,
        compact_diff_for_functional_stage,
    )

    big_line = "".join(
        f"+def value_handler_{n:02d}():\n    return 'x' * 40\n" for n in range(400)
    )
    blocks = [
        f"diff --git a/src/flywheel/module_{n:02d}.py b/src/"
        f"flywheel/module_{n:02d}.py\n"
        f"+++ b/src/flywheel/module_{n:02d}.py\n"
        f"{big_line}"
        for n in range(20)
    ]
    giant_diff = "\n".join(blocks)

    compacted = compact_diff_for_functional_stage(giant_diff)

    assert len(compacted) <= MAX_FUNC_STAGE_TOTAL_CHARS + 500
    assert "diff --git a/src/flywheel/module_00.py" in compacted
    assert "arquivos omitidos por orçamento" in compacted


def test_compact_diff_priorizes_source_and_keeps_file_paths() -> None:
    """Business Rule: Codigofonte src/ tem prioridade no orcamento de tokens."""
    from harness_state.judge import compact_diff_for_functional_stage

    big_line = "".join(
        f"+data_value = 'payload de requisito de negocio {n}'\n" for n in range(600)
    )
    diffs_content = (
        f"diff --git a/docs/architecture/release.md b/docs/architecture/release.md\n"
        f"+++ b/docs/architecture/release.md\n{big_line}"
        f"diff --git a/src/flywheel/service.py b/src/flywheel/service.py\n"
        f"+++ b/src/flywheel/service.py\n{big_line}"
    )

    compacted = compact_diff_for_functional_stage(diffs_content)
    src_index = compacted.find("+++ b/src/flywheel/service.py")
    doc_index = compacted.find("+++ b/docs/architecture/release.md")

    assert src_index >= 0
    assert src_index < doc_index or doc_index == -1


def test_compact_file_added_lines_elides_middle_with_marker() -> None:
    """Business Rule: Blocos de diff gigantes mantem cabecalho e pontas dos hunks."""
    from harness_state.judge import (
        FUNC_STAGE_ELIDED_MARKER,
        compact_diff_block,
    )

    big_hunk = "\n".join(f"line_{number:03d}" for number in range(400))
    block = (
        "diff --git a/src/service.py b/src/service.py\n"
        "+++ b/src/service.py\n"
        f"@@\n{big_hunk}"
    )
    compacted = compact_diff_block(block)

    assert FUNC_STAGE_ELIDED_MARKER in compacted
    assert "diff --git a/src/service.py" in compacted
    assert "+++ b/src/service.py" in compacted
    assert "line_000" in compacted
    assert "line_399" in compacted
    assert len(compacted) <= len(block)


def test_compact_spec_for_functional_stage_slices_oversized_spec() -> None:
    """Business Rule: Especificacoes longas sao truncadas por orcamento de tokens."""
    from harness_state.judge import (
        MAX_FUNC_STAGE_SPEC_CHARS,
        compact_spec_for_functional_stage,
    )

    small_spec = "# Requisitos\n- endpoint GET /ping\n"
    assert compact_spec_for_functional_stage(small_spec) == small_spec

    big_spec = "linha de requisito de negocio para avalicao\n" * 1200
    compacted_spec = compact_spec_for_functional_stage(big_spec)

    assert compacted_spec.startswith(big_spec[:MAX_FUNC_STAGE_SPEC_CHARS])
    assert "spec elidida por orcamento" in compacted_spec
    assert len(compacted_spec) <= MAX_FUNC_STAGE_SPEC_CHARS + 100


def test_compact_diff_prioritizes_spec_referenced_files() -> None:
    """Business Rule: Arquivos na spec têm prioridade sobre outros arquivos src/."""
    from harness_state.judge import compact_diff_for_functional_stage

    spec_content = (
        "# Architecture\nComponente principal: `judge.py` e testes `test_judge.py`."
    )
    big_line = "+dummy line\n" * 200
    diffs_content = (
        f"diff --git a/src/flywheel/bug.py b/src/flywheel/bug.py\n"
        f"+++ b/src/flywheel/bug.py\n{big_line}"
        f"diff --git a/src/flywheel/cli.py b/src/flywheel/cli.py\n"
        f"+++ b/src/flywheel/cli.py\n{big_line}"
        f"diff --git a/src/flywheel/judge.py b/src/flywheel/judge.py\n"
        f"+++ b/src/flywheel/judge.py\n{big_line}"
    )

    compacted = compact_diff_for_functional_stage(
        diffs_content, spec_content=spec_content
    )
    judge_index = compacted.find("+++ b/src/flywheel/judge.py")
    bug_index = compacted.find("+++ b/src/flywheel/bug.py")

    assert judge_index >= 0
    assert judge_index < bug_index


def test_is_maintenance_or_refactor_reason_handles_unrelated_release_diff() -> None:
    """Business Rule: Mudancas fora do escopo da spec sem regressoes e manutencao."""
    from harness_state.judge import is_maintenance_or_refactor_reason

    reason = (
        "The actual output does not provide any code changes or modifications "
        "that adhere to the architecture and principles described in the "
        "specification. The changes made are not relevant to the evaluation "
        "criteria and do not demonstrate any maintenance, bug fixes, or "
        "enhancements as per the given test case parameters"
    )
    assert is_maintenance_or_refactor_reason(reason) is True


def test_aggregate_functional_votes_usa_mediana_e_maioria() -> None:
    """Business Rule: a Etapa 1 decide por mediana de score e maioria de
    sucesso — um voto ruidoso de modelo pequeno não aprova nem reprova sozinho."""
    score, success, reason = aggregate_functional_votes(
        [(30, False, "alucinou desvio"), (90, True, "ok"), (90, True, "ok")]
    )
    assert (score, success) == (90, True)
    assert reason == "ok"

    score, success, _ = aggregate_functional_votes(
        [(90, True, "ok"), (30, False, "ruim"), (20, False, "pior")]
    )
    assert (score, success) == (30, False)


def test_aggregate_functional_votes_rejeita_lista_vazia() -> None:
    """Business Rule: agregação sem votos é erro de programação, não veredito."""
    with pytest.raises(ValueError, match="ao menos 1 voto"):
        aggregate_functional_votes([])


class RecordingMetric:
    """Métrica funcional fake cujo score/sucesso variam a cada measure().

    Attributes:
        scores: Sequência de scores brutos (0..1) por votação.
        oks: Sequência de booleanos de sucesso por votação.
    """

    def __init__(self, scores: list[float], oks: list[bool]) -> None:
        """Inicializa a fila de votos."""
        self._scores = list(scores)
        self._oks = list(oks)
        self.calls = 0
        self.score: float = 0.0
        self.reason = ""

    def measure(self, _case: object) -> None:
        """Consome o próximo voto pré-programado."""
        self.score = self._scores[self.calls]
        self._ok = self._oks[self.calls]
        self.reason = f"vote-{self.calls}"
        self.calls += 1

    def is_successful(self) -> bool:
        """Retorna o sucesso do último voto consumido."""
        return self._ok


@patch("harness_state.judge.build_judge_model")
@patch("harness_state.judge.build_gate_metric")
def test_stage1_recupera_de_voto_ruidoso_por_maioria(
    mock_build_metric: MagicMock,
    mock_build_model: MagicMock,
    tmp_path: Path,
) -> None:
    """Business Rule: um voto 30/100 entre dois 95+ resulta em APPROVED —
    a maioria filtra o ruído do juiz de 7B sem afrouxar o limiar."""
    spec_file = tmp_path / "SPEC-012.md"
    spec_file.write_text("# SPEC-012\nRequisito: campo novo no payload", encoding="utf-8")
    diffs_file = tmp_path / "diffs.patch"
    diffs_file.write_text("+    novo_campo: str = \"\"\n", encoding="utf-8")

    metric = RecordingMetric(scores=[0.3, 0.96, 0.96], oks=[False, True, True])
    mock_build_metric.return_value = metric
    mock_build_model.return_value = MagicMock()

    result = evaluate_spec_diff(
        spec_path=spec_file,
        diffs_path=diffs_file,
        model="agentic-qwen",
        fallback_model="agentic-qwen",
    )

    assert result.status == "APPROVED"
    assert metric.calls == 3
