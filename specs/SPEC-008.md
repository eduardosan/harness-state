---
spec_id: SPEC-008
title: Unificação do parser de subtarefas de spec (formato e branch namespaced) -
  harness-state
parent_spec: SPEC-008
repo: eduardosan/harness-state
task_id: task-1
wave: 1
branch: agent/harness-spec-008-harness-state
tasks:
- id: task-1
  wave: 1
  branch: agent/harness-spec-008-harness-state
  expected_version: N/A
product:
- harness
capability: agent-workflow-platform
status: IN_PROGRESS
---

# SPEC-008: Unificação do parser de subtarefas de spec (formato e branch namespaced) - harness-state

> **Parent Spec:** `SPEC-008` (SPEC-008-spec-parser-unificado.md)  
> **Repositório Alvo:** `eduardosan/harness-state`  
> **Subtarefa Principal:** `task-1` (Onda 1)  
> **Branch:** `agent/harness-spec-008-harness-state`  
> **Status:** `IN_PROGRESS`

---

## 1. Contexto e Motivação

Hoje coexistem **três** implementações independentes de extração de subtarefas de uma
spec Markdown, com divergências reais de formato, numeração e nome de branch:

| Parser | Onde vive | Formato aceito | Branch gerada | Namespace |
|---|---|---|---|---|
| `parse_spec_markdown` | `harness-state/cli.py` (`harness plan`) | checkbox genérico `- [ ] ... \`repo\`` | `agent/{spec_id}-{repo}` | não |
| `extract_initial_subtasks` | `flywheel/orchestrator.py` (`spec plan`/`run`) | frontmatter `target_repositories` → fallback checkbox | `feat/{spec_id}-{repo}` | não |
| `extract_subtasks_from_lines` | `flywheel/fanout.py` (fan-out real) | canônico `- [ ] **Sub-tarefa N (\`repo\`):**` | `agent/{ecosystem}-{spec-xx}-{repo}` | sim (SPEC-007) |

**Consequência observada (evidência no próprio run do SPEC-002):**

- As sub-specs do desacoplamento ficaram com `branch: feat/spec-001-*` (parser 2),
  usando `spec-001` no lugar de `spec-002` — o `spec_id` foi resolvido errado.
- As ondas gravadas divergem do `manifest.yaml` (state=wave2 vs manifest wave1;
  ansible=wave4 vs manifest wave2).
- A sub-spec do `harness-slack-bot` foi escrita pelo fan-out mas **nunca commitada**,
  porque o working tree do spoke divergiu do que o tracker acreditava.
- O `spec plan` persiste o `SpecRun` com branches `feat/...` enquanto o fan-out cria
  `agent/{ecosystem}-...` — estado persistido ≠ o que a esteira realmente executa.

A dívida não é só estética: o contrato de branch/namespace define qual branch o
runner CI dispara, onde a sub-spec é escrita e como o tracker reconcilia. Três
contratos diferentes produzem exatamente os resíduos que encontramos no SPEC-002.

## 2. Escopo e Repositórios Afetados

- [ ] [Onda 1] `eduardosan/harness-state`: novo módulo `spec_parser.py` com o parser
      canônico (formato + numeração + branch namespaced) e `derive_ecosystem_from_repo`
      movida do flywheel; `parse_spec_markdown` (CLI `harness plan`) delega ao parser
      canônico.
- [ ] [Onda 2] `eduardosan/agentic-flywheel`: `extract_initial_subtasks` delega o
      fallback de checkbox ao parser canônico (mantendo o caminho frontmatter
      `target_repositories`, agora com branch namespaced); `extract_subtasks_from_lines`
      (fan-out) delega a extração base ao parser canônico e mantém apenas o
      enriquecimento (`raw_content`, slug via manifest, `SubSpecTask`).

## 3. Contratos de Interface


### 3.2. Mapeamento de modelos (sem mudança de contrato Redis)

- O parser canônico retorna `ParsedSubTask` (estrutura leve). Cada consumidor mapeia
  para seu modelo local:
  - `harness-state`: `SubTask(id, repo, branch, status, ...)`.
  - `flywheel`: `SubTask` (state.py) e `SubSpecTask` (fanout.py, com `raw_content`).
- O contrato Redis `spec:{id}` (SPEC-002 §3.1) **não muda**: a serialização continua a
  mesma; apenas o valor de `branch` passa a ser namespaced de forma consistente.

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
