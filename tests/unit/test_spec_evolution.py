"""Testes unitários para o motor de reconciliação e evolução de especificações (SPEC-011)."""

from pathlib import Path

import pytest

from harness_state.models import (
    RevisionType,
    SpecEvolutionPlan,
    SpecRun,
    SubTask,
    TaskState,
)
from harness_state.spec.evolution import SpecEvolutionEngine


@pytest.fixture
def sample_spec_hub(tmp_path: Path) -> tuple[Path, Path]:
    """Cria ambiente simulado do spec-hub com uma spec baseline."""
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir(parents=True)

    spec_content = """---
spec_id: SPEC-011
title: "Atualização e Evolução Contínua de Specs"
spec_version: "1.0.0"
revisions: []
product:
  - harness
capability: agent-workflow-platform
scope: platform
bounded_context: "SDD Lifecycle"
target_repositories:
  - repo: eduardosan/harness-spec-hub
    wave: 1
    role: hub
  - repo: eduardosan/harness-state
    wave: 2
    role: core
status: IN_PROGRESS
---

# SPEC-011: Atualização e Evolução Contínua de Specs

## 2. Escopo e Repositórios Afetados

- [x] **Sub-tarefa 1 (`eduardosan/harness-spec-hub`):** [Onda 1] Template e governança de Living Specs.
- [ ] **Sub-tarefa 2 (`eduardosan/harness-state`):** [Onda 2] Motores de descoberta e evolução.

## 3. Contratos de Interface

### 3.1. Parser Contract
```python
def parse(spec: str) -> dict: ...
```
"""
    spec_path = specs_dir / "SPEC-011-atualiza-spec.md"
    spec_path.write_text(spec_content, encoding="utf-8")
    return tmp_path, spec_path


def test_analyze_spec_evolution_identifies_frozen_and_pending_tasks(
    sample_spec_hub: tuple[Path, Path],
) -> None:
    """Business Rule: Tarefas com status READY ou APPROVED devem ser congeladas e isoladas das tarefas pendentes."""
    hub_dir, spec_path = sample_spec_hub
    engine = SpecEvolutionEngine(spec_hub_dir=hub_dir)

    t1 = SubTask(
        id="task-1",
        repo="eduardosan/harness-spec-hub",
        branch="agent/harness-spec-011-harness-spec-hub",
        status=TaskState.APPROVED,
        wave=1,
    )
    t2 = SubTask(
        id="task-2",
        repo="eduardosan/harness-state",
        branch="agent/harness-spec-011-harness-state",
        status=TaskState.PENDING,
        wave=2,
    )
    run = SpecRun(
        spec_id="SPEC-011",
        title="Living Specs",
        author="antigravity",
        status=TaskState.IN_PROGRESS,
        tasks={"task-1": t1, "task-2": t2},
        spec_version="1.0.0",
    )

    plan = engine.analyze_spec_evolution(
        spec_path=spec_path,
        instruction="Adicionar endpoint de telemetria e expandir contratos",
        current_run=run,
    )

    assert plan.spec_id == "SPEC-011"
    assert plan.current_version == "1.0.0"
    assert plan.target_version == "1.1.0"
    assert len(plan.frozen_tasks) == 1
    assert plan.frozen_tasks[0].id == "task-1"
    assert len(plan.tasks_to_execute) == 1
    assert plan.tasks_to_execute[0].id == "task-2"
    assert "eduardosan/harness-state" in plan.affected_repositories
    assert plan.has_breaking_changes is False


def test_analyze_spec_evolution_detects_breaking_changes_on_frozen_contracts(
    sample_spec_hub: tuple[Path, Path],
) -> None:
    """Business Rule: Remoção ou alteração incompatível de contrato associado a tarefa congelada deve ser detectada."""
    hub_dir, spec_path = sample_spec_hub
    engine = SpecEvolutionEngine(spec_hub_dir=hub_dir)

    # Modifica a spec removendo silenciosamente `def parse`
    modified_content = """---
spec_id: SPEC-011
title: "Atualização e Evolução Contínua de Specs"
spec_version: "1.0.0"
---
# SPEC-011
## 3. Contratos de Interface
```python
def completely_different_signature(x: int) -> int: ...
```
"""
    spec_path.write_text(modified_content, encoding="utf-8")

    t1 = SubTask(
        id="task-1",
        repo="eduardosan/harness-spec-hub",
        branch="agent/t1",
        status=TaskState.APPROVED,
    )
    run = SpecRun(
        spec_id="SPEC-011",
        title="Living Specs",
        author="antigravity",
        tasks={"task-1": t1},
        spec_version="1.0.0",
    )

    previous_content = """
## 3. Contratos de Interface
```python
def parse(spec: str) -> dict: ...
```
"""
    plan = engine.analyze_spec_evolution(
        spec_path=spec_path,
        instruction="Refatoração profunda de contratos",
        current_run=run,
        previous_spec_content=previous_content,
    )

    assert plan.has_breaking_changes is True
    assert plan.target_version == "2.0.0"


def test_apply_evolution_updates_spec_markdown_and_generates_revision(
    sample_spec_hub: tuple[Path, Path],
) -> None:
    """Business Rule: apply_evolution deve gravar a nova versão SemVer e o histórico de revisões no Markdown da spec."""
    hub_dir, spec_path = sample_spec_hub
    engine = SpecEvolutionEngine(spec_hub_dir=hub_dir)

    t1 = SubTask(id="task-1", repo="repo/hub", branch="agent/t1", status=TaskState.APPROVED)
    plan = SpecEvolutionPlan(
        spec_id="SPEC-011",
        current_version="1.0.0",
        target_version="1.1.0",
        frozen_tasks=[t1],
        tasks_to_execute=[],
        affected_repositories=[],
        has_breaking_changes=False,
    )

    revision = engine.apply_evolution_to_spec(
        spec_path=spec_path,
        plan=plan,
        author="antigravity",
        instruction="Evolução de contratos",
    )

    assert revision.spec_id == "SPEC-011"
    assert revision.version == "1.1.0"
    assert revision.revision_type == RevisionType.MINOR_EVOLUTION
    assert revision.frozen_task_ids == ["task-1"]

    updated_text = spec_path.read_text(encoding="utf-8")
    assert "1.1.0" in updated_text
    assert "Evolução de contratos" in updated_text
