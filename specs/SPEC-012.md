---
spec_id: SPEC-012
title: Avaliação Canônica de Tags via Workflows Reutilizáveis no Harness-State, Gate
  Federado e Ciclo de Vida - harness-state
parent_spec: SPEC-012
repo: eduardosan/harness-state
task_id: task-2
wave: 2
branch: agent/harness-spec-012-harness-state
tasks:
- id: task-2
  wave: 2
  branch: agent/harness-spec-012-harness-state
  expected_version: N/A
product:
- harness
capability: agent-workflow-platform
status: READY
---

# SPEC-012: Avaliação Canônica de Tags via Workflows Reutilizáveis no Harness-State, Gate Federado e Ciclo de Vida - harness-state

> **Parent Spec:** `SPEC-012` (SPEC-012-cross-repo-tag-evaluation-gate-and-harness-lifecycle.md)  
> **Repositório Alvo:** `eduardosan/harness-state`  
> **Subtarefa Principal:** `task-2` (Onda 2)  
> **Branch:** `agent/harness-spec-012-harness-state`  
> **Status:** `READY`

---

# SPEC-012: Avaliação Canônica de Tags via Workflows Reutilizáveis no Harness-State, Gate Federado e Ciclo de Vida

> **Product:** `harness`  
> **Business Capability:** `agent-workflow-platform`  
> **Scope:** Platform  
> **Bounded Context:** Centralização de workflows reutilizáveis (`workflow_call`) de avaliação de tags e CI no `harness-state`; consumo federado no `agentic-flywheel` e spokes via GitHub App; reconciliação de estado e eliminação de retestes redundantes pós-merge; comandos canônicos de ciclo de vida e atualização do ecossistema.  
> **Status:** `APPROVED` · **Version:** `1.1.0`

---

## 1. Contexto e Motivação

Com a consolidação da arquitetura estabelecida nas **SPEC-009** e **SPEC-009G**, a delimitação de responsabilidades entre os repositórios da plataforma é estrita:
- **`harness-state` (`core`, open-source AGPL-3.0):** É o repositório central detentor de toda a inteligência, CLI canônica (`harness`), modelos, parsers, motor de julgamento (`harness_state.judge`), sensores determinísticos, templates de instalação e **workflows reutilizáveis canônicos (`.github/workflows/reusable-*.yml`)**.
- **`agentic-flywheel` (`execution-engine`, privado):** É o nó executor de infraestrutura em nuvem, responsável exclusivamente pela configuração de servidores, runners *self-hosted* (com acesso a GPU/Ollama), autenticação federada via GitHub App (`BOT_APP_ID`) e despacho de eventos. Não mantém lógica de negócio nem workflows duplicados.
- **Spokes (`paralax-ia/*`):** São os repositórios consumidores de produtos que geram releases e deploys automatizados.

### Pontos Críticos de Fricção Resolvidos por esta Spec:

1. **Ausência de Gate Canônico Centralizado para Tags:** Repositórios spokes geram tags de release e disparam deploys imediatos sem validação do juiz do Harness. A avaliação de tags deve ser padronizada por um **workflow reutilizável centralizado no `harness-state` (`reusable-tag-evaluation.yml`)**, acessível a qualquer spoke nativamente via `workflow_call` ou executado em runners self-hosted através do gateway do Flywheel via GitHub App.
2. **Eliminação de Duplicação de Workflows:** Workflows de avaliação de código e testes não devem ser reimplementados ou bifurcados no `agentic-flywheel`. O Flywheel deve apenas orquestrar runners e herdar os workflows do `harness-state`.
3. **Descontinuação de Tokens Estáticos:** Toda interoperabilidade cross-repo opera obrigatoriamente através do GitHub App canônico (`BOT_APP_ID` e `BOT_PRIVATE_KEY`), garantindo tokens efêmeros de instalação com permissões mínimas e seguras.
4. **Desperdício de Recursos em Merges na `main`:** A suíte de testes unitários pesados é redundante quando o commit mergeado já foi 100% validado com sucesso durante o Pull Request. A desduplicação deve ser embutida nos workflows reutilizáveis de CI do `harness-state`.
5. **Padronização de Comandos de Ciclo de Vida:** Consolidação prescritiva dos comandos oficiais da CLI `harness` (100% em `harness-state`) para instalar/atualizar templates nos spokes e sincronizar o `spec-hub`.

