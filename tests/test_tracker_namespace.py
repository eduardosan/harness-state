"""Testes do namespace por ecossistema no State Tracker (SPEC-005 C1)."""

import pytest

from harness_state.client import (
    InMemoryStateStore,
    parse_spec_reference,
    redis_spec_key,
)
from harness_state.models import SpecRun


def test_parse_spec_reference_with_namespace() -> None:
    """Business Rule: referência `harness/SPEC-PC-005` parseia namespace e spec_id."""
    assert parse_spec_reference("harness/SPEC-005") == (
        "harness",
        "SPEC-005",
    ), "referência com namespace deve ser separada"

def test_parse_spec_reference_without_namespace() -> None:
    """Business Rule: spec_id solto parseia namespace vazio (comportamento legado)."""
    assert parse_spec_reference("SPEC-005") == ("", "SPEC-005")


def test_redis_spec_key_with_namespace() -> None:
    """Business Rule: chaves Redis namespaced contêm `spec:{ecosistema}:{spec_id}`."""
    assert redis_spec_key("harness", "SPEC-005") == "spec:harness:SPEC-005"


def test_redis_spec_key_legacy() -> None:
    """Business Rule: sem namespace o spec_id retorna chave legado `spec:{spec_id}`."""
    assert redis_spec_key("", "SPEC-004") == "spec:SPEC-004"


@pytest.mark.asyncio
async def test_in_memory_store_namespaced_specs_are_isolated() -> None:
    """Business Rule: specs de ecossistemas diferentes com mesmo número não colidem."""
    store = InMemoryStateStore()
    await store.save_spec(SpecRun(spec_id="harness/SPEC-999", title="H", author="a"))
    await store.save_spec(SpecRun(spec_id="SPEC-999", title="P", author="b"))

    from_harness = await store.get_spec("harness/SPEC-999")
    from_legacy = await store.get_spec("SPEC-999")

    assert from_harness.title == "H" and from_legacy.title == "P"


@pytest.mark.asyncio
async def test_specs_with_same_id_and_different_ecosystems_do_not_collide() -> None:
    """Business Rule: dois namespaced com mesmo número ficam isolados namespace-a-namespace."""
    store = InMemoryStateStore()
    await store.save_spec(SpecRun(spec_id="harness/SPEC-001", title="H", author="a"))
    await store.save_spec(SpecRun(spec_id="paralax-ia/SPEC-001", title="P", author="a"))

    harness_spec = await store.get_spec("harness/SPEC-001")
    paralax_spec = await store.get_spec("paralax-ia/SPEC-001")

    assert harness_spec.title == "H"
    assert paralax_spec.title == "P"
