# Sub-Spec: harness-state (harness/SPEC-002-harness-ecosystem-decoupling)

> **Spec Central:** [SPEC-002: Desacoplamento do harness](specs/SPEC-002-harness-ecosystem-decoupling.md)
> **Identificador da Tarefa:** `task-3`
> **Repositório:** `eduardosan/harness-state`
> **Onda de Execução:** 2
> **Branch de Trabalho:** `agent/harness-spec-002-harness-state`

> [!WARNING]
> **Bloqueado por:** task-1 (Onda anterior). Aguardar publicação do pacote/release antes do merge final.

---

## 1. Contexto e Intenção



---

## 2. Requisitos Específicos do Componente



### Checklist de Implementação:
- [ ] Implementação de acordo com os requisitos descritos.

---

## 3. Modelo Contratual e Interfaces Compartilhadas

### 3.1. Contrato de estado Redis `spec:{id}` (existente, intocado)
- `harness-state` (cliente) e `agentic-flywheel` (fallback) já escrevem no mesmo formato.
- Nenhum contrato muda nesta spec; a duplicação de fallback direto-Redis no flywheel
  (`fanout.py`, `gate.py`) permanece para ondas futuras.
- **O bot não usa esse canal:** nenhuma conexão Redis direta do bot; todo acesso a
  estado vai pelo binário `harness` (subprocess).

### 3.2. Fronteira flywheel ⇄ slack-bot (nova)
- `harness-slack-bot` **não importa** `flywheel`: despacha exclusivamente via subprocess
  para o binário `harness` (ex.: `harness spec start/approve/run`, `harness bug ...`).
- Contrato único entre os repos: a superfície pública da CLI. Inventário de call sites
  do despacho atual (o bot hoje chama internos do parser via `dispatch_*_subcommand`):
  durante a extração, gaps de comandos públicos viram sub-specs para o flywheel
  dentro da própria wave 2.
- Config multi-projeto (`projects.yaml`) migra com o bot para o novo repo.
- **Dependência de estado:** o bot se abastece exclusivamente por comandos CLI
  (`harness spec status` etc.); não depende do pacote `harness_state` nem de
  clientes Redis próprios.

### 3.3. Registro do projeto no flywheel
- `SpecHubConfig`: `github_org=eduardosan`, `default_repo=harness-spec-hub`,
  `flywheel_repo=eduardosan/agentic-flywheel`, `local_relative_path=../harness-spec-hub`.
- Feito via arquivo `config.yaml` do workspace (não hardcode em `config.py`);
  ecossistema `paralax` segue funcionando com seu config por projeto, intocado.

### 3.4. Allowlist do pipeline (repos.yml)
- O primeiro PR no flywheel habilita o ecossistema `eduardosan/harness-*` (os 4 spokes +
  hub na allowlist). **Sem contorno:** nenhum `harness spec plan/run` contra o novo
  hub antes do merge desse PR.

### 3.5. Avaliação de código (judge)
- Todos os projetos do ecossistema `harness` conectam no flywheel para obter avaliação
  dos seus códigos; mesmas Gates e mesma lógica de dispatch que o ecossistema paralax.

## 4. Restrições e Decisões Tomadas

1. **Nomes fechados:** `harness-spec-hub`, `harness-slack-bot` (org `eduardosan`).
2. **Hub nasce federado:** estrutura + manifest + fan-out ativos desde o primeiro commit.
3. **Doc anonimizada vive no `harness-state`** (preparação open source); **capacidades
   vivem no hub** (move, não espelho); arquitetura do pipeline fica no flywheel.
4. **Governança:** alterações no flywheel somente via branch + PR (`gh pr create`),
   proibido push em `main` e criação de tags.
5. **`ansible-hetzner-new` não está na org GitHub** (remote interno git@192.168.0.200):
   o spoke de infra é resolvido como repositório local do workspace pelo fan-out
   (`locate_repo_dir`); GitHub não faz parte do fluxo desse repo.
6. **Esta spec mestre é numerada `SPEC-002`** do hub (a `SPEC-001` já havia sido
   consumida; o template vem de `agentic-flywheel/specs/SPEC-TEMPLATE.md`).
7. **Criação dos repos via `gh repo create`** dentro da execução da onda 0
   (não é passo manual do operador).
8. **Bot multi-ecossistema no dia 1:** `projects.yaml` serve `paralax-ia` e `harness`
   simultaneamente (como hoje, com o projeto novo adicionado).