---

## 2. Escopo e Repositórios Afetados

- [x] **Sub-tarefa 1 (`eduardosan/harness-spec-hub`):** [Onda 1] [hub] Registro da SPEC-012 no catálogo e atualização da capability `agent-workflow-platform`.
- [x] **Sub-tarefa 2 (`eduardosan/harness-state`):** [Onda 2] [core]
  - Generalização do workflow reutilizável `.github/workflows/reusable-tag-evaluation.yml` para suportar tanto execução *in-tree* quanto avaliação *cross-repo* parametrizada (`target_repo`, `tag`, `commit_sha`).
  - Implementação de verificação de checks prévios no workflow reutilizável de testes (`reusable-test.yml` / `test.yml`) para pular retestes redundantes após o merge na `main`.
  - Atualização dos templates de spoke em `src/harness_state/catalog/` e `src/harness_state/installer.py` para injetar o step de tag gate consumindo o workflow reutilizável.
  - Consolidação e documentação dos comandos da CLI `harness` (`install`, `flywheel update`, `spec sync-hub`, `map-all`).
- [ ] **Sub-tarefa 3 (`eduardosan/agentic-flywheel`):** [Onda 3] [execution-engine]
  - Adequação do pipeline de release e tag do Flywheel para consumir diretamente `uses: eduardosan/harness-state/.github/workflows/reusable-tag-evaluation.yml@main`.
  - Configuração do gateway centralizado de despacho remoto (`workflow_dispatch` / `repository_dispatch`) autenticado com GitHub App (`BOT_APP_ID`) para spokes que necessitam de runners self-hosted dedicados.
  - Adoção da verificação de checks prévios na suíte de testes do Flywheel (`unit-tests.yml`).

---

## 3. Contratos de Interface e Arquitetura

### 3.1. Workflow Reutilizável Canônico de Tags (`reusable-tag-evaluation.yml` no `harness-state`)

O workflow `.github/workflows/reusable-tag-evaluation.yml` no repositório `harness-state` é o único ponto de verdade para avaliação de tags e pré-releases no ecossistema, operando via `workflow_call`:

```yaml
name: Reusable Tag Code Evaluation and Gate

on:
  workflow_call:
    inputs:
      tag:
        description: "Tag gerada ou versão candidata a ser avaliada (ex: v1.2.0)"
        required: true
        type: string
      target_repo:
        description: "Repositório do spoke a ser avaliado (opcional; vazio indica o repositório atual)"
        required: false
        type: string
        default: ""
      commit_sha:
        description: "SHA exato do commit vinculado à tag (opcional)"
        required: false
        type: string
        default: ""
      fast:
        description: "Executar avaliação consolidada em voto único (< 1 min)"
        required: false
        type: boolean
        default: true
      runs_on:
        description: "Tipo de runner para execução do gate"
        required: false
        type: string
        default: "self-hosted"
    secrets:
      token:
        description: "Token do GitHub App ou GitHub Token com acesso ao target_repo"
        required: false
    outputs:
      status:
        description: "Veredito da avaliação (APPROVED ou REJECTED)"
        value: ${{ jobs.evaluate-tag-release.outputs.status }}
      compliance_score:
        description: "Score de conformidade da release (0-100)"
        value: ${{ jobs.evaluate-tag-release.outputs.compliance_score }}
```

#### Regras de Execução do Workflow:
1. **Identificação do Alvo (In-Tree vs. Cross-Repo):**
   - Se `target_repo` estiver vazio: executa o checkout direto do repositório chamador (`actions/checkout@v4` com `fetch-depth: 0`).
   - Se `target_repo` for fornecido: utiliza o secret `token` (gerado via GitHub App) para clonar o repositório alvo com histórico completo de tags.
