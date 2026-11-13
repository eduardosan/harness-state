# SPEC-008 Parser Unificado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um único parser de subtarefas de spec (formato canônico + branch namespaced) no `harness-state`, consumido pelos três pontos de extração (`harness plan`, `spec plan/run`, fan-out).

**Architecture:** O parser vive no `harness-state` (base) como `spec_parser.py` e retorna uma estrutura leve `ParsedSubTask`. `agentic-flywheel` já depende de `harness-state>=0.2.3` (pyproject linha 12), então passa a importar `harness_state.spec_parser` e mapeia `ParsedSubTask` para seus modelos locais (`SubTask`, `SubSpecTask`), mantendo só o enriquecimento (slug via manifest, `raw_content`). O contrato Redis `spec:{id}` não muda.

**Tech Stack:** Python 3.13+, `dataclasses`/`re` (sem novas deps), pydantic (modelos), pytest.

**Spec:** `harness-spec-hub/specs/SPEC-008-spec-parser-unificado.md` (PR #21)

## Global Constraints

- Python 3.13+; PEP 585/604 (`list[str]`, `int | None`); `datetime.now(UTC)`.
- Google-style docstrings (`Args:`/`Returns:`/`Raises:`).
- Sem funções aninhadas, sem try/except aninhado, sem try/except em imports, sem `_` inicial em funções de módulo; isort obrigatório.
- TDD: todo teste com docstring `Business Rule: ...`; testes em `tests/`.
- Proibido push/commit/rebase/merge na `main` e criação de tags; commits com trailer `Co-Authored-By: harness-agent <harness-agent@pets.for.mat.br>`; entrega via branch + PR.

## Review Focus

1. **Repo sem org (`repo` vs `org/repo`)** → `repo_name` é sempre o último segmento; `branch` usa `repo_name`, nunca o slug cru.
2. **`ecosystem` vazio** → branch `agent/{short_spec_id}-{repo_name}` (sem prefixo de ecossistema).
3. **`spec_id` sem hífen ou prefixo diferente de `spec`/`sdd`** → `short_spec_id` cai para `spec_id.lower()` (ex: `SPEC-007` → `spec-007`; `SPEC-007-fanout-ci-real` → `spec-007`).
4. **Linha de tarefa dentro de fence ```** → ignorada (não vira subtarefa).
5. **Checkbox marcado `[x]`** → `checked=True` preservado (consumidores mapeiam para `APPROVED`).

---

## Task 1: Parser canônico no `harness-state`

**Files:**
- Create: `src/harness_state/spec_parser.py`
- Test: `tests/test_spec_parser.py`

**Interfaces:**
- Produces (para Tasks 2–4):
  - `derive_ecosystem_from_repo(repo: str) -> str`
  - `resolve_short_spec_id(spec_id: str) -> str`
  - `@dataclass(frozen=True) class ParsedSubTask` com campos `task_id: str`, `repo: str`, `repo_name: str`, `branch: str`, `title: str`, `raw_content: str = ""`, `pr_number: int | None = None`, `checked: bool = False`, `wave: int = 1`
  - `parse_spec_tasks(lines: list[str], *, spec_id: str, ecosystem: str = "") -> list[ParsedSubTask]`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_spec_parser.py
from harness_state.spec_parser import (
    ParsedSubTask, derive_ecosystem_from_repo, parse_spec_tasks, resolve_short_spec_id,
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
    tasks = parse_spec_tasks(lines, spec_id="SPEC-007-fanout-ci-real", ecosystem="harness")
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
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd harness-state && uv run pytest tests/test_spec_parser.py -q`
Expected: FAIL (`ModuleNotFoundError: harness_state.spec_parser`)

- [ ] **Step 3: Implementar `spec_parser.py`**

Replicar a lógica hoje no `flywheel/fanout.py` (`build_subtask_from_match` + `extract_subtasks_from_lines` + `unfenced_lines` + `finalize_accumulated_subtask`) e `flywheel/state.py` (`derive_ecosystem_from_repo`), com:
- regex canônico `-\s*\[([ xX])\]\s*\*\*Sub-tarefa\s*(\d+)\s*\(`([^`]+)`\):\*\*(.*)`
- regex fallback `-\s*\[([ xX])\]\s*.*?`([^`]+)`.*?`
- `repo_name = repo.split("/")[-1]`; `branch = f"agent/{ecosystem}-{short_spec_id}-{repo_name}"` (sem `ecosystem-` quando vazio)
- `title = f"Implementar {task_id} para {repo_name}"`; `pr_number` via `re.search(r"\[PR #(\d+)\]\((https://[^\)]+)\)", rest)`
- acumular `raw_content` entre cabeçalhos (terminando em `## ` ou `---`), ignorando fences.

