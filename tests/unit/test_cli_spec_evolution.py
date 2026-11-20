"""Testes unitários para os comandos CLI de evolução e descoberta de specs (SPEC-011)."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from harness_state.cli import main


@pytest.fixture
def cli_specs_dir(tmp_path: Path) -> Path:
    """Cria diretório de specs para testes de CLI."""
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    spec_content = """---
spec_id: SPEC-008
title: "Spec Parser Unificado e Roteamento de Subtarefas"
spec_version: "1.0.0"
product:
  - harness
capability: agent-workflow-platform
scope: platform
bounded_context: "Parser semântico de subtarefas e AST de especificações SDD"
target_repositories:
  - repo: eduardosan/harness-state
    wave: 1
    role: core
status: IN_PROGRESS
---

# SPEC-008: Spec Parser Unificado

## 2. Escopo e Repositórios Afetados
- [x] **Sub-tarefa 1 (`eduardosan/harness-state`):** [Onda 1] Core parser.
"""
    (specs_dir / "SPEC-008-spec-parser-unificado.md").write_text(
        spec_content, encoding="utf-8"
    )
    return specs_dir


def test_cli_plan_discovers_existing_spec_and_suggests_evolution(
    cli_specs_dir: Path,
) -> None:
    """Business Rule: harness plan ou harness spec plan deve inspecionar specs existentes e sugerir evolução para queries correlacionadas."""
    runner = CliRunner()
    result = runner.invoke(
        main,
        [
            "plan",
            "--title",
            "Melhorar parser para suportar formato YAML de subtarefas",
            "--specs-dir",
            str(cli_specs_dir),
        ],
    )

    assert result.exit_code == 0
    assert "SPEC-008" in result.output
    assert "Spec existente identificada" in result.output
    assert "harness spec update" in result.output


def test_cli_plan_force_new_bypasses_discovery_suggestion(
    cli_specs_dir: Path,
) -> None:
    """Business Rule: A flag --force-new deve contornar a sugestão de evolução e prosseguir com novo plano."""
    runner = CliRunner()
    with patch("harness_state.cli.StateStore") as mock_store_cls:
        mock_store = AsyncMock()
        mock_store.get_spec.return_value = None
        mock_store.__aenter__.return_value = mock_store
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            main,
            [
                "plan",
                "--title",
                "Melhorar parser para suportar formato YAML de subtarefas",
                "--spec-id",
                "SPEC-099",
                "--specs-dir",
                str(cli_specs_dir),
                "--force-new",
            ],
        )

        assert result.exit_code == 0
        assert "registrado com sucesso" in result.output


def test_cli_spec_update_evolves_spec_and_bumps_version(
    cli_specs_dir: Path,
) -> None:
    """Business Rule: harness spec update deve analisar o delta, incrementar a versão e congelar tarefas concluídas."""
    runner = CliRunner()
    spec_file = cli_specs_dir / "SPEC-008-spec-parser-unificado.md"

    with patch("harness_state.cli.StateStore") as mock_store_cls:
        mock_store = AsyncMock()
        mock_store.get_spec.return_value = None
        mock_store.__aenter__.return_value = mock_store
        mock_store_cls.return_value = mock_store

        result = runner.invoke(
            main,
            [
                "spec",
                "update",
                str(spec_file),
                "-p",
                "Adicionar suporte a YAML de subtarefas",
                "--specs-dir",
                str(cli_specs_dir),
            ],
        )

        assert result.exit_code == 0
        assert "SPEC-008" in result.output
        assert "evoluída para versão 1.1.0" in result.output

        content = spec_file.read_text(encoding="utf-8")
        assert "1.1.0" in content
        assert "Adicionar suporte a YAML de subtarefas" in content