2. **Deteção Cirúrgica de Diff da Tag:**
   - Se a tag já existe no repositório: detecta a `PREV_TAG` imediatamente anterior e gera `git diff ${PREV_TAG}...${CURRENT_TAG} > release_diff.patch`.
   - Se for versão candidata pré-tag: compara a última tag existente com `HEAD` (`git diff ${LATEST_TAG}..HEAD > release_diff.patch`).
3. **Avaliação pelo LLM-as-a-Judge (`harness_state.judge`):**
   - Executa `uv run python -m harness_state.judge` em modo fast (`--fast`), avaliando as 3 regras normativas (integridade de gates, não-mascaramento de erros/RCA e preservação de contratos públicos) sobre o patch unificado.
4. **Emissão de Status API e Veredito:**
   - Em execuções cross-repo (`target_repo` preenchido), registra um Commit Status na Status API do GitHub no commit avaliado com contexto `flywheel/tag-gate` (`state: success` ou `state: failure`).
   - Conclui com código de saída `0` para `APPROVED` ou código `1` para `REJECTED`, bloqueando pipelines chamadores.

---

### 3.2. Consumo pelos Repositórios Spokes e Gateway do Flywheel

A validação de tags de repositórios spokes pode ocorrer através de dois padrões complementares:

#### Modelo Direto (Spoke com Runner Próprio via `workflow_call`):
No workflow de release do spoke (`.github/workflows/release.yml`), o spoke consome o workflow reutilizável do `harness-state` sem intermediários:
```yaml
jobs:
  tag-gate:
    name: "Harness Tag Gate"
    uses: eduardosan/harness-state/.github/workflows/reusable-tag-evaluation.yml@main
    with:
      tag: ${{ github.ref_name }}
      fast: true
      runs_on: self-hosted
    secrets: inherit
```

#### Modelo Federado (Gateway via `agentic-flywheel` para Runners Centralizados):
Quando o spoke roda em runners hospedados na nuvem (GitHub-hosted) sem acesso a GPU/Ollama local, ele delega a execução para o Flywheel através do GitHub App canônico:
1. O pipeline do spoke gera um token temporário da GitHub App (`BOT_APP_ID`) e despacha o evento para o Flywheel via `workflow_dispatch`.
2. O workflow do `agentic-flywheel` (`.github/workflows/tag-code-evaluation.yml`) recebe o evento e delega para o workflow reutilizável do `harness-state`:
   ```yaml
   jobs:
     evaluate-spoke:
       uses: eduardosan/harness-state/.github/workflows/reusable-tag-evaluation.yml@main
       with:
         tag: ${{ inputs.tag }}
         target_repo: ${{ inputs.target_repo }}
         commit_sha: ${{ inputs.commit_sha }}
         fast: true
       secrets:
         token: ${{ steps.app-token.outputs.token }}
   ```
3. O spoke aguarda o status `flywheel/tag-gate == success` antes de liberar o artefato no container registry ou ArgoCD.

---

### 3.3. Eliminação de Testes Redundantes no Merge da `main`

Para evitar desperdício de computação e bloqueios desnecessários nas esteiras de produção:

1. **Implementação no Workflow Reutilizável de Testes (`harness-state`):**
   O job de testes em `reusable-test.yml` (e nos templates injetados nos spokes) executa a verificação prévia de status no GitHub:
   ```bash
   # Verifica se o SHA já possui check run de teste concluído com sucesso
   PREV_CHECK=$(gh api "repos/${GITHUB_REPOSITORY}/commits/${GITHUB_SHA}/check-runs" \
     --jq '.check_runs[] | select(.name == "Test" and .conclusion == "success") | .id' 2>/dev/null || true)

   if [ -n "$PREV_CHECK" ]; then
     echo "Commit ${GITHUB_SHA} já validado com sucesso no PR (Check Run ID: ${PREV_CHECK}). Pulando reteste redundante na main."
     exit 0
   fi
   ```
