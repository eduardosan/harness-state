# harness-state

Núcleo open-source de **State Tracking**, **Orquestração de Agentes**, **Gates de Qualidade** e **Ciclo de Vida SDD** (Spec-Driven Development) federado.

Distribuído sob a licença [GNU Affero General Public License v3 (AGPL-3.0)](./LICENSE).

---

## Recursos e Módulos Canônicos

O `harness-state` encapsula toda a inteligência e infraestrutura do ecossistema de desenvolvimento orientado por especificações:

- **State Tracking e Ciclo de Vida SDD**: Gerenciamento de especificações decompostas em sub-tarefas com cálculo topológico de dependências e ondas de execução (`harness_state.models`, `harness_state.client`, `harness_state.spec_lifecycle`).
- **Fan-Out Federado**: Despacho de subtarefas para múltiplos repositórios spoke através de Pull Requests e Issues no GitHub (`harness_state.spec_fanout`, `harness_state.git_ops`).
- **Gates e LLM-as-a-Judge**: Avaliação automática de conformidade arquitetural, semântica e contratos de runtime (`harness_state.gate`, `harness_state.judge`, `harness_state.contracts`).
- **Ciclo de Vida de Bugs com SDD**: Elicitação de planos de correção com LLMs, reprodução hermética via TDD, diagnóstico RCA e promoção atômica de prompts para o Langfuse SSOT (`harness_state.bug`, `harness_state.prompt_manager`, `harness_state.prompt_promotion`).
- **Sensores e Baseline de Qualidade**: Auditoria de AST, complexidade cognitiva (complexipy), conformidade de configuração 12-factor, baseline de tipagem estática pyright e governança de prompts (`harness_state.sensors`).
- **Auditoria e Segurança contra Vazamento**: Validação automatizada `mask-sensitive-data` garantindo que nenhuma credencial ou IP privado vaze em documentações públicas (§7 da SPEC-009).
- **Instalador e Corte de Release**: Instalação e injeção de templates de harness em repositórios spoke e cálculo semântico automatizado de releases (`harness_state.installer`, `harness_state.release`).

---

## Instalação

O binário disponibilizado é o **`harness`** (o pacote Python é `harness-state`):

```bash
# Instalação global via uv tool
uv tool install --force git+https://github.com/eduardosan/harness-state.git

# Ou via pip
pip install git+https://github.com/eduardosan/harness-state.git
```

---

## Comandos Principais da CLI `harness`

```bash
# 1. Planejar e registrar uma nova spec no barramento de estado
harness plan --spec specs/SPEC-042.md

# 2. Consultar o status consolidado de uma especificação
harness status SPEC-042

# 3. Atualizar o estado de uma subtarefa (com worker e PR associado)
harness update SPEC-042 task-1 IN_PROGRESS --worker local-agent --pr 123

# 4. Retomar o trabalho no ambiente local (checkout da branch pendente)
harness resume SPEC-042

# 5. Instalar o harness e suas skills em um repositório spoke
harness install --path ./meu-projeto

# 6. Calcular a próxima tag SemVer a partir do histórico e PRs
harness release --strategy minor

# 7. Auditar o repositório contra vazamento de IPs ou tokens sensíveis
harness audit --mask-sensitive-data
```

---

## Configuração e 12-Factor

O `harness-state` é agnóstico à infraestrutura física. A parametrização é realizada por variáveis de ambiente ou arquivo local gitignored (`~/.config/harness/config.yaml`):

```bash
export HARNESS_REDIS_HOST="127.0.0.1"
export HARNESS_REDIS_PORT="6379"
export ES_URL="http://127.0.0.1:9200"
export ES_INDEX="harness-sensor-telemetry"
export SPEC_HUB_REPO="org/spec-hub"
```

---

## Desenvolvimento e Testes

Consulte o arquivo [`CONTRIBUTING.md`](./CONTRIBUTING.md) para diretrizes detalhadas de contribuição e convenções de estilo.

```bash
uv sync              # sincroniza dependências
just verify          # executa pyright (0 erros em modo strict), ruff, isort e testes
```

---

## Licença

Este projeto é software livre sob a licença [GNU Affero General Public License v3 (AGPL-3.0)](./LICENSE).
