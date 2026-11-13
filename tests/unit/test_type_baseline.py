"""Testes da ferramenta de baseline do pyright (decisao 5 do plano)."""

import json
from pathlib import Path

import pytest

from harness_state.sensors.type_baseline import (
    Diagnostic,
    compare,
    load_baseline,
    main,
    parse_report,
    save_baseline,
    shrink,
)

ROOT = Path("/repo")


def make_item(
    file: str = "/repo/src/app.py",
    line: int = 9,
    rule: str = "reportGeneralTypeIssues",
    message: str = "Type mismatch",
    severity: str = "error",
) -> dict[str, object]:
    """Monta um diagnostico no formato do ``pyright --outputjson``.

    Args:
        file: Caminho absoluto do arquivo.
        line: Linha base zero, como emitida pelo pyright.
        rule: Regra do pyright.
        message: Mensagem do diagnostico.
        severity: Severidade (``error``, ``warning`` ou ``information``).

    Returns:
        Dicionario de um item de ``generalDiagnostics``.
    """
    return {
        "file": file,
        "severity": severity,
        "message": message,
        "rule": rule,
        "range": {
            "start": {"line": line, "character": 4},
            "end": {"line": line, "character": 10},
        },
    }


def make_report(*items: dict[str, object]) -> str:
    """Serializa itens como um relatorio completo do pyright.

    Args:
        *items: Diagnosticos criados por ``make_item``.

    Returns:
        Texto JSON do relatorio.
    """
    return json.dumps({"generalDiagnostics": list(items)})


def test_parse_keeps_only_errors_with_relative_path_and_one_based_line() -> None:
    """Business Rule: so erros entram no baseline, nao avisos.

    Caminhos ficam relativos a raiz e linhas passam a ser base 1.
    """
    report = make_report(
        make_item(line=9),
        make_item(severity="warning"),
        make_item(severity="information"),
    )

    diagnostics = parse_report(report, ROOT)

    assert diagnostics == [
        Diagnostic(
            file="src/app.py",
            line=10,
            column=5,
            rule="reportGeneralTypeIssues",
            message="Type mismatch",
        )
    ]


def test_parse_report_without_diagnostics_is_empty() -> None:
    """Business Rule: relatorio sem a chave de diagnosticos nao tem erros."""
    assert parse_report(json.dumps({"summary": {}}), ROOT) == []


def test_moved_error_is_not_new() -> None:
    """Business Rule: o baseline nao depende do numero da linha.

    Editar codigo acima de um erro ja conhecido nao pode quebrar o gate.
    """
    baseline = parse_report(make_report(make_item(line=9)), ROOT)
    current = parse_report(make_report(make_item(line=40)), ROOT)

    result = compare(current, baseline)

    assert result.new == []


def test_new_error_is_reported() -> None:
    """Business Rule: erro fora do baseline bloqueia o gate."""
    baseline = parse_report(make_report(make_item(message="Old")), ROOT)
    current = parse_report(
        make_report(make_item(message="Old"), make_item(message="Brand new")), ROOT
    )

    result = compare(current, baseline)

    assert [item.message for item in result.new] == ["Brand new"]


def test_extra_occurrence_of_known_error_is_new() -> None:
    """Business Rule: repetir um erro conhecido alem do baseline e regressao.

    O baseline conta ocorrencias; uma terceira ocorrencia de um erro registrado
    duas vezes e nova.
    """
    baseline = parse_report(make_report(make_item(line=1), make_item(line=2)), ROOT)
    current = parse_report(
        make_report(make_item(line=1), make_item(line=2), make_item(line=3)), ROOT
    )

    result = compare(current, baseline)

    assert len(result.new) == 1
    assert result.fixed == 0


def test_fixed_error_does_not_fail_and_is_counted() -> None:
    """Business Rule: corrigir um erro do baseline e permitido."""
    item_a = make_item(message="A")
    item_b = make_item(message="B")
    baseline = parse_report(make_report(item_a, item_b), ROOT)
    current = parse_report(make_report(item_a), ROOT)

    result = compare(current, baseline)

    assert result.new == []
    assert result.fixed == 1


def test_baseline_round_trip_is_deterministic(tmp_path: Path) -> None:
    """Business Rule: o arquivo de baseline e estavel e versionavel.

    A ordem de entrada nao altera o conteudo, para diffs limpos no Git.
    """
    first = parse_report(
        make_report(make_item(message="B"), make_item(message="A")), ROOT
    )
    second = parse_report(
        make_report(make_item(message="A"), make_item(message="B")), ROOT
    )
    path_one = tmp_path / "one.json"
    path_two = tmp_path / "two.json"

    save_baseline(path_one, first)
    save_baseline(path_two, second)

    assert path_one.read_text(encoding="utf-8") == path_two.read_text(encoding="utf-8")
    loaded = load_baseline(path_one)
    assert compare(first, loaded).new == []
    assert compare(first, loaded).fixed == 0