2. **Separação de Eventos:** Suítes lentas de linters e testes unitários ficam vinculadas exclusivamente ao trigger `pull_request`. O trigger `push: branches: [main]` executa apenas checagem rápida de integridade e o cálculo do SemVer.
3. **Commits com `[skip ci]`:** Releases automatizadas e bumps de versão não reexecutam as suítes de teste.

---

### 3.4. Comandos Canônicos de Ciclo de Vida da CLI `harness`

Toda a interface de CLI pública reside exclusivamente no pacote `harness-state`. O `agentic-flywheel` não possui comandos de CLI públicos (conforme SPEC-009F).

#### A. Gerenciamento e Atualização de Spokes:
```bash
# Instalar ou atualizar templates de sensores, justfile e workflows reutilizáveis no spoke
harness install --path /caminho/para/repositorio-spoke

# Atualizar dependências e compatibilidade do Flywheel no spoke
harness flywheel update /caminho/para/repositorio-spoke --version 0.4.1

# Atualizar em lote todos os spokes declarados no config.yaml com estratégia semver
harness flywheel update-all --strategy patch

# Verificação estática local de conformidade (ast_sensor, complexidade, pyright)
harness verify --path /caminho/para/repositorio-spoke
```

#### B. Sincronização e Governança do Spec Hub:
```bash
# Sincronizar sub-spec do spoke de volta para o spec-hub mestre
harness spec sync-hub \
  --repo-spec specs/SPEC-012.md \
  --hub-spec /caminho/para/spec-hub/specs/SPEC-012.md \
  --workspace-root /caminho/para/workspace

# Evolução de especificações existentes (Living Specs)
harness spec update SPEC-012 \
  --prompt "Generalizar reusable-tag-evaluation.yml para suporte cross-repo" \
  --author "@eduardo"

# Mapear e sincronizar o grafo de produtos, capacidades e contratos de todo o ecossistema
harness map-all
```

---

## 4. Critérios de Aceitação (Gherkin)

### Cenário 1: Tag de Spoke Avaliada Diretamente via Workflow Reutilizável
- **Dado** que uma nova tag `v1.2.0` foi gerada em um repositório spoke
- **Quando** o workflow de release do spoke invocar `uses: eduardosan/harness-state/.github/workflows/reusable-tag-evaluation.yml@main`
- **E** o patch de código respeitar integralmente as 3 regras normativas do Judge
- **Então** o job reutilizável deve concluir com status `success` e veredito `APPROVED`
- **E** a esteira do spoke deve prosseguir para a publicação do pacote e deploy.

### Cenário 3: Desduplicação de Testes no Merge da Main
- **Dado** que um Pull Request concluiu com sucesso o check `Test` no CI
- **Quando** o PR for mesclado na branch `main`
- **Então** o workflow de CI deve identificar o check run prévio aprovado no SHA
- **E** deve registrar o log de bypass e finalizar com sucesso em menos de 10 segundos sem rodar a suíte pesada.

### Cenário 4: Atualização de Spoke via CLI `harness`
- **Dado** um repositório spoke com versões defasadas de sensores ou workflows
- **Quando** o operador executar `harness install --path <spoke>`
- **Então** o `justfile`, os sensores em `.harness/sensors/` e os workflows reutilizáveis devem ser sincronizados com a versão mais recente do `harness-state`.

---

## 5. Plano de Rollout e Compatibilidade

1. **Fase 1 (Onda 1):** Aprovação e merge desta SPEC-012 no repositório `eduardosan/harness-spec-hub`.
2. **Fase 2 (Onda 2 - `harness-state`):**
3. **Fase 3 (Onda 3 - `agentic-flywheel`):**
4. **Compatibilidade:** Retrocompatível; chamadas in-tree existentes continuam funcionando sem necessidade de alteração de parâmetros.

   - Lançamento de release semver do `harness-state`.
