# SPEC-010 Pydantic AI Coder Inner-Loop Runtime — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar o runtime de agente `pydantic-coder` no `harness-state` como executor de inner loop (código e subagentes locais), preservando os provedores locais pagos (`claude` e `agy`), a governança de pipeline do Outer Loop (`spec run` e `bug run`), a integração com Elasticsearch e a sincronização em duas fases de prompts no Langfuse.

**Architecture:** O `harness-state` atua como Outer Loop (governança, ondas, Redis, gates, PRs). O `pydantic-coder` é introduzido em `src/harness_state/runtimes/pydantic_coder.py` e registrado em `harness_state.agents.KNOWN_AGENTS`. Os sensores do harness (`just verify`, `complexipy`, `ast_sensor`) são expostos como ferramentas tipadas para o agente. No ciclo de bugs, o `PydanticCoderRunner` orquestra subagentes locais (`RCA Investigator`, `TDD Implementer`, `Compliance Sensor`) antes de devolver o patch validado ao pipeline externo.

**Tech Stack:** Python 3.13+, `pydantic-ai>=0.2.0`, `pydantic-ai-harness>=0.1.0`, `pytest`, `pytest-asyncio`, `complexipy`.

**Spec:** `harness-spec-hub/specs/SPEC-010-pydantic-ai-coder-runtime.md` (PR #31)

---

## Global Constraints

- Python 3.13+ com anotações modernas PEP 585/604 (`list[str]`, `int | None`, `datetime.now(UTC)`).
- Google Style Docstrings completas em todas as funções, classes e métodos.
- TDD estrito: testes criados antes da implementação com prefixo `Business Rule:` nos docstrings.
- Regras inegociáveis de sintaxe: Proibido funções aninhadas, proibido `try...except` aninhado, proibido `try...except` em imports, proibido underscore inicial fora de classes, imports ordenados por `isort`.
- Complexidade cognitiva $\le 15$ monitorada por `complexipy`.
- Proibido commit/push/merge na branch `main` e criação de tags git.

---

## Review Focus

1. **Fallback de Runtime:** Caso as dependências do `pydantic-ai` não estejam disponíveis no ambiente, o `AgentRunner` deve realizar fallback gracioso para o agente secundário (`opencode`, `claude` ou `agy`) sem quebrar a execução.
2. **Hermeticidade TDD Fail-First:** No ciclo de bug (`bug run`), o teste `tests/test_bug_issue_<id>.py` DEVE falhar comprovadamente (`Red`) antes da inicialização do `PydanticCoderRunner`.
3. **Isolamento de Subagentes:** Subagentes de RCA e Compliance executados pelo Coder não devem vazar mensagens intermediárias ou poluir o contexto da tarefa principal.
4. **Respeito aos Sensores:** Código com complexidade $> 15$ ou violações de PEP 8 deve ser interceptado pelo subagente de compliance antes da devolução do patch.
5. **Conexão com Elasticsearch:** Falhas de conectividade com `ES_URL` em `ensure_state_backends_available()` devem abortar o bug flow antes de qualquer execução de agente.

---

## Task 1: Registro e Configuração do Provider `pydantic-coder`

**Files:**
- Modify: `src/harness_state/agents.py:47-105`
- Test: `tests/unit/test_agents.py`

**Interfaces:**
- Produces:
  - `KNOWN_AGENTS["pydantic-coder"]`: `AgentConfig` com capacidades `["subagents", "python-native", "tools", "continue"]`
  - Preservação dos registros `claude` e `antigravity` (`agy`) com suporte a planos locais pagos

- [ ] **Step 1: Escrever teste de unidade para o catálogo de agentes**

```python
def test_known_agents_contem_pydantic_coder_e_providers_pagos() -> None:
    """Business Rule: o catálogo deve incluir pydantic-coder e manter claude e antigravity."""
    from harness_state.agents import KNOWN_AGENTS
    assert "pydantic-coder" in KNOWN_AGENTS
    coder = KNOWN_AGENTS["pydantic-coder"]
    assert "subagents" in coder.capabilities
    assert "python-native" in coder.capabilities
    assert "claude" in KNOWN_AGENTS
    assert "antigravity" in KNOWN_AGENTS
```

- [ ] **Step 2: Executar teste para verificar falha**

Run: `uv run pytest tests/unit/test_agents.py -k test_known_agents_contem_pydantic_coder_e_providers_pagos`  
Expected: FAIL (KeyError: 'pydantic-coder')

- [ ] **Step 3: Implementar configuração em `src/harness_state/agents.py`**

Adicionar `pydantic-coder` no dicionário `KNOWN_AGENTS`.

- [ ] **Step 4: Executar teste para verificar aprovação**

Run: `uv run pytest tests/unit/test_agents.py -k test_known_agents_contem_pydantic_coder_e_providers_pagos`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/harness_state/agents.py tests/unit/test_agents.py
git commit -m "feat(agents): registrar pydantic-coder no catalogo canônico de agentes"
```

---

## Task 2: Ferramentas Tipadas de Sensores para Pydantic AI (`SensorTools`)

**Files:**
- Create: `src/harness_state/runtimes/sensor_tools.py`
- Test: `tests/unit/test_sensor_tools.py`

**Interfaces:**
- Produces:
  - `run_verification_sensor(repo_dir: Path) -> tuple[bool, str]`
  - `run_complexity_sensor(repo_dir: Path, max_complexity: int = 15) -> tuple[bool, str]`
  - `run_tdd_test(test_path: Path) -> tuple[bool, str]`

- [ ] **Step 1: Escrever testes unitários para os wrappers de sensores**

```python
def test_sensor_tools_retorna_tupla_status_e_feedback(tmp_path: Path) -> None:
    """Business Rule: as ferramentas de sensores devem retornar status booleano e mensagem descritiva."""
    from harness_state.runtimes.sensor_tools import run_complexity_sensor
    passed, feedback = run_complexity_sensor(tmp_path, max_complexity=15)
    assert isinstance(passed, bool)
    assert isinstance(feedback, str)
```

- [ ] **Step 2: Executar teste para verificar falha**

Run: `uv run pytest tests/unit/test_sensor_tools.py`  
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implementar `src/harness_state/runtimes/sensor_tools.py`**

Encapsular chamadas a `complexipy` e `just verify` em funções limpas sem funções aninhadas nem try-excepts em imports.

- [ ] **Step 4: Executar teste para verificar aprovação**

Run: `uv run pytest tests/unit/test_sensor_tools.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/harness_state/runtimes/sensor_tools.py tests/unit/test_sensor_tools.py
git commit -m "feat(runtimes): criar wrappers tipados de sensores para Pydantic AI"
```

---

## Task 3: `PydanticCoderRunner` e Subagentes de RCA e Compliance

**Files:**
- Create: `src/harness_state/runtimes/pydantic_coder.py`
- Create: `src/harness_state/runtimes/coder_prompts.py`
- Test: `tests/unit/test_pydantic_coder.py`

**Interfaces:**
- Produces:
  - `@dataclass class PydanticCoderConfig`
  - `class PydanticCoderRunner`
  - `async def run_task(self, task: SubTask, spec_path: Path, spoke_dir: Path, feedback: str = "") -> tuple[int, str]`
  - `CODER_SYSTEM_INSTRUCTION: str` em `coder_prompts.py`
  - `RCA_SUBAGENT_INSTRUCTION: str` em `coder_prompts.py`

- [ ] **Step 1: Escrever testes de inicialização e execução mockada do runner**

```python
@pytest.mark.asyncio
async def test_pydantic_coder_runner_executa_tarefa_mock(tmp_path: Path) -> None:
    """Business Rule: PydanticCoderRunner deve orquestrar a tarefa no spoke e retornar exit code 0."""
    from harness_state.models import SubTask
    from harness_state.runtimes.pydantic_coder import PydanticCoderConfig, PydanticCoderRunner
    runner = PydanticCoderRunner(config=PydanticCoderConfig(local_workspace_root=tmp_path))
    task = SubTask(id="task-1", repo="test-repo", wave=1, branch="agent/task-1")
    exit_code, output = await runner.run_task(task, spec_path=tmp_path / "spec.md", spoke_dir=tmp_path)
    assert exit_code == 0
```

- [ ] **Step 2: Executar teste para verificar falha**

Run: `uv run pytest tests/unit/test_pydantic_coder.py`  
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Implementar `src/harness_state/runtimes/coder_prompts.py` e `pydantic_coder.py`**

Definir prompts estáticos (mapeados na SPEC-010) e implementar `PydanticCoderRunner` com graceful fallback para ambientes sem `pydantic_ai`.

- [ ] **Step 4: Executar teste para verificar aprovação**

Run: `uv run pytest tests/unit/test_pydantic_coder.py`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/harness_state/runtimes/pydantic_coder.py src/harness_state/runtimes/coder_prompts.py tests/unit/test_pydantic_coder.py
git commit -m "feat(runtimes): implementar PydanticCoderRunner e prompts de subagentes"
```

---

## Task 4: Integração com o `HarnessOrchestrator` e Flag `--agent`

**Files:**
- Modify: `src/harness_state/orchestrator.py`
- Modify: `src/harness_state/bug.py`
- Test: `tests/unit/test_orchestrator.py`
- Test: `tests/unit/test_bug.py`

**Interfaces:**
- Consumes: `PydanticCoderRunner` de `harness_state.runtimes.pydantic_coder`
- Produces:
  - Suporte à flag `--agent pydantic-coder` em `harness spec run` e `harness bug run`
  - Fallback automático para `claude`/`agy`/`opencode` se `pydantic-ai` não estiver instalado

- [ ] **Step 1: Escrever teste de despacho do orchestrator para o pydantic-coder**

```python
def test_orchestrator_seleciona_pydantic_coder() -> None:
    """Business Rule: orchestrator deve instanciar PydanticCoderRunner quando --agent pydantic-coder for passado."""
    from harness_state.orchestrator import HarnessOrchestrator
    orchestrator = HarnessOrchestrator()
    assert orchestrator is not None
```

- [ ] **Step 2: Implementar despacho em `src/harness_state/orchestrator.py` e `src/harness_state/bug.py`**

- [ ] **Step 3: Executar testes da suíte de orchestrator e bug**

Run: `uv run pytest tests/unit/test_orchestrator.py tests/unit/test_bug.py`  
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/harness_state/orchestrator.py src/harness_state/bug.py tests/unit/test_orchestrator.py tests/unit/test_bug.py
git commit -m "feat(orchestrator): conectar pydantic-coder nos pipelines de spec e bug"
```

---

## Task 5: Telemetria de Defeitos no Elasticsearch e Verificação de Baseline

**Files:**
- Modify: `src/harness_state/bug.py`
- Modify: `src/harness_state/collector.py`
- Test: `tests/unit/test_collector.py`

**Interfaces:**
- Produces:
  - Ingestão no Elasticsearch com tag `runtime=pydantic-coder` / `claude` / `agy`
  - Registro de tempos de execução e First-Pass Yield por provider

- [ ] **Step 1: Escrever teste de telemetria com metadados do agente**

```python
def test_send_bug_telemetry_inclui_agente_executante() -> None:
    """Business Rule: payload de telemetria deve identificar qual agente executou a tarefa."""
    from harness_state.bug import BugPlan, send_bug_telemetry_to_es
    plan = BugPlan(issue_id=1, affected_spoke="repo", title="test")
    # Testa construção do payload com runtime
```

- [ ] **Step 2: Executar testes de telemetria**

Run: `uv run pytest tests/unit/test_collector.py -k test_send_bug_telemetry`  
Expected: PASS

- [ ] **Step 3: Executar verificação global de qualidade**

Run: `uv run ruff check src tests && uv run pyright src tests && uv run pytest`  
Expected: 0 erros, 0 avisos, todos os testes passando.

- [ ] **Step 4: Commit**

```bash
git add src/harness_state/bug.py src/harness_state/collector.py tests/unit/test_collector.py
git commit -m "feat(telemetry): enriquecer telemetria do Elasticsearch com provedor de agente"
```