def test_load_missing_baseline_is_empty(tmp_path: Path) -> None:
    """Business Rule: repositorio novo nasce com baseline vazio (strict pleno)."""
    assert load_baseline(tmp_path / "absent.json") == []


def test_shrink_removes_fixed_and_never_adds_new() -> None:
    """Business Rule: o baseline so pode encolher.

    Erros corrigidos saem; erros novos nunca entram por essa via.
    """
    item_a = make_item(message="A")
    baseline = parse_report(make_report(item_a, make_item(message="B")), ROOT)
    current = parse_report(make_report(item_a, make_item(message="C")), ROOT)

    shrunk = shrink(baseline, current)

    assert [item.message for item in shrunk] == ["A"]


def write_report(tmp_path: Path, *items: dict[str, object]) -> Path:
    """Grava um relatorio do pyright em disco.

    Args:
        tmp_path: Diretorio temporario do teste.
        *items: Diagnosticos criados por ``make_item``.

    Returns:
        Caminho do arquivo de relatorio.
    """
    path = tmp_path / "report.json"
    path.write_text(make_report(*items), encoding="utf-8")
    return path


def test_cli_generate_creates_baseline(tmp_path: Path) -> None:
    """Business Rule: a adocao inicial grava os erros atuais como baseline."""
    report = write_report(tmp_path, make_item())
    baseline = tmp_path / "baseline.json"

    code = main(
        [
            "generate",
            "--report",
            str(report),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )

    assert code == 0
    assert baseline.is_file()


def test_cli_generate_refuses_to_overwrite_existing_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: gerar de novo poderia aumentar o baseline, entao e vetado.

    Com baseline existente o caminho correto e o comando `shrink`.
    """
    report = write_report(tmp_path, make_item())
    baseline = tmp_path / "baseline.json"
    baseline.write_text("[]", encoding="utf-8")

    code = main(
        [
            "generate",
            "--report",
            str(report),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )

    assert code == 2
    assert "shrink" in capsys.readouterr().out
    assert baseline.read_text(encoding="utf-8") == "[]"


def test_cli_check_passes_when_nothing_is_new(tmp_path: Path) -> None:
    """Business Rule: sem regressao o gate de tipos passa em silencio."""
    report = write_report(tmp_path, make_item())
    baseline = tmp_path / "baseline.json"
    main(
        [
            "generate",
            "--report",
            str(report),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )

    code = main(
        [
            "check",
            "--report",
            str(report),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )

    assert code == 0


def test_cli_check_prints_new_errors_in_pyright_format(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: regressao e devolvida no formato que o sensor entende.

    O format_feedback.sh reconhece `arquivo:linha:coluna - error: mensagem`.
    """
    baseline = tmp_path / "baseline.json"
    save_baseline(baseline, [])
    report = write_report(tmp_path, make_item(line=9, message="Brand new"))

    code = main(
        [
            "check",
            "--report",
            str(report),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )

    output = capsys.readouterr().out
    assert code == 1
    assert "src/app.py:10:5 - error: Brand new" in output


def test_cli_check_without_baseline_treats_every_error_as_new(tmp_path: Path) -> None:
    """Business Rule: sem baseline o repositorio e validado em strict pleno."""
    report = write_report(tmp_path, make_item())

    code = main(
        [
            "check",
            "--report",
            str(report),
            "--baseline",
            str(tmp_path / "none.json"),
            "--root",
            "/repo",
        ]
    )

    assert code == 1


def test_cli_shrink_rewrites_baseline_without_fixed_errors(tmp_path: Path) -> None:
    """Business Rule: apos corrigir erros o baseline e encolhido, nunca ampliado."""
    both = write_report(tmp_path, make_item(message="A"), make_item(message="B"))
    baseline = tmp_path / "baseline.json"
    main(
        [
            "generate",
            "--report",
            str(both),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )
    only_a = write_report(tmp_path, make_item(message="A"), make_item(message="Z"))

    code = main(
        [
            "shrink",
            "--report",
            str(only_a),
            "--baseline",
            str(baseline),
            "--root",
            "/repo",
        ]
    )

    assert code == 0
    remaining = load_baseline(baseline)
    assert [item.message for item in remaining] == ["A"]