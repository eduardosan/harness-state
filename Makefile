# Makefile para harness-state
#
# Parâmetros de rede são genéricos; para o seu ambiente, defina-os em um
# arquivo `local.mk` (ignorado pelo git) com atribuições `=`, ex.:
#   REDIS_HOST = 10.0.0.5
#   SSH_USER   = seu-usuario
#   SSH_HOST   = seu-jump-host
#   SSH_PORT   = 22

.PHONY: tunnel tunnel-check tunnel-stop install install-global install-local test lint sync help

REDIS_HOST ?= 127.0.0.1
REDIS_PORT ?= 6379
SSH_USER ?=
SSH_HOST ?=
SSH_PORT ?= 22

-include local.mk

help:
	@echo "Comandos disponíveis:"
	@echo "  make tunnel         - Inicia o túnel SSH para o Redis em background"
	@echo "  make tunnel-check   - Verifica se o túnel SSH está ativo"
	@echo "  make tunnel-stop    - Encerra o túnel SSH ativo"
	@echo "  make install-local  - Instala a CLI no ambiente virtual atual (pip install -e .)"
	@echo "  make install-global - Instala a CLI globalmente via uv tool (acessível no PATH do usuário)"
	@echo "  make test           - Executa os testes unitários via pytest"
	@echo "  make lint           - Executa checagem de estilo com ruff e isort"
	@echo "  make sync           - Sincroniza as dependências do projeto com uv"

# Sobe o túnel SSH em background (requer SSH_HOST configurado em local.mk)
tunnel:
	@if [ -z "$(SSH_HOST)" ] || [ -z "$(SSH_USER)" ]; then \
		echo "✗ Configure SSH_HOST e SSH_USER em local.mk antes de abrir o túnel."; \
		exit 1; \
	fi
	@if pgrep -f "ssh.*-L $(REDIS_PORT):$(REDIS_HOST):$(REDIS_PORT)" > /dev/null; then \
		echo "Túnel SSH já está ativo na porta $(REDIS_PORT)."; \
	else \
		echo "Iniciando túnel SSH para o Redis ($(REDIS_HOST):$(REDIS_PORT)) via $(SSH_HOST):$(SSH_PORT)..."; \
		ssh -p $(SSH_PORT) -N -f -L $(REDIS_PORT):$(REDIS_HOST):$(REDIS_PORT) $(SSH_USER)@$(SSH_HOST); \
		echo "Túnel SSH estabelecido com sucesso."; \
	fi

tunnel-check:
	@if pgrep -f "ssh.*-L $(REDIS_PORT):$(REDIS_HOST):$(REDIS_PORT)" > /dev/null; then \
		echo "✓ Túnel SSH está ATIVO."; \
	else \
		echo "✗ Túnel SSH NÃO está ativo."; \
	fi

tunnel-stop:
	@echo "Encerrando túnel SSH..."
	@pkill -f "ssh.*-L $(REDIS_PORT):$(REDIS_HOST):$(REDIS_PORT)" || true
	@echo "Túnel SSH encerrado."

# Instalação no ambiente local (venv)
install-local:
	uv pip install -e .

# Instalação global (uv tool) para disponibilizar o binário harness-state no PATH
install-global:
	uv tool install --force .

# Alias padrão
install: install-global

sync:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run isort --check-only .
