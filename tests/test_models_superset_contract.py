"""Contrato do bus compartilhado core↔flywheel (SPEC-009 §4).

O barramento Redis `spec:{id}` é lido/escrito pelos dois pacotes; o modelo
do core deve aceitar o JSON do flywheel (superset de campos) e serializar
de volta com as mesmas chaves — qualquer deriva quebra o fan-out e o
orchestrator em produção.
"""

from datetime import UTC, datetime

import pytest

from harness_state.models import SpecRun, SubTask, TaskState


def sample_spec_run_payload() -> dict[str, object]:
    """Corpo no formato exato emitido pelo flywheel.state.SpecRun.

    Returns:
        Dicionário serializável com todos os campos do contrato.
    """
    return {
        "spec_id": "SPEC-009",
        "title": "Migração total",
        "author": "harness-agent",
        "status": "IN_PROGRESS",
        "created_at": datetime.now(UTC).isoformat(),
        "correlation_uuid": None,
        "product": ["harness"],
        "capability": "agent-workflow-platform",
        "scope": "platform",
        "origin_module": "harness-state",
        "declared_status": "APPROVED",
        "prompts": ["harness/agent_instruction"],
        "hub_pr_number": 21,
        "hub_pr_url": "https://github.com/eduardosan/harness-spec-hub/pull/21",
        "tasks": {
            "task-1": {
                "id": "task-1",
                "repo": "eduardosan/agentic-flywheel",
                "branch": "agent/harness-spec-009-flywheel",
                "status": "READY",
                "pr_number": 175,
                "issue_number": 42,
                "issue_url": "https://github.com/eduardosan/harness-spec-hub/issues/42",
                "expected_version": "0.7.0",
                "sub_spec_path": "specs/SPEC-009.md",
                "last_worker": "runner-1",
                "wave": 1,
                "depends_on": [],
                "updated_at": datetime.now(UTC).isoformat(),
            }
        },
    }


def test_core_parsa_payload_no_formato_do_flywheel() -> None:
    """Business Rule: o modelo do core aceita integralmente o JSON do flywheel
    (campos DDD, hub PR, issue/expected_version) — contrato §4 da SPEC-009."""
    run = SpecRun.model_validate(sample_spec_run_payload())

    assert run.product == ["harness"]
    assert run.capability == "agent-workflow-platform"
    assert run.scope == "platform"
    assert run.origin_module == "harness-state"
    assert run.declared_status == "APPROVED"
    assert run.prompts == ["harness/agent_instruction"]
    assert run.hub_pr_number == 21
    task = run["task-1"]
    assert task.issue_number == 42
    assert task.expected_version == "0.7.0"


def test_payload_legado_sem_campos_novos_usa_defaults() -> None:
    """Business Rule: JSON antigo (pré-superset) continua válido com defaults
    idênticos aos do flywheel — rolling upgrade do barramento é seguro."""
    legacy = {
        "spec_id": "SPEC-001",
        "title": "Legado",
        "author": "op",
        "status": "IN_PROGRESS",
        "created_at": datetime.now(UTC).isoformat(),
        "tasks": {},
    }
    run = SpecRun.model_validate(legacy)

    assert run.scope == "platform"
    assert run.declared_status == "APPROVED"
    assert run.product == []
    assert run.prompts == []
    assert run.hub_pr_number is None


def test_round_trip_json_preserva_chaves_do_contrato() -> None:
    """Business Rule: a serialização do core produz JSON com TODAS as chaves
    do contrato — o StateStore do flywheel consegue validar de volta."""
    run = SpecRun.model_validate(sample_spec_run_payload())
    payload = run.model_dump(mode="json")
    subtask_payload = payload["tasks"]["task-1"]

    for key in (
        "product",
        "capability",
        "scope",
        "origin_module",
        "declared_status",
        "prompts",
        "hub_pr_number",
        "hub_pr_url",
    ):
        assert key in payload, key
    for key in ("issue_number", "issue_url", "expected_version"):
        assert key in subtask_payload, key

    again = SpecRun.model_validate_json(run.model_dump_json())
    assert again == run


def mk_task(task_id: str, wave: int, status: TaskState, deps: list[str]) -> SubTask:
    return SubTask(
        id=task_id,
        repo="eduardosan/x",
        branch=f"agent/{task_id}",
        status=status,
        wave=wave,
        depends_on=deps,
    )


def test_get_next_unblocked_task_ordena_por_wave_e_respeita_dependencias() -> None:
    """Business Rule: o escalonador retorna a primeira tarefa pendente cujas
    dependências estão READY/APPROVED, em ordem (wave, id) — paridade com o
    `get_next_unblocked_task` do flywheel que moveu o wave 2/6 para o core."""
    run = SpecRun(
        spec_id="SPEC-042",
        title="t",
        author="a",
        tasks={
            "t3": mk_task("t3", 2, TaskState.PENDING, ["t9"]),
            "t2": mk_task("t2", 2, TaskState.PENDING, ["t1"]),
            "t1": mk_task("t1", 1, TaskState.APPROVED, []),
        },
    )

    first = run.get_next_unblocked_task()
    assert first is not None
    assert first.id == "t2"

    # t1 em execução continua sendo a candidata do meio (ordem wave,id):
    # o escalonador prioriza retomar a onda raiz em andamento.
    run["t1"].status = TaskState.IN_PROGRESS
    resumed = run.get_next_unblocked_task()
    assert resumed is not None
    assert resumed.id == "t1"

    run["t1"].status = TaskState.APPROVED
    run["t2"].status = TaskState.APPROVED
    run["t3"].status = TaskState.APPROVED
    assert run.get_next_unblocked_task() is None


def test_metadados_invalidos_rejeitados_pelo_pydantic() -> None:
    """Business Rule: tipos do contrato são estritos (prompts lista de str;
    hub_pr_number inteiro) — lixo não entra no barramento silenciosamente."""
    bad = sample_spec_run_payload()
    bad["hub_pr_number"] = "não-é-inteiro-valido"
    with pytest.raises(ValueError):
        SpecRun.model_validate(bad)
