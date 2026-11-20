"""Testes unitários para o motor de descoberta prévia de especificações (SPEC-011)."""

from pathlib import Path

import pytest

from harness_state.spec.discovery import SpecDiscoveryEngine


@pytest.fixture
def sample_specs_dir(tmp_path: Path) -> Path:
    """Cria um diretório temporário de specs simulando o spec-hub."""
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    # SPEC-008: Parser Unificado
    spec_008_content = """---
spec_id: SPEC-008
title: "Spec Parser Unificado e Roteamento de Subtarefas"
product:
  - harness
capability: agent-workflow-platform
scope: platform
bounded_context: "Parser semântico de subtarefas e AST de especificações SDD"
origin_module: harness-state
status: IMPLEMENTED
---

# SPEC-008: Spec Parser Unificado e Roteamento de Subtarefas

## 1. Contexto e Motivação
Módulo de parsing para extrair subtarefas em formato canônico a partir de especificações Markdown.
Contratos de AST e extração de blocos de tarefas.
"""
    (specs_dir / "SPEC-008-spec-parser-unificado.md").write_text(
        spec_008_content, encoding="utf-8"
    )

    # SPEC-010: Pydantic AI Coder Runtime
    spec_010_content = """---
spec_id: SPEC-010
title: "Pydantic AI Coder Runtime"
product:
  - harness
capability: agent-workflow-platform
scope: platform
bounded_context: "Runtime autônomo de codificação baseado em Pydantic AI"
origin_module: harness-state
status: IMPLEMENTED
---

# SPEC-010: Pydantic AI Coder Runtime

## 1. Contexto e Motivação
Execução de agentes de codificação em malha fechada via Pydantic AI.
"""
    (specs_dir / "SPEC-010-pydantic-ai-coder-runtime.md").write_text(
        spec_010_content, encoding="utf-8"
    )

    # Template (deve ser ignorado)
    (specs_dir / "SPEC-TEMPLATE.md").write_text(
        "---\nspec_id: SPEC-XXX\ntitle: Template\n---\n# Template", encoding="utf-8"
    )

    return specs_dir


def test_discover_related_specs_high_similarity_redirects_to_evolution(
    sample_specs_dir: Path,
) -> None:
    """Business Rule: Query com alta similaridade semântica (>= 0.8) deve recomendar evolução da spec existente."""
    engine = SpecDiscoveryEngine(specs_dir=sample_specs_dir)
    matches = engine.discover_related_specs(
        query_title_or_prompt="Melhorar parser para suportar formato YAML de subtarefas",
        threshold=0.6,
    )

    assert len(matches) >= 1
    top_match = matches[0]
    assert top_match.spec_id == "SPEC-008"
    assert top_match.similarity_score >= 0.75
    assert top_match.recommended_action == "evolve"
    assert "parser" in top_match.title.lower()


def test_discover_related_specs_exact_spec_id_mention(
    sample_specs_dir: Path,
) -> None:
    """Business Rule: Menção explícita ao ID da spec (ex: SPEC-008) deve resultar em score máximo (1.0)."""
    engine = SpecDiscoveryEngine(specs_dir=sample_specs_dir)
    matches = engine.discover_related_specs(
        query_title_or_prompt="Refatoração de SPEC-008 com novas regras",
        threshold=0.5,
    )

    assert len(matches) >= 1
    top_match = matches[0]
    assert top_match.spec_id == "SPEC-008"
    assert top_match.similarity_score == 1.0
    assert top_match.recommended_action == "evolve"


def test_discover_related_specs_low_similarity_allows_new_spec(
    sample_specs_dir: Path,
) -> None:
    """Business Rule: Query sem correspondência com specs existentes deve retornar lista vazia no threshold."""
    engine = SpecDiscoveryEngine(specs_dir=sample_specs_dir)
    matches = engine.discover_related_specs(
        query_title_or_prompt="Gateway de pagamentos Pix assíncrono para checkout",
        threshold=0.5,
    )

    assert len(matches) == 0


def test_discover_related_specs_with_target_capability_boost(
    sample_specs_dir: Path,
) -> None:
    """Business Rule: Declarar a mesma target_capability deve aumentar o score de similaridade."""
    engine = SpecDiscoveryEngine(specs_dir=sample_specs_dir)
    matches_without_cap = engine.discover_related_specs(
        query_title_or_prompt="Agente autônomo coder",
        threshold=0.3,
    )
    matches_with_cap = engine.discover_related_specs(
        query_title_or_prompt="Agente autônomo coder",
        target_capability="agent-workflow-platform",
        threshold=0.3,
    )

    assert len(matches_with_cap) >= 1
    assert matches_with_cap[0].spec_id == "SPEC-010"
    if matches_without_cap:
        assert matches_with_cap[0].similarity_score >= matches_without_cap[0].similarity_score


def test_discover_related_specs_handles_non_existent_directory(tmp_path: Path) -> None:
    """Business Rule: Diretório de specs inexistente deve retornar lista vazia sem lançar exceção."""
    non_existent = tmp_path / "does_not_exist"
    engine = SpecDiscoveryEngine(specs_dir=non_existent)
    matches = engine.discover_related_specs("Qualquer busca")
    assert matches == []