- [ ] **Step 4: Rodar e confirmar verde**

Run: `cd harness-state && uv run pytest tests/test_spec_parser.py -q`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git -C harness-state add tests/test_spec_parser.py src/harness_state/spec_parser.py
git -C harness-state commit -m "feat(spec-parser): parser canônico de subtarefas (SPEC-008)"
```

---

## Task 2: `harness plan` delega ao parser canônico

**Files:**
- Modify: `src/harness_state/cli.py:104-152` (`parse_spec_markdown`)
- Test: `tests/test_cli.py` (adicionar)

**Interfaces:**
- Consumes: `parse_spec_tasks`, `ParsedSubTask` (Task 1).
- Produces: `parse_spec_markdown(file_path, manifest_path=None, ecosystem="")` continua retornando `(spec_id, title, dict[str, SubTask])`, mas com `branch` namespaced.

- [ ] **Step 1: Escrever o teste que falha**

```python
# tests/test_cli.py
def test_parse_spec_markdown_namespaced_branch(tmp_path) -> None:
    """Business Rule: `harness plan` gera branch namespaced `agent/{eco}-{spec}-{repo}`."""
    spec = tmp_path / "SPEC-004.md"
    spec.write_text(
        "# Titulo\n- [ ] **Sub-tarefa 1 (`agentic-flywheel`):** x\n", encoding="utf-8"
    )
    _, _, tasks = parse_spec_markdown(spec, ecosystem="harness")
    assert tasks["task-1"].branch == "agent/harness-spec-004-agentic-flywheel"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd harness-state && uv run pytest tests/test_cli.py::test_parse_spec_markdown_namespaced_branch -q`
Expected: FAIL (branch ainda `agent/spec-004-...` sem namespace, ou sem `ecosystem`)

- [ ] **Step 3: Implementar delegação em `parse_spec_markdown`**

Trocar o loop de checkbox por `parse_spec_tasks(content.splitlines(), spec_id=spec_id, ecosystem=ecosystem)`, mapeando cada `ParsedSubTask` → `SubTask(id, repo, branch, status=APPROVED if checked else PENDING)`. Manter `spec_id = file_path.stem`, `title` (primeiro `#`) e `calculate_waves` via `load_manifest_dependencies` como hoje. Adicionar `ecosystem: str = ""` ao parâmetro e derivá-lo no `run_plan` a partir do campo `project` do `manifest.yaml` (fallback `""`).

- [ ] **Step 4: Rodar a suíte**

Run: `cd harness-state && uv run pytest tests/ -q && uv run pyright && uv run ruff check . && uv run isort --check-only .`
Expected: tudo verde.

- [ ] **Step 5: Commit**

```bash
git -C harness-state add -A && git -C harness-state commit -m "feat(cli): harness plan usa parser canônico namespaced (SPEC-008)"
```

- [ ] **Step 6: PR**

```bash
gh pr create --repo eduardosan/harness-state --title "feat(spec-parser): parser canônico + harness plan namespaced (SPEC-008)" --body "..."
```

---

## Task 3: [release] `harness-state` publicado

- [ ] **Step 1: Operador faz release**

O operador publica nova tag do `harness-state` (minor). O flywheel só consome o parser após o bump. Não é ação do agente.

---

## Task 4: flywheel `fanout.py` delega ao parser canônico

**Files:**
- Modify: `src/flywheel/fanout.py` (`extract_subtasks_from_lines:873`, `build_subtask_from_match:793`, import linha 20)
- Modify: `src/flywheel/state.py` (remover `derive_ecosystem_from_repo`, re-exportar do `harness_state` para não quebrar importadores)
- Test: `tests/unit/test_fanout_namespace.py` (estender)

