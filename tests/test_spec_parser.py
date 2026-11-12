"""Testes do parser canônico de subtarefas de spec (SPEC-008)."""

from harness_state.spec_parser import (
    ParsedSubTask,
    derive_ecosystem_from_repo,
    parse_spec_tasks,
    resolve_short_spec_id,
)


def test_derive_ecosystem_from_repo() -> None:
    """Business Rule: hub `eduardosan/harness-spec-hub` deriva ecossistema `harness`."""
    assert derive_ecosystem_from_repo("eduardosan/harness-spec-hub") == "harness"
    assert derive_ecosystem_from_repo("") == ""


def test_resolve_short_spec_id() -> None:
    """Business Rule: `SPEC-007-fanout-ci-real` deriva prefixo curto `spec-007`."""
    assert resolve_short_spec_id("SPEC-007-fanout-ci-real") == "spec-007"
    assert resolve_short_spec_id("SPEC-007") == "spec-007"


def test_parse_spec_tasks_canonical_format() -> None:
    """Business Rule: formato `**Sub-tarefa N (`repo`):**` gera tarefa com branch namespaced."""
    lines = [
        "- [ ] **Sub-tarefa 1 (`agentic-flywheel`):** Implementar task-1",
        "- [x] **Sub-tarefa 2 (`eduardosan/harness-state`):** [PR #5](https://x/5)",
    ]
    tasks = parse_spec_tasks(
        lines, spec_id="SPEC-007-fanout-ci-real", ecosystem="harness"
    )
    assert [t.task_id for t in tasks] == ["task-1", "task-2"]
    assert tasks[0].repo_name == "agentic-flywheel"
    assert tasks[0].branch == "agent/harness-spec-007-agentic-flywheel"
    assert tasks[1].repo_name == "harness-state"
    assert tasks[1].branch == "agent/harness-spec-007-harness-state"
    assert tasks[1].pr_number == 5
    assert tasks[1].checked is True


def test_parse_spec_tasks_checkbox_fallback() -> None:
    """Business Rule: checkbox genérico `- [ ] ... `repo`` continua parseando (retrocompat)."""
    lines = ["- [ ] Implementar pipeline `agentic-flywheel`"]
    tasks = parse_spec_tasks(lines, spec_id="SPEC-004", ecosystem="harness")
    assert len(tasks) == 1
    assert tasks[0].task_id == "task-1"
    assert tasks[0].branch == "agent/harness-spec-004-agentic-flywheel"


def test_parse_spec_tasks_no_ecosystem() -> None:
    """Business Rule: sem ecosystem a branch não leva prefixo de namespace."""
    tasks = parse_spec_tasks(
        ["- [ ] **Sub-tarefa 1 (`agentic-flywheel`):** x"],
        spec_id="SPEC-008",
    )
    assert tasks[0].branch == "agent/spec-008-agentic-flywheel"


def test_parse_spec_tasks_ignores_fences() -> None:
    """Business Rule: linhas de tarefa dentro de ``` são ignoradas."""
    lines = ["```", "- [ ] **Sub-tarefa 1 (`x`):** fake", "```"]
    assert parse_spec_tasks(lines, spec_id="SPEC-008") == []


def test_parsed_subtask_is_frozen_dataclass() -> None:
    """Business Rule: `ParsedSubTask` é um dataclass frozen com os campos do contrato."""
    task = ParsedSubTask(
        task_id="task-1",
        repo="agentic-flywheel",
        repo_name="agentic-flywheel",
        branch="agent/harness-spec-008-agentic-flywheel",
        title="Implementar task-1 para agentic-flywheel",
    )
    assert task.raw_content == ""
    assert task.pr_number is None
    assert task.checked is False
    assert task.wave == 1


def test_inline_code_examples_not_parsed_as_tasks() -> None:
    """Business Rule: exemplo de formato em inline code (fora de fence) não vira subtarefa."""
    lines = [
        "| Parser | Formato |",
        "| `extract_subtasks_from_lines` | canônico `- [ ] **Sub-tarefa N (\\`repo\\`):**` |",
        "- **Formato primário (canônico):** `- [ ] **Sub-tarefa N (\\`repo\\`):** ...`",
        "- **Cenário 1:** dado um corpo com `- [ ] **Sub-tarefa 1 (\\`org/repo\\`):**`,",
        "## 2. Escopo",
        "- [x] [Onda 1] `eduardosan/harness-state`: parser canônico.",
        "- [x] [Onda 2] `eduardosan/agentic-flywheel`: consumidores.",
    ]
    tasks = parse_spec_tasks(lines, spec_id="SPEC-008", ecosystem="harness")

    assert [t.repo for t in tasks] == [
        "eduardosan/harness-state",
        "eduardosan/agentic-flywheel",
    ], "só as checkboxes reais (§2) podem virar subtarefas; exemplos inline não"
