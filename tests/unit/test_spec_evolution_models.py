"""Testes unitários para os modelos de dados de evolução de especificações (SPEC-011)."""

from datetime import datetime

from harness_state.models import (
    CapabilitySyncResult,
    RevisionType,
    SpecEvolutionPlan,
    SpecMatch,
    SpecRevision,
    SpecRun,
    SubTask,
    TaskState,
)


def test_revision_type_enum_values() -> None:
    """Business Rule: RevisionType deve categorizar revisões em MINOR, MAJOR e PATCH."""
    assert RevisionType.MINOR_EVOLUTION == "MINOR_EVOLUTION"
    assert RevisionType.MAJOR_BREAKING == "MAJOR_BREAKING"
    assert RevisionType.PATCH_CORRECTION == "PATCH_CORRECTION"


def test_spec_revision_model_instantiation() -> None:
    """Business Rule: SpecRevision deve registrar dados imutáveis de uma revisão de spec."""
    rev = SpecRevision(
        revision_id="rev-001",
        spec_id="SPEC-011",
        version="1.1.0",
        revision_type=RevisionType.MINOR_EVOLUTION,
        author="eduardo",
        instruction="Adicionar motor de descoberta",
        frozen_task_ids=["task-1"],
        new_task_ids=["task-2", "task-3"],
        modified_contracts=["SpecDiscoveryEngine"],
    )
    assert rev.revision_id == "rev-001"
    assert rev.spec_id == "SPEC-011"
    assert rev.version == "1.1.0"
    assert rev.revision_type == RevisionType.MINOR_EVOLUTION
    assert rev.author == "eduardo"
    assert rev.frozen_task_ids == ["task-1"]
    assert rev.new_task_ids == ["task-2", "task-3"]
    assert rev.modified_contracts == ["SpecDiscoveryEngine"]
    assert isinstance(rev.created_at, datetime)


def test_spec_match_model_defaults() -> None:
    """Business Rule: SpecMatch deve conter informações de relevância e ação recomendada."""
    match = SpecMatch(
        spec_id="SPEC-008",
        title="Parser Unificado",
        file_path="specs/SPEC-008.md",
        similarity_score=0.85,
    )
    assert match.spec_id == "SPEC-008"
    assert match.similarity_score == 0.85
    assert match.recommended_action == "evolve"
    assert match.matched_capability == ""


def test_capability_sync_result_defaults() -> None:
    """Business Rule: CapabilitySyncResult reporta termos e contratos adicionados ao mapa."""
    result = CapabilitySyncResult(
        capability_id="agent-workflow-platform",
        updated=True,
        added_terms=["Living Specs"],
        added_specs=["SPEC-011"],
    )
    assert result.capability_id == "agent-workflow-platform"
    assert result.updated is True
    assert "Living Specs" in result.added_terms
    assert "SPEC-011" in result.added_specs


def test_spec_evolution_plan_structure() -> None:
    """Business Rule: SpecEvolutionPlan deve isolar tarefas congeladas das tarefas a executar."""
    t1 = SubTask(id="task-1", repo="repo/hub", branch="agent/t1", status=TaskState.APPROVED)
    t2 = SubTask(id="task-2", repo="repo/core", branch="agent/t2", status=TaskState.PENDING)
    plan = SpecEvolutionPlan(
        spec_id="SPEC-011",
        current_version="1.0.0",
        target_version="1.1.0",
        frozen_tasks=[t1],
        tasks_to_execute=[t2],
        affected_repositories=["repo/core"],
        has_breaking_changes=False,
    )
    assert len(plan.frozen_tasks) == 1
    assert len(plan.tasks_to_execute) == 1
    assert plan.current_version == "1.0.0"
    assert plan.target_version == "1.1.0"
    assert plan.has_breaking_changes is False


def test_spec_run_apply_evolution_preserves_frozen_and_resumes_in_progress() -> None:
    """Business Rule: apply_evolution deve congelar tarefas finalizadas e reabrir status para IN_PROGRESS."""
    t1 = SubTask(id="task-1", repo="repo/hub", branch="agent/t1", status=TaskState.APPROVED)
    spec = SpecRun(
        spec_id="SPEC-011",
        title="Living Specs",
        author="antigravity",
        status=TaskState.APPROVED,
        tasks={"task-1": t1},
        spec_version="1.0.0",
    )
    t2 = SubTask(id="task-2", repo="repo/core", branch="agent/t2", status=TaskState.PENDING)
    rev = SpecRevision(
        revision_id="rev-001",
        spec_id="SPEC-011",
        version="1.1.0",
        revision_type=RevisionType.MINOR_EVOLUTION,
        author="antigravity",
        instruction="Adicionar core",
        frozen_task_ids=["task-1"],
        new_task_ids=["task-2"],
    )

    spec.apply_evolution(new_version="1.1.0", revision=rev, new_subtasks=[t2])

    assert spec.spec_version == "1.1.0"
    assert len(spec.revisions) == 1
    assert spec.revisions[0].revision_id == "rev-001"
    assert len(spec.tasks) == 2
    assert spec["task-1"].status == TaskState.APPROVED
    assert spec["task-2"].status == TaskState.PENDING
    assert spec.status == TaskState.IN_PROGRESS


def test_spec_run_evolution_serialization_roundtrip() -> None:
    """Business Rule: SpecRun com revisões deve serializar e desserializar sem perda de dados."""
    spec = SpecRun(
        spec_id="SPEC-011",
        title="Living Specs",
        author="antigravity",
        author_agent="antigravity",
        author_model="gemini-2.5-pro",
        spec_version="1.1.0",
        capability_synced=True,
    )
    rev = SpecRevision(
        revision_id="rev-1",
        spec_id="SPEC-011",
        version="1.1.0",
        revision_type=RevisionType.MINOR_EVOLUTION,
        author="antigravity",
        instruction="Atualização",
    )
    spec.revisions.append(rev)

    dumped = spec.model_dump(mode="json")
    reloaded = SpecRun.model_validate(dumped)

    assert reloaded.spec_version == "1.1.0"
    assert reloaded.author_agent == "antigravity"
    assert reloaded.author_model == "gemini-2.5-pro"
    assert reloaded.capability_synced is True
    assert len(reloaded.revisions) == 1
    assert reloaded.revisions[0].version == "1.1.0"
