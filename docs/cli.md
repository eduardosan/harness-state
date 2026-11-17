# Referência de Comandos da CLI `harness`

> Plataforma de Harness SDD Federada (`eduardosan/harness-state`).
> A CLI é unificada no binário **`harness`** — os antigos aliases `flywheel` e
> `harness-state` foram removidos. Os ciclos de **spec** e de **bug** ficam
> exclusivamente dentro de seus grupos (`harness spec ...` e `harness bug ...`).

---

## 1. Mapa geral

| Grupo / Comando | Papel no fluxo |
|---|---|
| `harness spec` | Ciclo de vida de especificações (SDD) — Gates 2, 3 e 5 |
| `harness bug` | Ciclo de vida de bugs (Spec-Driven Bugfix) — Gate 0 a encerramento |
| `harness init` | Inicializa o harness no módulo (skills + pipeline + sensores) |
| `harness clone` | Clona/atualiza repositórios do `manifest.yaml` |
| `harness config` | Exibe e valida a configuração local ativa |
| `harness setup` | Gera/valida `config.yaml` a partir do ambiente (usado em CI) |
| `harness update` | Atualiza o State Tracker (Redis) — usado pela esteira |
| `harness verify` | Executa `just verify` + sensores no módulo |
| `harness audit` | Audita cobertura da Linguagem Ubíqua e integridade de dados sensíveis |
| `harness map-all` | Mapeia Produtos, Capabilities e Contratos do ecossistema |
| `harness superpowers install` | Baixa skills do upstream do Superpowers |
| `harness slack start` | Inicia o Daemon do Slack Bot (Socket Mode) |

---

## 2. Comandos de infraestrutura (top-level)

### `harness init`
```bash
harness init                          # na raiz do módulo
harness init --path ./meu-projeto     # a partir da raiz do workspace
harness init --all                    # lote: auto-clona e inicializa via manifest.yaml
harness init --ci --path .            # modo CI: só sensores e pipeline de verificação
harness init --with-superpowers       # inclui skills do upstream oficial
```
| Flag | Uso |
|---|---|
| `--path` | Raiz do pacote local (default: `.`) |
| `--all / --manifest / --https` | Inicialização em lote via manifesto |
| `--language` | Força a linguagem (`python`, `go`, `typescript`, `cicd`); padrão: auto-detecção |
| `--ci` | Instala apenas sensores e pipeline de verificação |
| `--force` | Sobrescreve justfile e config.yaml existentes |
| `--with-superpowers` | Baixa as skills do upstream do Superpowers |

O que instala: skills por linguagem + `common` em `.claude/skills/`, diretrizes de
agentes em `AGENTS.md`/`CLAUDE.md`, `justfile` da linguagem com a receita `verify`
(mandatory checks), sensores determinísticos em `.harness/sensors/`
(`format_feedback.sh`, `ast_sensor.py`, `complexity_sensor.py`, `type_baseline.py`,
`spec_router.py`, `cicd_sensor.py`, `config_sensor.py`), hook `pre-commit` e
isolamento 12-Factor no `.gitignore`.

### `harness clone`
```bash
harness clone [--workspace PATH] [--manifest path/to/manifest.yaml] [--https]
```

### `harness config`
```bash
harness config [--path PATH] [--config-file path/to/config.yaml]
```

### `harness setup`
```bash
harness setup [--path PATH] [--ci]    # passo padrão em CI: `harness setup --ci`
```

### `harness update` (State Tracker — esteira)
```bash
harness update SPEC-XXX task-1 READY --worker runner-a --pr 42
```
| Argumento/Flag | Uso |
|---|---|
| `SPEC_ID TASK_ID NEW_STATUS` | Ex.: `SPEC-004 task-2 IN_PROGRESS` |
| `--worker` | Identificador do worker (default: `local-dev`) |
| `--pr` | Número do Pull Request aberto |

### `harness verify`
```bash
harness verify --path ./meu-projeto
```

### `harness audit`
```bash
harness audit --spec-hub-dir ../<project>-spec-hub [--capability pix] [--workspace-root .]
harness audit --mask-sensitive-data   # auditoria contra vazamento de IPs ou tokens sensíveis
```

### `harness map-all`
```bash
harness map-all --spec-hub-dir ../<project>-spec-hub [--workspace-root .]
```

### `harness superpowers install` e `harness slack`
```bash
harness superpowers install [--path PATH] [--repo https://github.com/obra/superpowers.git]
harness slack start                   # daemon do Slack Bot em Socket Mode
```

---

## 3. Grupo `spec` — ciclo de vida de especificações

Fluxo canônico: `spec start` ➔ `spec plan` (refino + fan-out + ondas) ➔ Gate 2
(`spec approve`) ➔ `spec run` (ondas/humano-in-the-loop) ➔ `spec continue` ➔
`spec finish` (Gate 5).

| Comando | Função |
|---|---|
| `spec start` | Cria rascunho da spec com pré-voo (fetch/clone de spokes) |
| `spec plan` | Cria/refina a spec com IA, calcula ondas topológicas e faz fan-out (Fase 1) |
| `spec approve` | Gate 2: transiciona DRAFT ➔ APPROVED e sincroniza o spec-hub |
| `spec run` | Executa o pipeline autônomo completo de ondas (Fase 2) |
| `spec continue` | Retoma a execução após pausa/bloqueio (Fase 3a) |
| `spec status` | Exibe o progresso das ondas no State Tracker |
| `spec watch` | Acompanhamento em tempo real (Rich Live) |
| `spec finish` | Fechamento transacional: Gate 5, Langfuse, merges (Fase 3b) |
| `spec refine` | Refina spec in-flight preservando tarefas concluídas |
| `spec fanout` | Decompõe a spec mestra em sub-specs nos spokes |
| `spec sync-hub` | Sync-back: reconcilia sub-spec do spoke no spec-hub |

