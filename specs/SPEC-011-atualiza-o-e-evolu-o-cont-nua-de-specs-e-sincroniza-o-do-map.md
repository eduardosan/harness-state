---
spec_id: SPEC-011
title: Atualização e Evolução Contínua de Specs, Descoberta Inteligente e Sincronização
  de Capacidades - harness-state
parent_spec: SPEC-011
repo: eduardosan/harness-state
task_id: task-2
wave: 2
branch: agent/harness-spec-011-harness-state
tasks:
- id: task-2
  wave: 2
  branch: agent/harness-spec-011-harness-state
  expected_version: N/A
product:
- harness
capability: agent-workflow-platform
status: IN_PROGRESS
prompts:
- name: harness_state/instruction
  target_repo: eduardosan/harness-state
  file: src/harness_state/runtimes/coder_prompts.py
  symbol: ARCHITECT_SPEC_DISCOVERY_INSTRUCTION
  description: Instrução do Agente Arquiteto para inspecionar o catálogo de specs
    existentes durante o comando plan, detectando similaridade semântica para evitar
    specs duplicadas e direcionar para evolução
- name: harness_state/instruction
  target_repo: eduardosan/harness-state
  file: src/harness_state/runtimes/coder_prompts.py
  symbol: ARCHITECT_SPEC_EVOLUTION_INSTRUCTION
  description: Instrução do Agente Arquiteto para reconciliar deltas de especificações
    existentes, preservando tarefas congeladas e atualizando contratos
- name: harness_state/instruction
  target_repo: eduardosan/harness-state
  file: src/harness_state/runtimes/coder_prompts.py
  symbol: CODER_CODE_EVOLUTION_INSTRUCTION
  description: Instrução do Agente Coder (Pydantic AI Coder) para evoluir a base de
    código a partir de contratos atualizados via TDD Fail-First e zero regressão
- name: harness_state/instruction
  target_repo: eduardosan/harness-state
  file: src/harness_state/runtimes/coder_prompts.py
  symbol: CAPABILITY_MAP_SYNC_INSTRUCTION
  description: Instrução de sistema para o agente autor da spec atualizar o mapa de
    capacidades (DDD) após aprovação formal (Gate 2)
---

# SPEC-011: Atualização e Evolução Contínua de Specs, Descoberta Inteligente e Sincronização de Capacidades - harness-state

> **Parent Spec:** `SPEC-011` (SPEC-011-atualiza-spec.md)  
> **Repositório Alvo:** `eduardosan/harness-state`  
> **Subtarefa Principal:** `task-2` (Onda 2)  
> **Branch:** `agent/harness-spec-011-harness-state`  
> **Status:** `IN_PROGRESS`

---

## 1. Contexto e Motivação

No modelo de **Spec-Driven Development (SDD) Federado**, as especificações técnicas (`specs/SPEC-*.md`) constituem a Fonte Única da Verdade (SSOT) para o design arquitetural, contratos de interface e critérios de aceite antes de qualquer linha de código de produção ser escrita.

### 1.1. O Problema da Rigidez "Forward-Only" e Proliferação de Specs
O ecossistema foi concebido originalmente em um fluxo unidirecional rígido: `start -> plan -> approve -> fanout -> run -> finish`. Quando uma funcionalidade precisa mudar, requisitos de negócio evoluem ou falhas de design são identificadas em módulos já especificados ou implementados, a esteira apresentava três graves limitações:
1. **Proliferação de Specs Fragmentadas por Desconhecimento do Operador:** Frequentemente, o operador ou agente que dispara `harness spec plan` não tem conhecimento prévio de todas as especificações existentes no hub. Como o comando `plan` gerava cegamente um novo arquivo rascunho (`SPEC-XXX.md`) quando o título não casava perfeitamente com um arquivo existente, criavam-se múltiplas specs sobrepostas (ex: `SPEC-012`, `SPEC-013`...) para alterar o mesmo domínio de software, espalhando a verdade arquitetural e gerando débitos documentais.
2. **Incapacidade de Reconciliar Código com Specs Existentes:** A edição direta do arquivo Markdown de uma spec em andamento (`IN_PROGRESS`) ou já concluída (`IMPLEMENTED`) quebrava o tracking no Redis StateStore (`spec:{id}`). A esteira não sabia distinguir o que já havia sido entregue e mergeado nos spokes do que representava uma nova alteração.
3. **Ausência de Propagação Automática Arquitetura → Código:** Modificar classes, métodos ou contratos em uma spec existente não disparava um fluxo ordenado de atualização de código nos repositórios alvo, forçando intervenções manuais ou desvios do regime SDD.

### 1.2. O Descolamento do Mapa de Capacidades (Capability Drift)
As Business Capabilities (`capabilities/<capability>/capability.yaml`) e manifestos de produtos em `products/` mapeiam a linguagem ubíqua, o context map e os contratos do ecossistema sob a ótica de Domain-Driven Design (DDD).
Atualmente, quando uma spec é criada, aprovada e executada, o mapa de capacidades frequentemente não é atualizado ou depende de cron jobs assíncronos desconectados do ciclo de vida da spec. Isso provoca drift arquitetural entre o que as specs declaram e o que o catálogo de capacidades reflete.

