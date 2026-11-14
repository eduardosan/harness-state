---
spec_id: SPEC-001
title: 'Desacoplamento do harness: spec hub federado, CLI anonimizado, bot Slack e
  infra cloud-harness - harness-state'
parent_spec: SPEC-002
repo: eduardosan/harness-state
task_id: task-3
wave: 2
branch: feat/spec-001-harness-state
tasks:
- id: task-3
  wave: 2
  branch: feat/spec-001-harness-state
  expected_version: N/A
product:
- harness
capability: agent-workflow-platform
status: IN_PROGRESS
---

# SPEC-001: Desacoplamento do harness: spec hub federado, CLI anonimizado, bot Slack e infra cloud-harness - harness-state

> **Parent Spec:** `SPEC-001` (SPEC-001-harness-ecosystem-decoupling.md)  
> **Repositório Alvo:** `eduardosan/harness-state`  
> **Subtarefa Principal:** `task-3` (Onda 2)  
> **Branch:** `feat/spec-001-harness-state`  
> **Status:** `IN_PROGRESS`

---

## 1. Contexto e Motivação

O `agentic-flywheel` (~30k LOC) acumulou cinco produtos em um único repositório:
(a) pipeline SDD de specs, (b) pipeline de bugs, (c) bot do Slack, (d) instalador/catálogo
de harness e (e) governança (Langfuse, gates, judge). O `cli.py` sozinho tem 4.280 linhas,
e o `flywheel/slack` (~1.900 LOC) re-despacha diretamente para o código do CLI — Slack, CLI
e pipeline vivem no mesmo grafo de importação.

O ecossistema `harness` passa a ser organizado em **componentes separados**, governados por
um **spec hub federado próprio** (`harness-spec-hub`), seguindo o padrão já validado em
`paralax-spec-hub`: spec mestre + `manifest.yaml` + fan-out cirúrgico via o próprio flywheel
(dogfooding da esteira desde o primeiro dia). Todos os projetos do ecossistema conectam no
flywheel para obter avaliação de seus códigos (judge/gates), seguindo a mesma lógica de
GitHub Actions do ecossistema paralax (`agent.yml`, `spec-dispatch.yml`,
`capabilities-sync.yml` replicados nos novos spokes — exceto o repo de infra, que é
local-only).

### Artifacts afetados hoje (mapa de origem)

| Artefato | Hoje | Destino |
|---|---|---|
| Doc de fluxo sem especificação de servidores (anonimizada) | `agentic-flywheel/docs/architecture/federated-sdd-platform.md` (§ fluxo local) + `docs/cli.md` | `harness-state/docs/` (open source) |
| Catálogo de capacidades e arquitetura de capacidades | `agentic-flywheel/docs/architecture/*` | `harness-spec-hub/` (catálogo de capacidades) |
| Docs de arquitetura do flywheel (pipeline, WIF/GCP, judge) | `agentic-flywheel/docs/architecture/*` | Mantidos em `agentic-flywheel/docs/` |
| Bot do Slack (`src/flywheel/slack/`) | `agentic-flywheel` | `harness-slack-bot` (novo repo) |
| Infra (CT 108–111, Ollama, runner, ES, bot) | `ansible-hetzner-new/cloud-harness.yml` | Consolidados no mesmo playbook |

## 2. Escopo e Repositórios Afetados

- [ ] [Onda 0] `eduardosan/harness-spec-hub`: criação do hub — estrutura federal
      (`manifest.yaml`, `specs/SPEC-TEMPLATE.md`, `products/`, `capabilities/`, `README.md`),
      esta SPEC-001 como spec mestre, registro do projeto no config do flywheel.
- [ ] [Onda 0] `eduardosan/harness-slack-bot`: criação do repo-skeleton (novo projeto,
      vazio, com README + LICENSE definindo o destino da extração).
- [ ] [Onda 1] `eduardosan/harness-state`: doc anonimizada de fluxo (sem IPs/tokens/Redis
      interno/GCP) + pass de preparação para open source (README cosmético, sanitização).
- [ ] [Onda 1] `eduardosan/agentic-flywheel`: catálogo de capacidades movido para o hub;
      docs de arquitetura e pipeline mantidos no repo; allowlist `repos.yml` atualizada
      (via PR — sem push em main).
- [ ] [Onda 2] `eduardosan/harness-slack-bot`: extração do código de `src/flywheel/slack/`,
      fronteira de despacho via subprocess do CLI `harness` (sem importar `flywheel`,
      sem Redis direto).
- [ ] [Onda 2] `eduardosan/ansible-hetzner-new` (git privado interno): role `slackbot`
      atualizada para o novo repo (serviço deixa de ser `python -m flywheel.slack.app`),
      playbook permanece centralizado em `cloud-harness.yml`; deploy direto segue
      caminho seguro (ver §4.9).

## 4. Restrições e Decisões Tomadas

1. **Nomes fechados:** `harness-spec-hub`, `harness-slack-bot` (org `eduardosan`).
2. **Hub nasce federado:** estrutura + manifest + fan-out ativos desde o primeiro commit.
3. **Doc anonimizada vive no `harness-state`** (preparação open source); **capacidades
   vivem no hub** (move, não espelho); arquitetura do pipeline fica no flywheel.
4. **Governança:** alterações no flywheel somente via branch + PR (`gh pr create`),
   proibido push em `main` e criação de tags.
5. **`ansible-hetzner-new` não está na org GitHub** (remote interno git@{{SERVER_IP}}):
   o spoke de infra é resolvido como repositório local do workspace pelo fan-out
   (`locate_repo_dir`); GitHub não faz parte do fluxo desse repo.
6. **Esta spec mestre é numerada `SPEC-001`** do novo hub (numeração não herda o
   flywheel; o template vem de `agentic-flywheel/specs/SPEC-TEMPLATE.md`).
7. **Criação dos repos via `gh repo create`** dentro da execução da onda 0
   (não é passo manual do operador).
8. **Bot multi-ecossistema no dia 1:** `projects.yaml` serve `paralax-ia` e `harness`
   simultaneamente (como hoje, com o projeto novo adicionado).
9. **Instalação/atualização do bot:** pacote próprio do `harness-slack-bot`
   (não atado às releases do flywheel) **mais** mecanismo de deploy direto e seguro
   no servidor: workflow de release do bot publica a versão e atualiza o CT 111 com
   chave SSH de comando restrito (deploy user sem acesso root amplo), reiniciando o
   serviço systemd; detalhamento na sub-spec de infra (wave 2).
10. **Licenças:** `harness-state` = **AGPL v3**; `harness-spec-hub` e
    `harness-slack-bot` = **licenças privadas** (repositórios privados, All Rights
    Reserved até decisão de abertura).
