"""Testes unitários para o repositório de estado e protocolos de persistência."""

import pytest

from harness_state.client import (
    InMemoryStateStore,
    Settings,
    StateStore,
    StateStoreProtocol,
)
from harness_state.models import SpecRun, SubTask, TaskState


def test_protocol_implementation_compliance() -> None:
    """Business Rule: Tanto StateStore quanto InMemoryStateStore devem cumprir o StateStoreProtocol."""
    in_memory_store = InMemoryStateStore()
    redis_store = StateStore()

    assert isinstance(in_memory_store, StateStoreProtocol)
    assert isinstance(redis_store, StateStoreProtocol)


@pytest.mark.asyncio
async def test_in_memory_store_save_and_get() -> None:
    """Business Rule: InMemoryStateStore deve persistir e recuperar instâncias de SpecRun corretamente."""
    store = InMemoryStateStore()
    spec = SpecRun(spec_id="SPEC-100", title="Persist Test", author="tester")
    spec.add_task(SubTask(id="task-1", repo="core-repo", branch="main"))

    await store.save_spec(spec)
    retrieved = await store.get_spec("SPEC-100")

    assert retrieved is not None
    assert retrieved.spec_id == "SPEC-100"
    assert "task-1" in retrieved
    assert len(retrieved) == 1

    missing = await store.get_spec("NON-EXISTENT")
    assert missing is None


@pytest.mark.asyncio
async def test_in_memory_store_update_task_status() -> None:
    """Business Rule: Atualizar uma tarefa deve persistir o novo status e atualizar a spec global."""
    store = InMemoryStateStore()
    spec = SpecRun(spec_id="SPEC-200", title="Update Test", author="tester")
    spec.add_task(SubTask(id="task-1", repo="core-repo", branch="main"))
    await store.save_spec(spec)

    updated_spec = await store.update_task_status(
        spec_id="SPEC-200",
        task_id="task-1",
        status=TaskState.READY,
        worker_id="agent-07",
        pr_number=42,
    )

    assert updated_spec is not None
    assert updated_spec["task-1"].status == TaskState.READY
    assert updated_spec["task-1"].last_worker == "agent-07"
    assert updated_spec["task-1"].pr_number == 42
    assert updated_spec.status == TaskState.READY


@pytest.mark.asyncio
async def test_in_memory_store_context_manager() -> None:
    """Business Rule: O armazenamento de estado deve suportar o protocolo async context manager."""
    async with InMemoryStateStore() as store:
        spec = SpecRun(spec_id="SPEC-300", title="CM Test", author="tester")
        await store.save_spec(spec)
        found = await store.get_spec("SPEC-300")
        assert found is not None


@pytest.mark.asyncio
async def test_state_store_async_context_manager_close(monkeypatch: pytest.MonkeyPatch) -> None:
    """Business Rule: StateStore deve garantir o fechamento seguro de conexões ativas com o Redis ao sair do contexto."""
    closed = False

    class DummyRedisClient:
        async def aclose(self) -> None:
            nonlocal closed
            closed = True

    dummy_client = DummyRedisClient()
    store = StateStore(settings=Settings())
    store._client = dummy_client  # type: ignore[assignment]

    async with store:
        pass

    assert closed