### 1.3. Diretrizes Canônicas do Operador
> *"Antes de criar uma nova spec, precisa atualizar uma spec existente e ser capaz de atualizar a arquitetura e o código da spec."*  
> *"Sempre que uma spec for aprovada o mapa de capacidades precisa ser atualizado caso seja necessário. Isso deve ser feito pelo mesmo agente que criou a spec."*  
> *"Considere que a pessoa que executa o comando de plan não sabe se existe alguma spec relacionada. Então todo comando de plan deve verificar se realmente se trata de uma nova spec ou se estamos alterando specs existentes."*

Esta especificação define:
1. **Pre-flight Spec Discovery no Comando `plan`:** Todo comando `harness spec plan` inspeciona proativamente o repositório de specs do hub. Utilizando correspondência semântica e estrutural (domínio, capability, bounded context e contratos), o motor identifica se a intenção do usuário altera uma spec existente, orientando a evolução do documento existente em vez de criar duplicidades.
2. O mecanismo de **Evolução Contínua de Especificações (Living Specs)**, permitindo atualizar a arquitetura e os contratos de uma especificação existente via comandos CLI dedicados (`harness spec update` / `harness spec refine --evolve`).
3. O **Congelamento Atômico de Tarefas Concluídas** (`frozen_tasks`), isolando apenas o delta evolutivo para re-fanout sem regredir nem reexecutar código entregue.
4. A **Propagação Atômica Arquitetura → Código** com diretriz explícita de TDD Fail-First e zero regressão no Coder Runtime.
5. A **Sincronização Obrigatória do Mapa de Capacidades no Gate 2 (Aprovação)**: assim que a spec é formalmente aprovada (`harness spec approve`), o *mesmo agente* de IA que planejou/refinou a spec é acionado para avaliar e atualizar o mapa de capacidades (`capabilities/<capability>/capability.yaml`) e os produtos associados, garantindo paridade imediata entre spec e mapa de capacidades.

---

## 2. Escopo e Repositórios Afetados

- [ ] **Sub-tarefa 1 (`eduardosan/harness-spec-hub`):** [Onda 1] Atualizar o template padrão `SPEC-TEMPLATE.md`, as diretrizes de governança de Living Specs, as regras de descoberta semântica no catálogo e a automação do mapa de capacidades em `capabilities/` durante a aprovação formal de specs (Gate 2).
- [x] **Sub-tarefa 2 (`eduardosan/harness-state`):** [Onda 2] Implementar motor de descoberta prévia de specs (`SpecDiscoveryEngine`), modelos de revisão (`SpecRevision`), motor de reconciliação de deltas (`SpecEvolutionEngine`), comando `harness spec update`, enriquecimento do comando `harness spec plan` com roteamento inteligente, gatilho de sincronização do mapa de capacidades no comando `harness spec approve` mantendo a sessão/identidade do agente autor, e registrar prompts canônicos em `src/harness_state/runtimes/coder_prompts.py`.
- [ ] **Sub-tarefa 3 (`eduardosan/agentic-flywheel`):** [Onda 2] Adaptar o fan-out incremental (`src/flywheel/spec_fanout.py`) para emitir sub-specs de evolução sem colidir com branches de tarefas já concluídas, e integrar o Coder Runtime para executar a evolução de código com TDD Fail-First.

---

## 3. Contratos de Interface


### 3.2. Modelos de Dados no `harness-state` (`harness_state/models.py`)

```python
from datetime import UTC, datetime
from enum import StrEnum
from pydantic import BaseModel, Field
from harness_state.models import SubTask, TaskState


class RevisionType(StrEnum):
    """Tipo de revisão aplicada à especificação técnica."""

    MINOR_EVOLUTION = "MINOR_EVOLUTION"
    MAJOR_BREAKING = "MAJOR_BREAKING"
    PATCH_CORRECTION = "PATCH_CORRECTION"


class SpecRevision(BaseModel):
    """Registro imutável de uma revisão aplicada a uma spec existente."""

    revision_id: str
    spec_id: str
    version: str
    revision_type: RevisionType
    author: str
    instruction: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    frozen_task_ids: list[str] = Field(default_factory=list)
    new_task_ids: list[str] = Field(default_factory=list)
    modified_contracts: list[str] = Field(default_factory=list)


class SpecMatch(BaseModel):
    """Resultado da correspondência de uma spec existente durante o comando plan."""

    spec_id: str
    title: str
    file_path: str
    similarity_score: float
    matched_capability: str = ""
    relevance_summary: str = ""
    recommended_action: str = "evolve"  # "evolve" | "new_spec"


class CapabilitySyncResult(BaseModel):
    """Resultado da sincronização do mapa de capacidades pós-aprovação."""

    capability_id: str
    updated: bool
    added_terms: list[str] = Field(default_factory=list)
    added_contracts: list[str] = Field(default_factory=list)
    added_specs: list[str] = Field(default_factory=list)
    sync_agent: str = ""
    diff_summary: str = ""


class SpecEvolutionPlan(BaseModel):
    """Plano de evolução gerado a partir do diff semântico de uma spec."""

    spec_id: str
    current_version: str
    target_version: str
    frozen_tasks: list[SubTask]
    tasks_to_execute: list[SubTask]
    affected_repositories: list[str]
    has_breaking_changes: bool = False
```

