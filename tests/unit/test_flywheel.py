"""Testes do gerenciador do Flywheel Execution Engine (SPEC-009 Onda 1)."""

from pathlib import Path

import pytest

from harness_state.flywheel import (
    check_flywheel_status,
    ensure_dir,
    init_flywheel,
    load_flywheel_config,
    run_command,
    write_file,
)

EXPECTED_WORKFLOWS = (
    Path(".github") / "workflows" / "agent.yml",
    Path(".github") / "workflows" / "spec-dispatch.yml",
    Path(".github") / "workflows" / "capabilities-sync.yml",
)


def test_init_flywheel_cria_estrutura_completa(tmp_path: Path) -> None:
    """Business Rule: `harness flywheel init` gera o esqueleto operacional do engine.

    Um flywheel novo deve nascer com pyproject (dependências harness-state e
    agentic-flywheel), config.yaml, módulos delegadores (agents.py, catalog/,
    sensors/), os três workflows de CI e README.
    """
    target = tmp_path / "meu-flywheel"
    init_flywheel(target)

    pyproject = (target / "pyproject.toml").read_text(encoding="utf-8")
    assert "harness-state" in pyproject
    assert "agentic-flywheel" in pyproject
    assert "meu-flywheel" in pyproject

    config = (target / "config.yaml").read_text(encoding="utf-8")
    assert "flywheels:" in config

    assert (target / "agents.py").is_file()
    assert (target / "catalog" / "__init__.py").is_file()
    assert (target / "sensors" / "__init__.py").is_file()
    for workflow in EXPECTED_WORKFLOWS:
        assert (target / workflow).is_file(), workflow
    assert (target / "README.md").is_file()


def test_init_flywheel_recusa_diretorio_nao_vazio(tmp_path: Path) -> None:
    """Business Rule: init nunca sobrescreve trabalho existente — aborta se não vazio.

    Silenciar arquivos pré-existentes mascararia colisão com um flywheel ou
    repositório já inicializado no caminho.
    """
    target = tmp_path / "sujo"
    target.mkdir()
    (target / "qualquer-arquivo.txt").write_text("conteúdo", encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        init_flywheel(target)
    assert excinfo.value.code == 1


def test_load_flywheel_config_sem_arquivo_retorna_vazio(tmp_path: Path) -> None:
    """Business Rule: ausência de config.yaml significa 'nenhum flywheel', sem erro."""
    assert load_flywheel_config(tmp_path / "config.yaml") == []


def test_load_flywheel_config_ignora_yaml_invalido(tmp_path: Path) -> None:
    """Business Rule: manifest corrompido degrada para lista vazia (não derruba CLI).

    O update-loop roda em cron de CI; um YAML quebrado deve ser reportado
    como 'nada a fazer', não como stack trace do pipeline.
    """
    broken = tmp_path / "config.yaml"
    broken.write_text("flywheels: [ name: quebrado", encoding="utf-8")
    assert load_flywheel_config(broken) == []


def test_load_flywheel_config_extrai_lista_de_flywheels(tmp_path: Path) -> None:
    """Business Rule: a chave `flywheels` do config.yaml é a fonte da listagem."""
    good = tmp_path / "config.yaml"
    good.write_text(
        "flywheels:\n"
        "  - name: support-engine\n"
        "    path: /srv/support\n"
        "    repo: eduardosan/support-engine\n",
        encoding="utf-8",
    )
    entries = load_flywheel_config(good)
    assert len(entries) == 1
    assert entries[0]["name"] == "support-engine"
    assert load_flywheel_config(good.parent / "outro.yaml") == []


def test_check_flywheel_status_exige_diretorio_existente(tmp_path: Path) -> None:
    """Business Rule: status em caminho inexistente aborta com exit code 1."""
    with pytest.raises(SystemExit) as excinfo:
        check_flywheel_status(tmp_path / "nao-existe")
    assert excinfo.value.code == 1


def test_check_flywheel_status_exige_pyproject(tmp_path: Path) -> None:
    """Business Rule: sem pyproject.toml o diretório não é um flywheel válido."""
    (tmp_path / "README.md").write_text("# não é flywheel", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        check_flywheel_status(tmp_path)
    assert excinfo.value.code == 1


def test_check_flywheel_status_aceita_flywheel_inicializado(
    tmp_path: Path,
) -> None:
    """Business Rule: o health check de um flywheel recém-criado conclui sem erro.

    O status valida pyproject.toml e os imports delegados
    (harness_state.catalog/sensors/agents); um init válido deve passar
    integralmente — é o contrato end-to-end init -> status.
    """
    target = tmp_path / "flywheel-ok"
    init_flywheel(target)
    check_flywheel_status(target)


def test_run_command_injeta_env_preservando_ambiente() -> None:
    """Business Rule: run_command mescla env customizado sobre os.environ.

    Os runners de CI dependem de segredos passados via env sem perder as
    variáveis padrão do processo (PATH etc.).
    """
    result = run_command(
        ["python3", "-c", "import os; print(os.environ['HARNESS_TEST_VAR'])"],
        env={"HARNESS_TEST_VAR": "ok"},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "ok"
    path_probe = run_command(
        ["python3", "-c", "import os; print(len(os.environ['PATH']))"]
    )
    assert path_probe.returncode == 0
    assert path_probe.stdout.strip().isdigit()


def test_ensure_dir_e_write_file_sao_idempotentes(tmp_path: Path) -> None:
    """Business Rule: helpers de filesystem não falham em reexecução.

    `ensure_dir` sobre diretório existente e `write_file` sobre arquivo
    existente devem apenas (re)garantir conteúdo, criando parents quando
    necessário.
    """
    nested = tmp_path / "a" / "b" / "c"
    ensure_dir(nested)
    ensure_dir(nested)
    assert nested.is_dir()

    arquivo = nested / "arquivo.txt"
    write_file(arquivo, "conteúdo")
    write_file(arquivo, "novo conteúdo")
    assert arquivo.read_text(encoding="utf-8") == "novo conteúdo"
