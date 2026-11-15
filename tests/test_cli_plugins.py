"""Testes do plugin registry e da CLI pública `harness` (SPEC-006 Onda 2)."""

from typing import Any

import click
import pytest

import harness_state.cli as cli_module
from harness_state.cli import main


def test_core_public_commands_present(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Business Rule: a CLI pública expõe init/status/update/plan/resume/get-spec."""
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "get-spec" in result.output
    assert "status" in result.output


def test_load_plugins_registers_commands(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Business Rule: plugins via entry points `harness.plugins` acrescentam comandos ao grupo."""

    def register_plugin(group: click.Group) -> None:
        group.add_command(
            click.Command("bug-suite", help="Comandos privados do flywheel")
        )

    fake_ep: Any = type("EP", (), {"name": "flywheel", "load": lambda self: register_plugin})()
    monkeypatch.setattr(cli_module, "list_available_plugins", lambda: [fake_ep])

    fresh = click.Group("main")
    cli_module.load_plugins_into(fresh)

    assert "bug-suite" in fresh.commands


def test_load_plugins_collisions_are_not_overridden(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Business Rule: plugin tentando sobrescrever comando público é rejeitado com aviso (stderr), sem traceback."""

    def register_evil(group: click.Group) -> None:
        group.add_command(click.Command("status", help="sobrescreve"))

    fake_ep: Any = type(
        "EP", (), {"name": "evil", "load": lambda self: register_evil}
    )()
    monkeypatch.setattr(cli_module, "list_available_plugins", lambda: [fake_ep])

    group = click.Group("main")
    original = click.Command("status", help="público")
    group.add_command(original)

    cli_module.load_plugins_into(group)

    assert group.commands["status"] is original
    captured = capsys.readouterr()
    assert "status" in (captured.err + captured.out)


def test_load_plugins_tolerates_broken_plugin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Business Rule: plugin quebrado faz WARN no stderr e o resto carrega (sem traceback)."""

    def broken(group: click.Group) -> None:
        raise RuntimeError("plugado errado")

    fake_ep: Any = type("EP", (), {"name": "broken", "load": lambda self: broken})()
    ok_ep: Any = type(
        "EP2",
        (),
        {"name": "ok", "load": lambda self: lambda g: g.add_command(click.Command("ok-cmd"))},
    )()
    monkeypatch.setattr(cli_module, "list_available_plugins", lambda: [fake_ep, ok_ep])

    fresh = click.Group("main")
    cli_module.load_plugins_into(fresh)

    assert "ok-cmd" in fresh.commands
    captured = capsys.readouterr()
    assert "broken" in (captured.err + captured.out)


def montar_plugin_setup_na_cli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Registra um plugin fake com o comando `setup` e reabre a montagem de plugins.

    Args:
        monkeypatch: Fixture do pytest para patchar a descoberta de entry points.
    """

    def register_setup(group: click.Group) -> None:
        group.add_command(click.Command("setup", help="inicializa config"))

    fake_ep: Any = type(
        "EP", (), {"name": "flywheel", "load": lambda self: register_setup}
    )()
    monkeypatch.setattr(cli_module, "list_available_plugins", lambda: [fake_ep])
    monkeypatch.setattr(main, "plugins_mounted", False, raising=False)


def test_binario_harness_resolve_comando_de_plugin_no_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business Rule: no binário real, um comando de plugin é resolvido no dispatch.

    Reproduz a falha de produção do flywheel em CI: `harness setup --ci` retornava
    "No such command 'setup'" porque os plugins nunca eram montados no grupo
    público — o chamador não pode precisar invocar `load_plugins_into` manualmente.
    """
    from click.testing import CliRunner

    montar_plugin_setup_na_cli(monkeypatch)

    result = CliRunner().invoke(main, ["setup"])
    assert "No such command" not in result.output
    assert result.exit_code != 2


def test_binario_harness_lista_comandos_de_plugin_na_ajuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Business Rule: `harness --help` expõe os comandos aportados por plugins."""
    from click.testing import CliRunner

    montar_plugin_setup_na_cli(monkeypatch)

    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "setup" in result.output
