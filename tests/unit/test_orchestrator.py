"""Testes unitários para o motor de orquestração por ondas (SDD)."""

import asyncio
from pathlib import Path
from unittest.mock import patch

import pytest

from harness_state.client import InMemoryStateStore
from harness_state.judge import JudgeEvaluation
from harness_state.models import SpecRun, SubTask, TaskState
from harness_state.orchestrator import (
    HarnessOrchestrator,
    extract_initial_subtasks,
    parse_spec_with_waves,
)


@pytest.fixture(autouse=True)
def fake_issue_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Business Rule: pipelines de teste não exercem gh real de criação de issue."""
    monkeypatch.setattr(
        "harness_state.orchestrator.ensure_task_issue",
        lambda *args, **kwargs: (None, None),
    )


def make_rejected_judge_evaluation(
    spec_path: Path, diffs_path: Path, spec_id: str
) -> JudgeEvaluation:
    """Retorna avaliação reprovada para testes de Gate 5."""
    return JudgeEvaluation(
        spec_id=spec_id,
        compliance_score=75,
        status="REJECTED",
        summary="Faltou método assíncrono.",
        violations=["Método síncrono"],
        recommendations=["Converter método para assíncrono"],
    )


def test_parse_spec_with_waves_extracts_frontmatter_and_calculates_waves(
    tmp_path: Path,
) -> None:
    """Business Rule: Leitura da spec extrai produtos, capabilities e calcula ondas."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "SPEC-004-vendas.md"

    spec_content = """---
spec_id: SPEC-004
title: Pipeline Comercial Automatizado
product:
  - paralax-support
capability: crm
scope: platform
target_repositories:
  - repo: paralax-ia/paralax-evo-crm
    wave: 1
    role: sdk
  - repo: paralax-ia/customer-support-vehicles
    wave: 2
    role: ai-agent
status: APPROVED
---
# SPEC-004: Pipeline Comercial Automatizado
## Contexto
Descrição aqui.
"""
    spec_file.write_text(spec_content, encoding="utf-8")

    manifest_file = tmp_path / "manifest.yaml"
    manifest_content = """version: '1.0'
repositories:
  - name: paralax-evo-crm
    repo: paralax-ia/paralax-evo-crm
    depends_on: []
  - name: customer-support-vehicles
    repo: paralax-ia/customer-support-vehicles
    depends_on:
      - paralax-evo-crm
"""
    manifest_file.write_text(manifest_content, encoding="utf-8")

    spec_run = parse_spec_with_waves(spec_file, manifest_path=manifest_file)

    assert spec_run.spec_id == "SPEC-004"
    assert spec_run.title == "Pipeline Comercial Automatizado"
    assert spec_run.product == ["paralax-support"]
    assert spec_run.capability == "crm"
    assert len(spec_run.tasks) == 2
    assert spec_run.tasks["task-1"].wave == 1
    assert spec_run.tasks["task-2"].wave == 2
    assert "task-1" in spec_run.tasks["task-2"].depends_on


def test_parse_spec_with_waves_replaces_dummy_module_name(tmp_path: Path) -> None:
    """Business Rule: Substitui placeholder 'module-name' pelo nome real do spoke."""
    module_dir = tmp_path / "customer-support-vehicles"
    spec_dir = module_dir / "specs"
    spec_dir.mkdir(parents=True)
    spec_file = spec_dir / "SPEC-001.md"

    spec_content = """---
spec_id: SPEC-001
title: Funcionalidade Local
target_repositories:
  - repo: paralax-ia/module-name
    wave: 1
---
# SPEC-001
"""
    spec_file.write_text(spec_content, encoding="utf-8")

    spec_run = parse_spec_with_waves(spec_file)

    assert len(spec_run.tasks) == 1
    task = spec_run.tasks["task-1"]
    assert task.repo == "paralax-ia/customer-support-vehicles"
    assert "customer-support-vehicles" in task.branch


def test_extract_initial_subtasks_fallback_branch_namespaced() -> None:
    """Business Rule: Fallback sem target_repositories gera branch com namespace."""
    subtasks = extract_initial_subtasks(
        frontmatter={},
        body="# SPEC-001: Exemplo",
        spec_id="SPEC-001",
        origin_module="my-service",
        file_path=Path("SPEC-001.md"),
        ecosystem="harness",
    )
    assert len(subtasks) == 1
    assert subtasks["task-1"].branch == "agent/harness-spec-001-my-service"


