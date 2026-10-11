"""Testes unitários dos modelos e lógica de estado."""

import pytest
from harness_state.models import SpecRun, SubTask, TaskState


def test_spec_run_initialization():
    """Business Rule: Uma nova spec deve iniciar com status IN_PROGRESS e tarefas vazias."""
    spec = SpecRun(spec_id="SPEC-001", title="Test Feature", author="tester")
    assert spec.spec_id == "SPEC-001"
    assert spec.status == TaskState.IN_PROGRESS
    assert len(spec.tasks) == 0


def test_subtask_addition():
    """Business Rule: Subtarefas devem ser atribuídas a repositórios com status inicial PENDING."""
    task = SubTask(id="task-1", repo="paralax-evo-crm", branch="agent/spec-1")
    assert task.status == TaskState.PENDING
    assert task.pr_number is None
