# Sub-Spec: harness-state (harness/SPEC-008-spec-parser-unificado)

> **Spec Central:** [SPEC-008: Unificação do parser de subtarefas de spec](specs/SPEC-008-spec-parser-unificado.md)
> **Identificador da Tarefa:** `task-1`
> **Repositório:** `eduardosan/harness-state`
> **Onda de Execução:** 1
> **Branch de Trabalho:** `agent/harness-spec-008-harness-state`

---

## 1. Contexto e Intenção



---

## 2. Requisitos Específicos do Componente



### Checklist de Implementação:
- [ ] Implementação de acordo com os requisitos descritos.

---

## 3. Modelo Contratual e Interfaces Compartilhadas

### 3.1. Parser canônico (`harness_state/spec_parser.py`)

```
derive_ecosystem_from_repo(repo: str) -> str
    # eduardosan/harness-spec-hub -> "harness"  (movido de flywheel/state.py)

resolve_short_spec_id(spec_id: str) -> str
    # "SPEC-007-fanout-ci-real" -> "spec-007"   (lógica hoje inline no fanout)

@dataclass
class ParsedSubTask:
    task_id: str          # "task-1"
    repo: str             # repo como escrito (ex: "agentic-flywheel" ou "eduardosan/harness-state")
    repo_name: str        # último segmento ("harness-state")
    branch: str           # "agent/harness-spec-007-harness-state"
    title: str            # "Implementar task-1 para harness-state"
    raw_content: str = "" # corpo acumulado entre cabeçalhos (fence-aware)
    pr_number: int | None = None
    checked: bool = False # checkbox [x] (consumidores mapeiam p/ APPROVED)
    wave: int = 1

parse_spec_tasks(
    lines: list[str],
    *,
    spec_id: str,
    ecosystem: str = "",
) -> list[ParsedSubTask]
```

- **Formato primário (canônico):** `- [ ] **Sub-tarefa N (\`repo\`):** ...` (o mesmo já
  emitido pelo fan-out na SPEC-007).
- **Formato de compatibilidade (fallback):** checkbox genérico `- [ ] ... \`repo\``
  (o que `harness plan`/`spec plan` aceitam hoje) — mantido para não quebrar specs
  antigas já gravadas.
- **Numeração explícita:** no formato canônico, `N` vem do markdown; no fallback,
  sequencial (`task-1`, `task-2`, ...).
- **Fences:** linhas dentro de blocos de código (```) são ignoradas (não viram tarefa).
- **Ondas:** o parser retorna `wave=1` por padrão (é wave-agnóstico); o cálculo de ondas
  via `manifest.yaml` continua responsabilidade de cada consumidor
  (`calculate_waves` no harness-state; `resolve_waves_and_dependencies` no fan-out).
- **Branch canônica:** `agent/{ecosystem}-{short_spec_id}-{repo_name}` com ecosystem;
  `agent/{short_spec_id}-{repo_name}` sem ecosystem (SPEC-007 §branch).

### 3.2. Mapeamento de modelos (sem mudança de contrato Redis)

- O parser canônico retorna `ParsedSubTask` (estrutura leve). Cada consumidor mapeia
  para seu modelo local:
  - `harness-state`: `SubTask(id, repo, branch, status, ...)`.
  - `flywheel`: `SubTask` (state.py) e `SubSpecTask` (fanout.py, com `raw_content`).
- O contrato Redis `spec:{id}` (SPEC-002 §3.1) **não muda**: a serialização continua a
  mesma; apenas o valor de `branch` passa a ser namespaced de forma consistente.

### 3.3. Viabilidade e compatibilidade

- **Sem novas dependências externas:** o parser usa apenas `re` e `dataclasses`.
- **Direção de dependência respeitada:** `harness-state` é a base; `agentic-flywheel`
  já depende dele (`harness-state>=0.2.x`), então o parser canônico vive na base.
- **Retrocompatibilidade:** specs com formato checkbox genérico continuam parseando
  (fallback); specs canônicas (SPEC-007+) seguem idênticas.

## 4. Abordagens Consideradas

- **A — alinhamento mínimo (só branch naming):** rejeitada — mantém 3 parsers e a
  dívida, apenas mascara o sintoma.
- **B — parser canônico único no `harness-state` (ESCOLHIDA):** elimina a divergência
  na raiz; um só contrato de formato/branch/namespace; flywheel delega. Custo: muda 2
  repos e exige release do `harness-state` antes do flywheel consumir.
- **C — unificar só dentro do flywheel:** rejeitada — deixa a CLI pública
  `harness plan` fora do contrato, perpetuando a divergência entre o planejado (CLI)
  e o executado (esteira).

## 5. Não-Metas

- **Não** reconcilia o drift de campos entre os modelos `SubTask` (`harness-state` não
  tem `issue_number`/`issue_url`/`expected_version`) — spec futura.
- **Não** refatora o `cli.py` monólito do flywheel (SPEC-002 §5 segue válido).
- **Não** altera o formato Redis `spec:{id}` nem migra specs já persistidas.

## 6. Anti-Metas

- Introduzir um 4º parser ou uma camada de "tradução" ad-hoc entre os três.
- Quebrar specs já escritas em formato checkbox (regressão de `harness plan`/`spec run`).
- Mover o parser para o flywheel e inverter a dependência (flywheel→base, nunca base→flywheel).

## 7. Critérios de Aceitação (TDD)

- **Cenário 1 — formato canônico:** dado um corpo com `- [ ] **Sub-tarefa 1 (\`org/repo\`):**`,
  o parser retorna `task-1` com `repo=org/repo` e `branch=agent/<eco>-spec-008-repo`.
- **Cenário 2 — fallback checkbox:** dado um corpo com `- [ ] ... \`org/repo\``, o parser
  numera sequencialmente e gera a mesma branch namespaced.
- **Cenário 3 — fence:** linhas de subtarefa dentro de ``` são ignoradas.
- **Cenário 4 — namespace:** com `ecosystem="harness"`, a branch é
  `agent/harness-spec-008-repo`; sem ecosystem, `agent/spec-008-repo`.
- **Cenário 5 — paridade:** `parse_spec_markdown`, `extract_initial_subtasks` e o fan-out
  produzem a **mesma** branch para a mesma spec (teste de regressão contra o resíduo
  `feat/spec-001-*`).

## 8. Plano de Rollout

1. `harness-state`: implementar `spec_parser.py` + delegar `parse_spec_markdown`
   (TDD), `just verify` verde, PR.
2. Release `harness-state` (minor) — ação do operador.
3. `agentic-flywheel`: bump da dependência + delegar os dois consumidores (TDD),
   `just verify` verde, PR.
4. Dogfood: `harness spec plan` sobre esta própria SPEC-008 (modo local) e conferir que
   as sub-specs geradas usam `agent/harness-spec-008-*`.

---

## 4. Instruções para o Agente Autônomo e Validação

1. **Test-Driven Development (TDD):** Crie testes unitários em `tests/unit/`
   com docstring contendo o prefixo `Business Rule:`.
2. **Qualidade e Estilo:** PEP 8 estrito, Google docstrings em todas as classes,
   métodos e funções, sem funções aninhadas, sem try-except em imports.
3. **Verificação dos Sensores:** Execute `just verify` localmente para certificar
   a conformidade antes do envio do Pull Request.
