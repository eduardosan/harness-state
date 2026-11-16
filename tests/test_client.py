"""Testes unitários para o repositório de estado e protocolos de persistência."""

from pathlib import Path

import pytest

from harness_state.client import (
    InMemoryStateStore,
    Settings,
    StateStore,
    StateStoreProtocol,
    derive_hub_ecosystem,
    parse_spec_reference,
    redis_spec_key,
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
async def test_state_store_async_context_manager_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_derive_hub_ecosystem() -> None:
    """Business Rule: derive_hub_ecosystem extrai o ecossistema removendo o sufixo -spec-hub."""
    assert derive_hub_ecosystem(Path("/workspace/harness-spec-hub")) == "harness"
    assert derive_hub_ecosystem(Path("paralax-spec-hub")) == "paralax"
    assert derive_hub_ecosystem(Path("outro-hub")) == "outro-hub"


@pytest.mark.asyncio
async def test_in_memory_store_update_task_status_kwargs_completos() -> None:
    """Business Rule: InMemoryStateStore propaga expected_version, issue_number e issue_url."""
    store = InMemoryStateStore()
    spec = SpecRun(spec_id="SPEC-201", title="Full Kwargs Test", author="tester")
    spec.add_task(SubTask(id="task-1", repo="core-repo", branch="main"))
    await store.save_spec(spec)

    updated_spec = await store.update_task_status(
        spec_id="SPEC-201",
        task_id="task-1",
        status=TaskState.READY,
        worker_id="agent-07",
        pr_number=42,
        expected_version="0.8.0",
        issue_number=101,
        issue_url="https://github.com/eduardosan/hub/issues/101",
    )

    assert updated_spec is not None
    task = updated_spec["task-1"]
    assert task.expected_version == "0.8.0"
    assert task.issue_number == 101
    assert task.issue_url == "https://github.com/eduardosan/hub/issues/101"


@pytest.mark.asyncio
async def test_state_store_reconnect_hook_e_client_factory() -> None:
    """Business Rule: StateStore suporta hook de reconexão e client_factory para injeção de dependência."""
    hook_called = False

    def dummy_hook() -> bool:
        nonlocal hook_called
        hook_called = True
        return True

    class MockRedis:
        def __init__(self) -> None:
            self.store: dict[str, str] = {}
            self.calls = 0

        async def get(self, key: str) -> str | None:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("Simulated disconnect")
            return self.store.get(key)

        async def aclose(self) -> None:
            pass

    mock_client = MockRedis()
    mock_client.store["spec:SPEC-300"] = SpecRun(
        spec_id="SPEC-300", title="Retry Test", author="tester"
    ).model_dump_json()

    store = StateStore(
        reconnect_hook=dummy_hook,
        client_factory=lambda: mock_client,  # type: ignore[return-value]
        max_retries=2,
        retry_delay=0.01,
    )

    retrieved = await store.get_spec("SPEC-300")
    assert retrieved is not None
    assert retrieved.spec_id == "SPEC-300"
    assert hook_called is True


def test_harness_state_re_exports_em_state_module() -> None:
    """Business Rule: harness_state.state deve re-exportar os modelos e clientes canônicos (SPEC-009 §3 Onda 1)."""
    import harness_state.state as hs_state

    assert hs_state.SpecRun is SpecRun
    assert hs_state.SubTask is SubTask
    assert hs_state.TaskState is TaskState
    assert hs_state.StateStore is StateStore
    assert hs_state.InMemoryStateStore is InMemoryStateStore
    assert hs_state.StateStoreProtocol is StateStoreProtocol
    assert hs_state.Settings is Settings
    assert hs_state.parse_spec_reference is parse_spec_reference
    assert hs_state.redis_spec_key is redis_spec_key
    assert hs_state.derive_hub_ecosystem is derive_hub_ecosystem