Extensão do modelo `SpecRun` em `harness_state/models.py`:

```python
class SpecRun(BaseModel):
    # Campos existentes preservados...
    spec_version: str = "1.0.0"
    author_agent: str = "antigravity"
    author_model: str = ""
    revisions: list[SpecRevision] = Field(default_factory=list)
    capability_synced: bool = False

    def apply_evolution(
        self,
        new_version: str,
        revision: SpecRevision,
        new_subtasks: list[SubTask],
    ) -> None:
        """Aplica uma evolução à spec, preservando tarefas concluídas como congeladas."""
        self.spec_version = new_version
        self.revisions.append(revision)
        for task in new_subtasks:
            self.tasks[task.id] = task
        if self.status in (TaskState.READY, TaskState.APPROVED):
            self.status = TaskState.IN_PROGRESS
```

---

## 4. Critérios de Aceitação (Gherkin)

### Cenário 1: Descoberta prévia e redirecionamento de spec existente no comando plan
- **Dado** uma especificação `SPEC-008` já existente no hub descrevendo o parser de subtarefas
- **Quando** o operador executa `harness spec plan "Melhorar parser para suportar formato YAML de subtarefas"` sem especificar o ID da spec
- **Então** o motor de descoberta deve detectar que `SPEC-008` cobre o mesmo domínio com score $\ge 0.8$
- **E** a CLI deve informar ao operador que `SPEC-008` foi identificada
- **E** direcionar o fluxo para a evolução de `SPEC-008` em vez de criar uma nova spec `SPEC-012` concorrente.

### Cenário 2: Confirmação de criação legítima de nova spec no comando plan
- **Dado** um spec-hub sem nenhuma especificação cobrindo processamento de pagamentos
- **Quando** o operador executa `harness spec plan "Gateway de pagamentos Pix assíncrono"`
- **Então** o motor de descoberta deve verificar que a similaridade com specs existentes é menor que o threshold de corte
- **E** criar legitimamente uma nova especificação com o próximo ID livre disponível.

### Cenário 3: Refinamento e atualização in-flight com preservação de tarefas concluídas
- **Dado** uma especificação `SPEC-011` com `task-1` (Onda 1) em estado `APPROVED` e `task-2` (Onda 2) em estado `PENDING`
- **Quando** o operador executa `harness spec refine SPEC-011 -p "Adicionar endpoint de telemetria e expandir contratos"`
- **Então** o motor de reconciliação deve marcar `task-1` como `frozen` (não reexecutável)
- **E** a versão da spec deve ser incrementada para uma revisão evolutiva
- **E** a sub-tarefa `task-2` deve ter seus contratos atualizados sem descartar o escopo de `task-1`.

### Cenário 4: Sincronização do mapa de capacidades pelo mesmo agente autor na aprovação (Gate 2)
- **Dado** uma especificação `SPEC-011` planejada pelo agente `antigravity` vinculada à capability `agent-workflow-platform`
- **Quando** o operador executa `harness spec approve SPEC-011`
- **Então** o orquestrador deve invocar o mesmo agente (`antigravity`) com a instrução `spec/capability_map_sync`
- **E** o agente deve inspecionar se a spec introduziu novos termos ou contratos
- **E** o arquivo `capabilities/agent-workflow-platform/capability.yaml` deve ser atualizado incluindo `SPEC-011` em `specs` com status `APPROVED` e quaisquer novos termos de linguagem ubíqua.

### Cenário 5: Propagação de novos contratos para a base de código via TDD Fail-First
- **Dado** uma sub-spec de evolução contendo novos contratos de interface na Seção 3
- **Quando** o Agente Coder inicia a execução da tarefa no spoke alvo
- **Então** ele deve escrever os testes unitários correspondentes antes de modificar o código de produção
- **E** os novos testes devem falhar (RED) comprovando a ausência do novo comportamento
- **E** após a implementação, 100% dos testes legados e novos devem passar (GREEN).

### Cenário 6: Rejeição de breaking changes silenciosas em tarefas congeladas
- **Dado** uma tarefa `task-1` congelada com contrato `def parse(spec: str) -> dict`
- **Quando** uma alteração na spec tentar renomear ou remover `def parse` sem declarar migração formal
- **Então** o linter de spec e o validador de contratos devem reprovar o Gate de Especificação
- **E** emitir feedback orientando o operador a manter retrocompatibilidade ou definir uma nova onda de migração.

---

## 5. Plano de Rollout e Compatibilidade

1. **Compatibilidade com Specs Legadas:**
2. **Versionamento e Publicação:**
3. **Rollback:**

   - Implementação introduzida no `harness-spec-hub` (Onda 1) e `harness-state` na release minor `v0.8.0` (Onda 2).
   - `agentic-flywheel` atualiza a dependência para `harness-state>=0.8.0` sem breaking changes em comandos existentes.