**Interfaces:**
- Consumes: `harness_state.spec_parser.parse_spec_tasks`, `ParsedSubTask`.
- Produces: `extract_subtasks_from_lines(lines, resolved_spec_id, manifest_data, ecosystem="") -> list[SubSpecTask]` mantém assinatura atual, agora mapeando `ParsedSubTask` → `SubSpecTask` (resolvendo slug completo via `resolve_full_repo_slug_for_fanout`).

- [ ] **Step 1: Escrever teste de paridade (falha)**

```python
# tests/unit/test_fanout_namespace.py
def test_fanout_uses_canonical_branch_for_checkbox_fallback() -> None:
    """Business Rule: fan-out e parser canônico geram a MESMA branch namespaced."""
    lines = ["- [ ] **Sub-tarefa 1 (`agentic-flywheel`):** x"]
    tasks = extract_subtasks_from_lines(lines, "SPEC-007-fanout-ci-real", None, "harness")
    assert tasks[0].branch == "agent/harness-spec-007-agentic-flywheel"
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `cd agentic-flywheel && uv run pytest tests/unit/test_fanout_namespace.py -q`
Expected: FAIL (se ainda não delegar).

- [ ] **Step 3: Implementar delegação**

- `extract_subtasks_from_lines` passa a chamar `parse_spec_tasks(lines, spec_id=resolved_spec_id, ecosystem=ecosystem)` e mapeia para `SubSpecTask` (com `raw_content` vindo de `ParsedSubTask.raw_content`, `pr_number` e slug via manifest). Remover `build_subtask_from_match`, `unfenced_lines`, `finalize_accumulated_subtask` (movidos ao `harness_state`).
- `derive_ecosystem_from_repo` em `state.py` vira re-export `from harness_state.spec_parser import derive_ecosystem_from_repo` (manter import em `fanout.py` funcionando ou trocar para `harness_state.spec_parser`).
- `short_spec_id` passa a usar `resolve_short_spec_id` do `harness_state`.

- [ ] **Step 4: Rodar a suíte**

Run: `cd agentic-flywheel && just verify`
Expected: verde (pyright/ruff/isort/complexipy/pytest).

- [ ] **Step 5: Commit + PR**

```bash
git -C agentic-flywheel add -A && git -C agentic-flywheel commit -m "refactor(fanout): delega parser ao harness_state (SPEC-008)"
gh pr create --repo eduardosan/agentic-flywheel --title "refactor(fanout): parser canônico do harness-state (SPEC-008)" --body "..."
```

---

## Task 5: flywheel `orchestrator.py` (`extract_initial_subtasks`)

**Files:**
- Modify: `src/flywheel/orchestrator.py:358-418` (`extract_initial_subtasks`)
- Test: `tests/unit/test_harness_orchestrator.py` (adicionar)

**Interfaces:**
- Consumes: `parse_spec_tasks`, `resolve_short_spec_id` (Task 1).
- Produces: `extract_initial_subtasks(frontmatter, body, spec_id, origin_module, file_path) -> dict[str, SubTask]` mantém assinatura; frontmatter `target_repositories` continua primário, mas a branch vira namespaced; fallback checkbox delega ao parser.

- [ ] **Step 1: Escrever teste (falha)**

```python
# tests/unit/test_harness_orchestrator.py
def test_extract_initial_subtasks_fallback_branch_namespaced() -> None:
    """Business Rule: fallback de checkbox em spec plan gera branch namespaced (não feat/)."""
    ...
```

- [ ] **Step 2–4: RED → implementar → GREEN** (delegar fallback a `parse_spec_tasks`; branch do caminho frontmatter `f"agent/{ecosystem}-{resolve_short_spec_id(spec_id)}-{repo_name}"`; derivar `ecosystem` do `origin_module`/manifest como no fan-out).

- [ ] **Step 5: Commit + PR**

```bash
git -C agentic-flywheel add -A && git -C agentic-flywheel commit -m "refactor(orchestrator): spec plan usa branch namespaced (SPEC-008)"
gh pr create --repo eduardosan/agentic-flywheel --title "refactor(orchestrator): branch namespaced no spec plan (SPEC-008)" --body "..."
```

---

## Task 6: Dogfood

- [ ] **Step 1:** Após merges, rodar `harness spec plan` sobre a própria SPEC-008 (modo local) e conferir que as sub-specs geradas usam `agent/harness-spec-008-*` (e não `feat/spec-001-*`).
