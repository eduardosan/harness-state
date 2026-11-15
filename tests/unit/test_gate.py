"""Testes unitários para o fechamento transacional do Cross-Repo Gate."""

from unittest.mock import MagicMock, patch

from harness_state.contracts import ContractValidationResult
from harness_state.gate import (
    TransactionalGateClosure,
    dispatch_cross_repo_gate,
    run_gate_cli,
    trigger_gate_if_ready,
)


class MockGateGitHubClient:
    """Mock de cliente GitHub para simular operações do gate."""

    def __init__(self) -> None:
        """Inicializa estruturas de rastreamento do mock."""
        self.merged_prs: list[tuple[str, int, str]] = []
        self.labels_added: dict[str, list[str]] = {}
        self.comments: dict[str, list[str]] = {}
        self.closed_issues: list[tuple[str, int, str | None]] = []

    def add_label(self, repo: str, pr_number: int, label: str) -> None:
        """Simula adição de label a um PR."""
        self.labels_added.setdefault(f"{repo}#{pr_number}", []).append(label)

    def merge_pr(self, repo: str, pr_number: int, merge_method: str = "squash") -> bool:
        """Simula merge bem-sucedido de um PR."""
        self.merged_prs.append((repo, pr_number, merge_method))
        return True

    def comment_pr(self, repo: str, pr_number: int, comment: str) -> None:
        """Simula comentário em um PR."""
        self.comments.setdefault(f"{repo}#{pr_number}", []).append(comment)

    def close_issue(
        self, repo: str, issue_number: int, comment: str | None = None
    ) -> bool:
        """Simula fechamento de uma issue."""
        self.closed_issues.append((repo, issue_number, comment))
        return True


def test_gate_closure_approval() -> None:
    """Business Rule: Com Judge e Contratos OK, PRs são mergeados."""
    mock_client = MockGateGitHubClient()
    closure = TransactionalGateClosure(
        github_client=mock_client,
        spec_hub_repo="paralax-ia/paralax-spec-hub",
        hub_pr_number=5,
    )

    contract_result = ContractValidationResult(
        valid=True,
        errors=[],
        endpoints=["/crm/health"],
        schemas=["HealthStatus"],
    )

    tasks_info = [
        {"repo": "paralax-ia/paralax-evo-crm", "pr_number": 8, "task_id": "task-1"},
        {
            "repo": "paralax-ia/customer-support-vehicles",
            "pr_number": 7,
            "task_id": "task-2",
        },
    ]

    result = closure.execute(
        spec_id="SPEC-001-crm-healthcheck",
        judge_status="APPROVED",
        judge_score=0.95,
        judge_reason="Conformidade estrita com todos os requisitos.",
        contract_result=contract_result,
        tasks_info=tasks_info,
    )

    assert result.decision == "APPROVED"
    assert result.all_merged is True

    # Verifica se os spokes receberam a label harness-approved
    crm_labels = mock_client.labels_added.get("paralax-ia/paralax-evo-crm#8", [])
    assert "harness-approved" in crm_labels

    veh_key = "paralax-ia/customer-support-vehicles#7"
    vehicles_labels = mock_client.labels_added.get(veh_key, [])
    assert "harness-approved" in vehicles_labels

    # Verifica se os PRs foram mergeados
    merged_repos = [item[0] for item in mock_client.merged_prs]
    assert "paralax-ia/paralax-evo-crm" in merged_repos
    assert "paralax-ia/customer-support-vehicles" in merged_repos

    # Verifica se o PR da spec no hub foi mergeado
    assert "paralax-ia/paralax-spec-hub" in merged_repos