def test_extract_initial_subtasks_frontmatter_branch_namespaced() -> None:
    """Business Rule: Repositórios declarados recebem prefixo do ecossistema na branch."""
    frontmatter = {
        "target_repositories": [
            {"repo": "paralax-ia/crm-api", "wave": 1},
        ]
    }
    subtasks = extract_initial_subtasks(
        frontmatter=frontmatter,
        body="",
        spec_id="SPEC-002",
        origin_module="crm-api",
        file_path=Path("SPEC-002.md"),
        ecosystem="harness",
    )
    assert subtasks["task-1"].branch == "agent/harness-spec-002-crm-api"


def test_orchestrator_blocks_when_spec_is_draft_gate_2(tmp_path: Path) -> None:
    """Business Rule: Spec em status DRAFT bloqueia execução (Gate 2 pendente)."""
    mod_dir = tmp_path / "module"
    mod_dir.mkdir()
    (mod_dir / "pyproject.toml").write_text(
        "[project]\nname = 'draft-mod'\nversion = '0.1.0'\n", encoding="utf-8"
    )

    spec_file = mod_dir / "specs" / "SPEC-005.md"
    spec_file.parent.mkdir(parents=True)
    spec_file.write_text(
        """---
spec_id: SPEC-005
title: "Funcionalidade em Rascunho"
status: DRAFT
target_repositories:
  - repo: paralax-ia/draft-mod
    wave: 1
---
# SPEC-005: Rascunho
""",
        encoding="utf-8",
    )

    store = InMemoryStateStore()
    orchestrator = HarnessOrchestrator(
        project_root=mod_dir,
        store=store,
        verify_runner=lambda _: (0, "OK"),
    )

    outcome = asyncio.run(orchestrator.run_pipeline(spec_path=spec_file))
    assert outcome.is_draft_blocked is True
    assert outcome.task_status == TaskState.PENDING


def test_closure_gate_blocks_when_judge_rejects(tmp_path: Path) -> None:
    """Business Rule: Se o Judge reprova (REJECTED), o Gate 5 bloqueia fechamento."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    spec_file = spec_dir / "SPEC-004.md"
    spec_file.write_text(
        "---\n"
        "spec_id: SPEC-004\n"
        "title: Pipeline\n"
        "target_repositories:\n"
        "  - repo: paralax-ia/crm\n"
        "    wave: 1\n"
        "---\n"
        "# SPEC\n",
        encoding="utf-8",
    )

    store = InMemoryStateStore()
    subtask = SubTask(
        id="task-1",
        repo="paralax-ia/crm",
        branch="feat/spec-004-crm",
        wave=1,
        status=TaskState.READY,
        pr_number=10,
        issue_number=5,
    )
    spec_run = SpecRun(
        spec_id="SPEC-004",
        title="Pipeline",
        author="local-dev",
        tasks={"task-1": subtask},
        status=TaskState.IN_PROGRESS,
    )
    asyncio.run(store.save_spec(spec_run))

    orch = HarnessOrchestrator(
        project_root=tmp_path,
        store=store,
        judge_evaluator=make_rejected_judge_evaluation,
    )

    with patch.object(orch, "_sync_wave_consumer_dependencies"):
        outcome = asyncio.run(
            orch.run_pipeline(
                spec_path=spec_file,
                ci_mode=False,
            )
        )

    assert outcome.is_awaiting_closure is True
    assert outcome.all_waves_complete is False
    assert outcome.judge_score == 0.75
    assert "Gate 5 Reprovado" in outcome.feedback


def test_orchestrator_executa_tarefa_com_pydantic_coder(tmp_path: Path) -> None:
    """Business Rule: orchestrator deve executar o loop agente-sensores com pydantic-coder."""
    from harness_state.agents import DetectedAgent

    agent = DetectedAgent(
        id="pydantic-coder",
        name="Pydantic AI Coder",
        binary_path="python",
        description="In-process agent",
    )
    orch = HarnessOrchestrator(
        project_root=tmp_path,
        verify_runner=lambda _dir: (0, "All tests passed"),
    )
    spec_run = SpecRun(
        spec_id="SPEC-010",
        title="Runtime Coder",
        author="dev",
        tasks={},
        status=TaskState.IN_PROGRESS,
    )
    task = SubTask(id="task-1", repo="spoke-repo", wave=1, branch="agent/task-1")
    code, output = orch._run_agent_verify_loop(
        active_spec=spec_run,
        next_task=task,
        target_repo_dir=tmp_path,
        spec_path=tmp_path / "SPEC-010.md",
        selected_agent=agent,
        was_already_in_progress=False,
        max_iterations=1,
    )
    assert code == 0
    assert "All tests passed" in output

