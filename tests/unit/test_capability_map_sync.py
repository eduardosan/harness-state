"""Testes unitários para a sincronização do mapa de capacidades no Gate 2 (SPEC-011)."""

from pathlib import Path

import pytest

from harness_state.capabilities import (
    BusinessCapability,
    load_business_capability,
    save_business_capability,
)
from harness_state.spec.lifecycle import approve_spec, sync_capability_map_for_spec


@pytest.fixture
def hub_with_capability(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Cria estrutura de spec-hub com diretório de capabilities e uma spec rascunho."""
    hub_dir = tmp_path / "harness-spec-hub"
    hub_dir.mkdir(parents=True)
    specs_dir = hub_dir / "specs"
    specs_dir.mkdir(parents=True)
    cap_dir = hub_dir / "capabilities" / "agent-workflow-platform"
    cap_dir.mkdir(parents=True)

    # Cria capability.yaml inicial
    cap = BusinessCapability(
        version="1.0",
        capability_id="agent-workflow-platform",
        name="Agent Workflow Platform",
        scope="platform",
        description="Plataforma de orquestração de workflows SDD",
        ubiquitous_language={"SDD": "Spec-Driven Development"},
        specs=[],
    )
    cap_file = cap_dir / "capability.yaml"
    save_business_capability(cap, cap_file)

    # Cria spec rascunho
    spec_content = """---
spec_id: SPEC-011
title: "Atualização e Evolução Contínua de Specs"
product:
  - harness
capability: agent-workflow-platform
scope: platform
bounded_context: "SDD Lifecycle"
author_agent: antigravity
author_model: gemini-2.5-pro
status: DRAFT
---

# SPEC-011: Atualização e Evolução Contínua de Specs

## 1. Contexto e Motivação
### Linguagem Ubíqua
- **Living Specs:** Especificações que evoluem continuamente preservando histórico.
- **Frozen Task:** Subtarefa concluída cujo código de produção é preservado sem reexecução.

## 2. Escopo
- [ ] Task 1
"""
    spec_file = specs_dir / "SPEC-011-atualiza-spec.md"
    spec_file.write_text(spec_content, encoding="utf-8")

    return hub_dir, spec_file, cap_file


def test_sync_capability_map_for_spec_updates_specs_and_ubiquitous_language(
    hub_with_capability: tuple[Path, Path, Path],
) -> None:
    """Business Rule: sync_capability_map_for_spec deve adicionar a spec em specs e enriquecer a linguagem ubíqua."""
    hub_dir, spec_file, cap_file = hub_with_capability

    result = sync_capability_map_for_spec(
        spec_file=spec_file,
        author_agent="antigravity",
        workspace_root=hub_dir,
    )

    assert result.capability_id == "agent-workflow-platform"
    assert result.updated is True
    assert "SPEC-011" in result.added_specs
    assert result.sync_agent == "antigravity"

    # Verifica se capability.yaml foi gravado com as informações
    updated_cap = load_business_capability(cap_file)
    spec_entries = [s["spec_id"] for s in updated_cap.specs]
    assert "SPEC-011" in spec_entries

    # Verifica termos adicionados na linguagem ubíqua
    assert "Living Specs" in updated_cap.ubiquitous_language
    assert "Frozen Task" in updated_cap.ubiquitous_language


def test_approve_spec_triggers_capability_map_sync(
    hub_with_capability: tuple[Path, Path, Path],
) -> None:
    """Business Rule: approve_spec (Gate 2) deve transicionar status para APPROVED e sincronizar o mapa de capacidades."""
    hub_dir, spec_file, cap_file = hub_with_capability

    success = approve_spec(
        spec_file=spec_file,
        workspace_root=hub_dir,
        author_agent="antigravity",
    )
    assert success is True

    # Verifica transição de status no markdown
    content = spec_file.read_text(encoding="utf-8")
    assert "status: APPROVED" in content

    # Verifica sincronização da capability
    updated_cap = load_business_capability(cap_file)
    spec_ids = [s["spec_id"] for s in updated_cap.specs]
    assert "SPEC-011" in spec_ids