def test_gate_closure_rejection() -> None:
    """Business Rule: Quando Judge reprova, PRs recebem feedback sem merge."""
    mock_client = MockGateGitHubClient()
    closure = TransactionalGateClosure(
        github_client=mock_client,
        spec_hub_repo="paralax-ia/paralax-spec-hub",
        hub_pr_number=5,
    )

    contract_result = ContractValidationResult(
        valid=False,
        errors=["Contrato /crm/health ausente no spoke"],
    )

    tasks_info = [
        {"repo": "paralax-ia/paralax-evo-crm", "pr_number": 8, "task_id": "task-1"},
    ]

    result = closure.execute(
        spec_id="SPEC-001-crm-healthcheck",
        judge_status="FAILED",
        judge_score=0.40,
        judge_reason="Faltou método assíncrono.",
        contract_result=contract_result,
        tasks_info=tasks_info,
    )

    assert result.decision == "FAILED"
    assert result.all_merged is False
    assert len(mock_client.merged_prs) == 0

    # Verifica se comentário com feedback prescritivo foi postado
    hub_comments = mock_client.comments.get("paralax-ia/paralax-spec-hub#5", [])
    assert len(hub_comments) > 0
    assert "Faltou método assíncrono" in hub_comments[0]


def test_dispatch_cross_repo_gate_success() -> None:
    """Business Rule: Disparo do gate emite repository_dispatch via gh CLI."""
    mock_proc = MagicMock(returncode=0, stdout="", stderr="")

    with patch("subprocess.run", return_value=mock_proc) as mock_run:
        success = dispatch_cross_repo_gate(
            spec_id="SPEC-001",
            hub_repo="paralax-ia/paralax-spec-hub",
            flywheel_repo="eduardosan/agentic-flywheel",
            token="ghp_fake_token",
        )

    assert success is True
    assert mock_run.called
    cmd_called = mock_run.call_args[0][0]
    assert "api" in cmd_called
    assert "repos/eduardosan/agentic-flywheel/dispatches" in cmd_called
    assert "event_type=cross-repo-gate" in cmd_called


def test_trigger_gate_if_ready_calls_dispatch() -> None:
    """Business Rule: Orquestrador dispara dispatch quando a spec está pronta."""
    with (
        patch("harness_state.gate.is_spec_ready_for_gate", return_value=True),
        patch(
            "harness_state.gate.dispatch_cross_repo_gate", return_value=True
        ) as mock_dispatch,
    ):
        triggered = trigger_gate_if_ready(
            spec_id="SPEC-001",
            hub_repo="paralax-ia/paralax-spec-hub",
            flywheel_repo="eduardosan/agentic-flywheel",
        )

    assert triggered is True
    assert mock_dispatch.called


def test_run_gate_cli_trigger_if_ready() -> None:
    """Business Rule: CLI run_gate_cli encaminha subcomando trigger-if-ready."""
    with patch(
        "harness_state.gate.trigger_gate_if_ready", return_value=True
    ) as mock_trigger:
        run_gate_cli(["trigger-if-ready", "--spec-id", "SPEC-999"])

    assert mock_trigger.called
    assert mock_trigger.call_args[1]["spec_id"] == "SPEC-999"


def test_gate_closure_promotes_prompts_to_production() -> None:
    """Business Rule: Gate 5 promove prompts vinculados à spec para 'production'."""
    mock_client = MockGateGitHubClient()
    closure = TransactionalGateClosure(
        github_client=mock_client,
        spec_hub_repo="paralax-ia/paralax-spec-hub",
    )
    contract_result = ContractValidationResult(valid=True)
    tasks_info = [
        {"repo": "paralax-ia/paralax-support", "pr_number": 21, "task_id": "task-1"}
    ]

    mock_mgr = MagicMock()
    mock_mgr.is_configured = True

    with patch(
        "harness_state.prompt_manager.LangfusePromptManager",
        return_value=mock_mgr,
    ):
        result = closure.execute(
            spec_id="SPEC-004",
            judge_status="APPROVED",
            judge_score=1.0,
            judge_reason="100% dos requisitos validados",
            contract_result=contract_result,
            tasks_info=tasks_info,
            prompts=["paralax/support", "paralax/support/pipeline_classifier"],
        )

    assert result.decision == "APPROVED"
    assert result.all_merged is True
    assert result.prompts_promoted == [
        "paralax/support",
        "paralax/support/pipeline_classifier",
    ]
    assert mock_mgr.promote_to_production.call_count == 2
    mock_mgr.promote_to_production.assert_any_call("paralax/support")
    mock_mgr.promote_to_production.assert_any_call(
        "paralax/support/pipeline_classifier"
    )
