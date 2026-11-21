---
spec_id: SPEC-009G
title: 'SPEC-009G: Validação Dupla (Local Judge e Server Gate), Pipeline Poliglota
  e Workflows Reutilizáveis - harness-state'
parent_spec: SPEC-009G
repo: eduardosan/harness-state
task_id: task-1
wave: 7
branch: agent/harness-spec-009g-harness-state
tasks:
- id: task-1
  wave: 7
  branch: agent/harness-spec-009g-harness-state
  expected_version: N/A
product:
- harness
capability: agent-workflow-platform
status: READY
prompts:
- name: harness-state/coder_self_judge_instruction
  target_repo: eduardosan/harness-state
  file: src/harness_state/runtimes/coder_prompts.py
  symbol: CODER_SELF_JUDGE_INSTRUCTION
  description: Instrução de sistema para o agente local (Coder) auto-avaliar o diff
    implementado contra as regras do Judge e critérios da sub-spec antes da abertura
    de PR
- name: harness-state/judge_fast_evaluation
  target_repo: eduardosan/harness-state
  file: src/harness_state/runtimes/coder_prompts.py
  symbol: JUDGE_FAST_EVALUATION_INSTRUCTION
  description: Instrução do LLM-as-a-Judge server-side para avaliação funcional consolidada
    em voto único de alta precisão
---

# SPEC-009G: SPEC-009G: Validação Dupla (Local Judge e Server Gate), Pipeline Poliglota e Workflows Reutilizáveis - harness-state

> **Parent Spec:** `SPEC-009G` (SPEC-009G-validacao-dupla-workflows-poliglotas-e-release.md)  
> **Repositório Alvo:** `eduardosan/harness-state`  
> **Subtarefa Principal:** `task-1` (Onda 7)  
> **Branch:** `agent/harness-spec-009g-harness-state`  
> **Status:** `READY`

---

# SPEC-009G: Validação Dupla, Pipeline Poliglota e Workflows Reutilizáveis

> **Parent Spec:** `SPEC-009` ([SPEC-009-flywheel-para-harness-state.md](SPEC-009-flywheel-para-harness-state.md))  
> **Status:** `DRAFT`  
> **Onda:** 7  

---

## 1. Contexto e Motivação

Como desdobramento da transformação do `agentic-flywheel` em execution engine puro e do `harness-state` como núcleo canônico da plataforma (§4 e §5 da SPEC-009), a esteira de desenvolvimento e lançamento é expandida para sanar os gargalos de latência no release e destravar o suporte nativo a projetos poliglotas:

1. **Validação Dupla (Local Self-Judge + Server-Side Gate):**
   - O agente local passa a executar as 3 regras normativas do Judge (integridade de gates/testes, não-mascaramento de exceções e preservação de contratos públicos) via `harness judge --local` antes de abrir PRs, emitindo `.harness/verification-summary.json`.
   - O `judge.py` server-side atua como auditor soberano pré-release em voto consolidado único (< 1 min).
2. **Otimização do Lançamento com Evals Pré-Release Mantidos:**
   - As 4 fases de Python Fluente e prompts de sistema rodam obrigatoriamente antes do corte de tag, mas em paralelo via `pytest-xdist` (`pytest -n 4`), com cache inteligente baseado no hash das diretrizes (`specs/python/`, `specs/prompts/`), reduzindo o tempo de eval de 15 min para ~3 min.
3. **Pipeline de Validação Poliglota no Flywheel (`sensor_tools.py`):**
   - Desacopla `run_tdd_test` de chamadas hardcoded a `pytest`, introduzindo o padrão `LanguageTestAdapter` que delega para a interface universal `justfile` (`check`, `lint`, `test`, `verify`, `judge-local`) para Python, Go e TypeScript.
4. **Centralização de Workflows de Desenvolvimento no `harness-state`:**
   - Workflows de CI/CD do ciclo de desenvolvimento são centralizados no `harness-state` e reutilizados pelo Flywheel via `workflow_call`. O Flywheel mantém exclusivamente `config.yaml`, runners e execuções.

---

## 2. Escopo e Mapeamento de Módulos

| Repositório | Destino / Componente | Papel |
|---|---|---|
| `harness-state` | `.github/workflows/reusable-*.yml` | Workflows canônicos reutilizáveis (`spec-ci`, `tag-evaluation`, `release`) |
| `harness-state` | `src/harness_state/catalog/skills/common/` | Nova skill de auto-julgamento `harness-judge-verification` |
| `harness-state` | `src/harness_state/judge.py` | Voto consolidado e CLI `harness judge --local` |
| `harness-state` | `src/harness_state/catalog/pipeline/` | Templates padronizados de `justfile` poliglota (Python, Go, TS) |
| `agentic-flywheel` | `.github/workflows/*.yml` | Consumo dos workflows do núcleo via `workflow_call` |
| `agentic-flywheel` | `src/flywheel/runtimes/sensor_tools.py` | Desacoplamento poliglota via `LanguageTestAdapter` |

---

## 3. Critérios de Aceite (Gherkin)

### Cenário 3: Release rápido com evals paralelos e cache
- **Dado** o workflow de release disparado na main
- **Quando** a autoavaliação pré-release for executada
- **Então** os evals devem rodar em paralelo via `pytest-xdist`
- **E** diretrizes inalteradas devem utilizar o cache de hash
- **E** o corte final da tag deve ser concluído em menos de 6 minutos com qualidade 100% garantida.
