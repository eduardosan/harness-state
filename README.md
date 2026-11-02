# harness-state

Cliente e CLI oficial de State Tracking para a esteira de desenvolvimento
guiado por especificações (SDD federada).

Permite sincronizar o progresso de especificações (`SPEC-ID`), tarefas
multi-repositório e o ciclo de execução em um barramento de estado
compatível com Redis. Licença: [AGPL-3.0](./LICENSE).

## Fluxo (sem dependência de infraestrutura específica)

Consulte [`docs/flow.md`](./docs/flow.md) para o fluxo completo analogizado:
**plan → status → update → resume** sobre ondas topológicas de sub-tarefas.

## Instalação

```bash
uv tool install git+https://github.com/eduardosan/harness-state.git
```

Ou clone e instale localmente:

```bash
make install-local   # instala no .venv do projeto
make install-global  # instala via uv tool no PATH do usuário
```

## Conexão ao barramento de estado

Qualquer serviço compatível com Redis serve. Configure por variáveis de
ambiente:

```bash
export HARNESS_REDIS_HOST="127.0.0.1"
export HARNESS_REDIS_PORT="6379"
export HARNESS_REDIS_DB="0"
# opcional:
export HARNESS_REDIS_PASSWORD="..."
```

Se o barramento ficar atrás de uma rede privada, um túnel SSH padrão
resolve. O Makefile traz um exemplo genérico e parametrizável (`make
tunnel`), com overrides via `local.mk` (ignorado pelo git).

## Comandos Principais

```bash
# Gravar ou atualizar uma nova spec e suas sub-tarefas
harness-state plan --spec specs/SPEC-042.md

# Visualizar o status consolidado de uma spec
harness-state status SPEC-042

# Retomar o trabalho no ambiente atual (checkout da branch pendente)
harness-state resume SPEC-042
```

## Desenvolvimento

```bash
uv sync              # sincroniza dependências
uv run pytest        # suíte de testes
uv run pyright       # checagem de tipos
uv run ruff check .  # linter
uv run isort --check-only .
```

Regiões do projeto (regras de arquitetura e python fluente) em
[`AGENTS.md`](./AGENTS.md).
