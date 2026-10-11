"""Testes unitários da interface de linha de comando (CLI) e suas operações."""

from pathlib import Path

import pytest
from click.testing import CliRunner

from harness_state.cli import (
    main,
    run_init,
    run_plan,
    run_resume,
    run_status,
    run_update,
)
from harness_state.client import InMemoryStateStore
from harness_state.models import SpecRun, SubTask, TaskState


@pytest.mark.asyncio
async def test_run_init_creates_spec() -> None:
    """Business Rule: A operação de inicialização deve criar uma nova spec persistida."""
    store = InMemoryStateStore()
    await run_init("SPEC-010", "Feature 10", "author-1", store=store)

    saved = await store.get_spec("SPEC-010")
    assert saved is not None
    assert saved.title == "Feature 10"
    assert saved.author == "author-1"
    assert saved.status == TaskState.IN_PROGRESS


@pytest.mark.asyncio
async def test_run_status_displays_spec_info(capsys: pytest.CaptureFixture[str]) -> None:
    """Business Rule: A exibição de status deve renderizar os detalhes da especificação e suas tarefas."""
    store = InMemoryStateStore()
    spec = SpecRun(spec_id="SPEC-020", title="Feature 20", author="author-2")
    spec.add_task(SubTask(id="task-1", repo="repo-a", branch="feat/a", status=TaskState.IN_PROGRESS))
    await store.save_spec(spec)

    await run_status("SPEC-020", store=store)
    captured = capsys.readouterr().out
    assert "SPEC-020" in captured
    assert "Feature 20" in captured
    assert "task-1" in captured


@pytest.mark.asyncio
async def test_run_update_changes_task_status() -> None:
    """Business Rule: A atualização via CLI deve modificar o estado da tarefa e registrar o worker."""
    store = InMemoryStateStore()
    spec = SpecRun(spec_id="SPEC-030", title="Feature 30", author="author-3")
    spec.add_task(SubTask(id="task-1", repo="repo-a", branch="feat/a"))
    await store.save_spec(spec)

    await run_update("SPEC-030", "task-1", "READY", worker="worker-99", pr=55, store=store)

    updated = await store.get_spec("SPEC-030")
    assert updated is not None
    assert updated["task-1"].status == TaskState.READY
    assert updated["task-1"].last_worker == "worker-99"
    assert updated["task-1"].pr_number == 55


@pytest.mark.asyncio
async def test_run_plan_from_file(tmp_path: Path) -> None:
    """Business Rule: O comando plan deve conseguir carregar dados a partir de um arquivo de spec."""
    spec_file = tmp_path / "SPEC-040.md"
    spec_file.write_text("# Feature 40: Implement Distributed Flow\n\nDetalhes da especificação...", encoding="utf-8")

    store = InMemoryStateStore()
    await run_plan(spec_file=str(spec_file), spec_id=None, title=None, author="planner-agent", store=store)

    saved = await store.get_spec("SPEC-040")
    assert saved is not None
    assert "Feature 40" in saved.title


@pytest.mark.asyncio
async def test_run_resume_identifies_pending_task(capsys: pytest.CaptureFixture[str]) -> None:
    """Business Rule: O comando resume deve apontar a próxima tarefa pendente para o operador."""
    store = InMemoryStateStore()
    spec = SpecRun(spec_id="SPEC-050", title="Feature 50", author="author-5")
    spec.add_task(SubTask(id="task-1", repo="repo-a", branch="feat/spec-50", status=TaskState.PENDING))
    await store.save_spec(spec)

    await run_resume("SPEC-050", store=store)
    captured = capsys.readouterr().out
    assert "task-1" in captured
    assert "feat/spec-50" in captured


def test_click_cli_help() -> None:
    """Business Rule: A CLI principal deve listar todos os comandos disponíveis na ajuda."""
    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
    assert "status" in result.output
    assert "update" in result.output
    assert "plan" in result.output
    assert "resume" in result.output