### Uso típico
```bash
# 1. Planejamento (cria OU refina a spec, calcula ondas, fan-out e Issues)
harness spec plan "Integração Pix via Webhook"
harness spec plan specs/SPEC-042.md --manifest ../<project>-spec-hub/manifest.yaml
harness spec plan SPEC-004 "Detalhe contratos Pydantic e adicione a camada de SDK"

# 2. Gate 2 (opcional: o spec run oferece aprovação interativa se estiver DRAFT)
harness spec approve SPEC-004

# 3. Execução das ondas (humano-in-the-loop entre ondas)
harness spec run SPEC-004

# 4. Monitoramento e retomada
harness spec status SPEC-004
harness spec watch SPEC-004 --interval 2.0
harness spec continue SPEC-004

# 5. Refino in-flight (preserva tasks congeladas)
harness spec refine SPEC-004 -p "Adicionar cenário de idempotência" --path . --ci

# 6. Decomposição e reconciliação manual
harness spec fanout specs/SPEC-042.md --workspace-root . --manifest ../<project>-spec-hub/manifest.yaml
harness spec sync-hub --repo-spec specs/SPEC-042.md --hub-spec ../<project>-spec-hub/specs/SPEC-042.md

# 7. Fechamento transacional (Gate 5, prompts e merges)
harness spec finish SPEC-004
```

---

## 4. Grupo `bug` — ciclo de vida de bugs (Spec-Driven Bugfix)

Fluxo canônico: `bug logs` (investigação) ➔ `bug plan` (Gate 0) ➔ gatilho
(`bug ready`) ➔ `bug run` (TDD Red ➔ Fix ➔ Green) ➔ `bug rca` ➔ `bug finish`.

| Comando | Função |
|---|---|
| `bug plan` | Elicita o plano estruturado do defeito com IA e abre a Issue (Gate 0) |
| `bug logs` | Consulta cirúrgica do GCP Cloud Logging via `gcloud` |
| `bug ready` | Gatilho canônico: transiciona a issue para `status:bug/ready` |
| `bug run` | Ciclo interativo TDD (Red ➔ Fix com IA ➔ Green ➔ sensores ➔ PR) |
| `bug verify-repro` | Valida a fase Red: o teste de repro DEVE falhar |
| `bug generate-test` | Instancia fisicamente o teste TDD Fail-First a partir do plano |
| `bug rca` | Registra o diagnóstico de causa raiz (RCA) na Issue |
| `bug continue` | Retoma o bug após aprovação da spec no Gate 2 (Fase 3a) |
| `bug finish` | Encerra a issue, promove prompts e registra telemetria (Passo 15) |

### Uso típico
```bash
# 1. Investigação de logs (opcional)
harness bug logs --container app-crm --severity ERROR --since 1h
harness bug logs --container app-crm --dry-run

# 2. Planejamento (Gate 0): elicita, gera contrato TDD e abre a Issue
harness bug plan "Erro 500 ao processar webhook sem customer_id" --repo <org>/app-crm
harness bug plan "<sintomas>" --triage            # sem certeza do spoke
harness bug plan "<sintomas>" --ready             # elicita e já gera o gatilho
harness bug plan 105 "Incluir validação de customer_id"   # refina issue existente

# 3. Contrato TDD Fail-First e confirmação do Red
harness bug generate-test 105 --repo-dir ../app-crm
harness bug verify-repro tests/unit/test_webhook_customer.py

# 4. Gatilho canônico (opcional; `bug plan --ready` já faz)
harness bug ready 105 --repo <org>/app-crm

# 5. Execução do ciclo (com Gate 2 até Green)
harness bug run 105
harness bug run 105 --skip-agent            # valida manualmente sem acionar IA
harness bug run 105 -m ollama-local/qwen2.5-coder:14b --max-iterations 5
harness bug continue 105                    # após aprovar a spec no Gate 2

# 6. Diagnóstico de causa raiz e encerramento
harness bug rca --issue 105 --summary "Cálculo ignorava fuso" --action update-spec --spec SPEC-012
harness bug finish 105 --pr 42 --prompt <org>/support
```

---

## 5. Fluxo remoto (Slack)

Os mesmos ciclos estão disponíveis via Slash Commands do Slack Bot (daemon iniciado
por `harness slack start`): `/flywheel spec plan|run|approve|finish` e
`/flywheel bug plan|logs|run|finish` (o prefixo `/flywheel` é a marca do bot no
Slack; no terminal a CLI é `harness`).

---

## 6. Remoções e substituições canônicas

| Removido | Substituição canônica |
|---|---|
| `flywheel` / `harness-state` (binários separados) | `harness` (binário único do `harness-state`) |
| Top-level `run` | `harness spec run` |
| Top-level `plan` | `harness spec plan` |
| Top-level `status` / `watch` | `harness spec status` / `harness spec watch` |
| Top-level `resume` | `harness spec continue` |
| Top-level `sync` | automático no fechamento (`spec finish`, `bug finish`, Gate) |
| Top-level `update-spec` | automático no `spec approve` / `bug finish` |
| Grupo `prompt` (pull/push/promote) | governança automática dentro do ciclo (SPEC-PROMPT-01) |
| `spec draft` / `spec amend` | `harness spec start` / `harness spec refine` |
| `spec sync-back` | `harness spec sync-hub` |
| `bug approve` | `harness bug ready` (ou `bug plan --ready`) |
