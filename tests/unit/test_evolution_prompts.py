"""Testes unitários para os prompts canônicos de evolução de specs (SPEC-011)."""

from harness_state.runtimes.coder_prompts import (
    ARCHITECT_SPEC_DISCOVERY_INSTRUCTION,
    ARCHITECT_SPEC_EVOLUTION_INSTRUCTION,
    CAPABILITY_MAP_SYNC_INSTRUCTION,
    CODER_CODE_EVOLUTION_INSTRUCTION,
)


def test_architect_spec_discovery_prompt_content() -> None:
    """Business Rule: ARCHITECT_SPEC_DISCOVERY_INSTRUCTION deve conter o protocolo de descoberta semântica no catálogo de specs."""
    assert "CATALOG SCAN" in ARCHITECT_SPEC_DISCOVERY_INSTRUCTION
    assert "SEMANTIC CORRELATION" in ARCHITECT_SPEC_DISCOVERY_INSTRUCTION
    assert "ROUTING DECISION" in ARCHITECT_SPEC_DISCOVERY_INSTRUCTION
    assert "STRUCTURED OUTPUT" in ARCHITECT_SPEC_DISCOVERY_INSTRUCTION
    assert "specs/SPEC-*.md" in ARCHITECT_SPEC_DISCOVERY_INSTRUCTION


def test_architect_spec_evolution_prompt_content() -> None:
    """Business Rule: ARCHITECT_SPEC_EVOLUTION_INSTRUCTION deve orientar a preservação de tarefas concluídas e atualização de contratos."""
    assert "PRESERVE COMPLETED WORK" in ARCHITECT_SPEC_EVOLUTION_INSTRUCTION
    assert "CONTINUOUS SPEC EVOLUTION" in ARCHITECT_SPEC_EVOLUTION_INSTRUCTION
    assert "CONTRACT INTEGRITY" in ARCHITECT_SPEC_EVOLUTION_INSTRUCTION
    assert "SPEC REVISION TRACKING" in ARCHITECT_SPEC_EVOLUTION_INSTRUCTION


def test_coder_code_evolution_prompt_content() -> None:
    """Business Rule: CODER_CODE_EVOLUTION_INSTRUCTION deve exigir TDD Fail-First e zero regressão no runtime do coder."""
    assert "BASELINE INSPECTION" in CODER_CODE_EVOLUTION_INSTRUCTION
    assert "TDD FAIL-FIRST" in CODER_CODE_EVOLUTION_INSTRUCTION
    assert "ZERO REGRESSION" in CODER_CODE_EVOLUTION_INSTRUCTION
    assert "QUALITY INVARIANTS" in CODER_CODE_EVOLUTION_INSTRUCTION


def test_capability_map_sync_prompt_content() -> None:
    """Business Rule: CAPABILITY_MAP_SYNC_INSTRUCTION deve instruir o agente autor a sincronizar o mapa de capacidades no Gate 2."""
    assert "SPEC CONTEXT REVIEW" in CAPABILITY_MAP_SYNC_INSTRUCTION
    assert "CAPABILITY DISCOVERY" in CAPABILITY_MAP_SYNC_INSTRUCTION
    assert "MAP RECONCILIATION" in CAPABILITY_MAP_SYNC_INSTRUCTION
    assert "DETERMINISTIC DIFF" in CAPABILITY_MAP_SYNC_INSTRUCTION
