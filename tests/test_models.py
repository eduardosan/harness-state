"""Testes unitários dos modelos e lógica de domínio do estado."""

import pytest

from harness_state.models import SpecRun, SubTask, TaskState


def test_spec_run_initialization() -> None:
    """Business Rule: Uma nova spec deve iniciar com status IN_PROGRESS e tarefas vazias."""
    spec = SpecRun(spec_id="SPEC-001", title="Test Feature", author="tester")
    assert spec.spec_id == "SPEC-001"
    assert spec.status == TaskState.IN_PROGRESS
    assert len(spec) == 0
    assert not spec.is_complete


def test_subtask_addition() -> None:
    """Business Rule: Subtarefas devem ser atribuídas com status inicial PENDING."""
    task = SubTask(id="task-1", repo="paralax-evo-crm", branch="agent/spec-1")
    assert task.status == TaskState.PENDING
    assert task.pr_number is None
    assert task.last_worker is None


def test_spec_dunder_container_methods() -> None:
    """Business Rule: SpecRun deve se comportar como um contêiner Python idiomático (len, getitem, in, iter)."""
    spec = SpecRun(spec_id="SPEC-002", title="Container Test", author="tester")
    task1 = SubTask(id="task-1", repo="repo-a", branch="feat/a")
    task2 = SubTask(id="task-2", repo="repo-b", branch="feat/b")

    spec.add_task(task1)
    spec.add_task(task2)

    assert len(spec) == 2
    assert "task-1" in spec
    assert "task-2" in spec
    assert "task-unknown" not in spec
    assert spec["task-1"] == task1
    assert spec["task-2"] == task2

    tasks_from_iter = list(spec)
    assert tasks_from_iter == [task1, task2]


def test_spec_getitem_missing_raises_key_error() -> None:
    """Business Rule: Acessar uma subtarefa inexistente via colchetes deve disparar KeyError."""
    spec = SpecRun(spec_id="SPEC-003", title="Missing Task", author="tester")
    with pytest.raises(KeyError):
        _ = spec["non-existent"]


def test_spec_domain_completion_status() -> None:
    """Business Rule: Uma especificação atinge status READY quando todas as subtarefas forem concluídas."""
    spec = SpecRun(spec_id="SPEC-004", title="Completion Test", author="tester")
    task1 = SubTask(id="task-1", repo="repo-a", branch="feat/a")
    task2 = SubTask(id="task-2", repo="repo-b", branch="feat/b")
    spec.add_task(task1)
    spec.add_task(task2)

    assert not spec.is_complete
    assert len(spec.pending_tasks) == 2

    spec.update_task_status("task-1", TaskState.READY, worker_id="worker-1", pr_number=10)
    assert not spec.is_complete
    assert spec.status == TaskState.IN_PROGRESS
    assert len(spec.pending_tasks) == 1

    spec.update_task_status("task-2", TaskState.APPROVED, worker_id="worker-2", pr_number=11)
    assert spec.is_complete
    assert spec.status == TaskState.READY
    assert len(spec.pending_tasks) == 0


def test_spec_repr_output() -> None:
    """Business Rule: O __repr__ de SpecRun deve ser conciso e descritivo para depuração."""
    spec = SpecRun(spec_id="SPEC-005", title="Repr Test", author="tester")
    output = repr(spec)
    assert "SPEC-005" in output
    assert "IN_PROGRESS" in output
