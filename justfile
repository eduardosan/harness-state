# justfile - Interface canonica do harness para o repositorio harness-state
default:
    @just --list

# Checagem de tipagem estatica
check:
    uv run pyright src tests

# Checagem de estilo e ordenacao de imports
lint:
    uv run ruff check src tests
    uv run isort --check-only src tests

# Suite de testes unitarios
test:
    uv run pytest tests

# Validacao completa hermetica antes de PRs (mesmo contrato do flywheel)
verify: check lint test