9. **Instalação/atualização do bot:** pacote próprio do `harness-slack-bot`
   (não atado às releases do flywheel) **mais** mecanismo de deploy direto e seguro.
   O CT 111 não é acessível pela Internet. Caminho primário (**deploy-direct**):
   a MESMA server do runner (CT 109) registra uma 2ª instância **repo-level**
   para `eduardosan/harness-slack-bot` (org-level indisponível; a instância do
   flywheel segue intocada) — `roles/github_runner/tasks/runner_bot.yml`,
   `bot_runner_enabled: true` no playbook. O Ansible provisiona no runner a
   chave privada de deploy, o hostkey do CT e a entrada `ctb` em
   `~/.ssh/config`; o deploy do bot (jobs `build` → `deploy` `runs-on:
   self-hosted`) faz `scp ctb:<home>/` + `ssh ctb "sudo
   deploy-slackbot.sh <wheel>"`, sem segredos de pipeline no deploy.
   O CI empacota o bot (`uv build` → wheel) como artefato. Contingência
   (**deploy-via-bastion**), seguindo o procedimento validado no GitLab-CI do
   `new-blog`: `scp` até o bastion `pve2.for.mat.br:8` (exposto), `scp` interno
   ao CT e chamada em cadeia `ssh bastion "ssh slackbot-deploy@CT 'sudo
   deploy-slackbot.sh <wheel>'"`; todos os secrets obrigatórios (sem valores
   padrão). Em ambos os caminhos, o wrapper (único comando do sudoers) instala
   o artefato local via `uv tool install --force`, faz healthcheck e reinicia
   o systemd — o CT não precisa de acesso à Internet nem de credenciais GitHub
   durante o deploy; detalhamento na sub-spec de infra (wave 2).
10. **Licenças:** `harness-state` = **AGPL v3**; `harness-spec-hub` e
    `harness-slack-bot` = **licenças privadas** (repositórios privados, All Rights
    Reserved até decisão de abertura).

## 5. Não-Metas

- Não refatora o `cli.py` monólito do flywheel (separação CLI/pipeline é escopo futuro).
- Não remove o fallback Redis duplicado do flywheel (fica para spec futura).
- Não publica nada de fato no open source nesta rodada (apenas prepara; AGPLv3 fica
  no arquivo de LICENSE, com publicação para ronda futura).
- Não altera CTs/máquinas da infra (o playbook já concentra o essencial).

## 6. Anti-Metas (o que tornaria isto um fracasso)

- Desacoplar por cópia sem fronteira clara (bot importando flywheel "temporariamente").
- Specs de execução escritas fora do hub (SSOT violado desde o dia 1).
- Fan-out manual/ad-hoc no lugar da esteira (`harness spec plan`).

## 7. Abordagens Consideradas

- **A (escolhida) — bootstrap federado via o próprio flywheel:** hub criado já no padrão
  federal, registrado no config, execução das entregas via `harness spec plan` + fan-out.
  Valida a esteira desde o dia 1; custo extra de bootstrap com PR de allowlist antes do
  fan-out.
- **B — hub documental manual, fan-out depois:** rejeitada: contradiz o requisito de
  nascer federado e adia a validação da esteira.
- **C — bootstrap + execução completa no mesmo lote:** extração do bot, migração de docs
  e ansible executadas fora da esteira. Rejeitada: mistura bootstrap com execução.

## 8. O que fica para os termos (decomposição/fan-out)

- Formato exato das ondas e dependências (`manifest.yaml` derivado do frontmatter acima).
- Conteúdo executável das sub-specs de cada spoke (geradas pelo `harness spec plan`).
- Cronograma de descomissionamento do `flywheel.slack` dentro do flywheel (após wave 2).

---

## 9. Registro de fechamento (Gate 5 — transitório)

- **Status final: APPROVED** (todas as ondas entregues e deployado CT 111; tracker 5x APPROVED).
- **Gate 5 automático (LLM-as-a-Judge, DeepEval/Ollama): reprovado em 0%** na primeira execução, sem apontar requisito específico — julgou "ajustar código nos repositórios" contra entregas cuja evidência é **fora de código** (docs federadas, repos criados, deploy de prod no CT 111, pipeline de release). É um ```viés de escopo do judge``` a registrar para a esteira (futuro bug/ajuste no `judge.py` — LLM judge precisa aceitar evidência não-código). O fechamento manual aqui é o caminho honesto — "transparência > mascaramento".
- **Issues de fan-out fechadas** com o estado entregue: hub #2, flywheel #124, state #6, bot #1.
- **Deploy de produção do bot**: release `v0.1.2` (window de run #42344566617 verde), serviço `flywheel-slackbot` no CT 111 com o pacote `harness-slack-bot` instalado pelo wrapper restrito.
- Pendências de runtime de baixo impacto (documentadas, não bloqueiam): canal/usuários do Slack do projeto `harness` em `slackbot_projects` (quando o projeto tiver canal dedicado no Slack) e a publicação de fato do open source do `harness-state` (ronda futura).

---

## 4. Instruções para o Agente Autônomo e Validação

1. **Test-Driven Development (TDD):** Crie testes unitários em `tests/unit/`
   com docstring contendo o prefixo `Business Rule:`.
2. **Qualidade e Estilo:** PEP 8 estrito, Google docstrings em todas as classes,
   métodos e funções, sem funções aninhadas, sem try-except em imports.
3. **Verificação dos Sensores:** Execute `just verify` localmente para certificar
   a conformidade antes do envio do Pull Request.
