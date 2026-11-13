"""Baseline de erros do pyright para adoção gradual do modo ``strict``.

O ``pyright`` não possui baseline nativo. Este módulo compara o relatório de
``pyright --outputjson`` com um arquivo versionado no repositório:

* só erros novos bloqueiam o gate (``check``);
* o baseline só pode encolher (``shrink``);
* a geração inicial (``generate``) recusa sobrescrever um baseline existente,
  porque isso poderia ampliar a dívida silenciosamente.

O baseline guarda arquivo, regra e mensagem com contagem de ocorrências, sem o
número da linha, para que edições triviais não quebrem a comparação.
"""

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path

DiagnosticKey = tuple[str, str, str]

DEFAULT_BASELINE_PATH = Path("pyright-baseline.json")


@dataclass(frozen=True)
class Diagnostic:
    """Erro de tipo reportado pelo pyright.

    Attributes:
        file: Caminho do arquivo, relativo à raiz do repositório.
        line: Linha do erro, a partir de 1 (0 quando vindo do baseline).
        column: Coluna do erro, a partir de 1 (0 quando vindo do baseline).
        rule: Regra do pyright (ex: ``reportGeneralTypeIssues``).
        message: Mensagem do diagnóstico.
    """

    file: str
    line: int
    column: int
    rule: str
    message: str

    @property
    def key(self) -> DiagnosticKey:
        """Identidade do erro no baseline, independente da posição.

        Returns:
            Tupla ``(arquivo, regra, mensagem)``.
        """
        return (self.file, self.rule, self.message)


@dataclass(frozen=True)
class Comparison:
    """Resultado da comparação entre o relatório atual e o baseline.

    Attributes:
        new: Erros além do que o baseline permite.
        fixed: Quantidade de erros do baseline que não ocorrem mais.
    """

    new: list[Diagnostic]
    fixed: int


def relative_path(file: str, root: Path) -> str:
    """Converte um caminho para relativo à raiz, quando possível."""
    path = Path(file)
    if path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    return path.as_posix()


def parse_report(report: str, root: Path) -> list[Diagnostic]:
    """Extrai os erros de um relatório ``pyright --outputjson``.

    Args:
        report: Texto JSON do relatório.
        root: Raiz do repositório, usada para relativizar caminhos.

    Returns:
        Apenas diagnósticos de severidade ``error``, com linhas base 1.
    """
    data = json.loads(report)
    diagnostics: list[Diagnostic] = []
    for item in data.get("generalDiagnostics", []):
        if item.get("severity") != "error":
            continue
        start = item.get("range", {}).get("start", {})
        diagnostics.append(
            Diagnostic(
                file=relative_path(item.get("file", ""), root),
                line=start.get("line", 0) + 1,
                column=start.get("character", 0) + 1,
                rule=item.get("rule", ""),
                message=item.get("message", ""),
            )
        )
    return diagnostics


def expand(counts: Counter[DiagnosticKey]) -> list[Diagnostic]:
    """Converte contagens do baseline em diagnósticos sem posição."""
    result: list[Diagnostic] = []
    for (file, rule, message), count in sorted(counts.items()):
        result.extend([Diagnostic(file, 0, 0, rule, message)] * count)
    return result


def save_baseline(path: Path, diagnostics: Sequence[Diagnostic]) -> None:
    """Grava o baseline de forma determinística.

    Args:
        path: Arquivo de baseline.
        diagnostics: Erros a registrar.
    """
    counts = Counter(item.key for item in diagnostics)
    entries = [
        {"file": file, "rule": rule, "message": message, "count": count}
        for (file, rule, message), count in sorted(counts.items())
    ]
    text = json.dumps(entries, indent=2, ensure_ascii=False)
    path.write_text(text + "\n", encoding="utf-8")


def load_baseline(path: Path) -> list[Diagnostic]:
    """Lê o baseline; arquivo ausente equivale a baseline vazio."""
    if not path.is_file():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))
    counts: Counter[DiagnosticKey] = Counter()
    for entry in entries:
        key = (entry["file"], entry["rule"], entry["message"])
        counts[key] += entry.get("count", 1)
    return expand(counts)


def compare(
    current: Sequence[Diagnostic], baseline: Sequence[Diagnostic]
) -> Comparison:
    """Separa erros novos dos já conhecidos e conta os corrigidos."""
    budget = Counter(item.key for item in baseline)
    new: list[Diagnostic] = []
    for item in sorted(current, key=attrgetter("file", "line", "column")):
        if budget[item.key] > 0:
            budget[item.key] -= 1
        else:
            new.append(item)
    diff = Counter(i.key for i in baseline) - Counter(i.key for i in current)
    fixed = sum(diff.values())
    return Comparison(new=new, fixed=fixed)


def shrink(
    baseline: Sequence[Diagnostic], current: Sequence[Diagnostic]
) -> list[Diagnostic]:
    """Remove do baseline os erros corrigidos, sem nunca adicionar novos."""
    remaining = Counter(i.key for i in baseline) & Counter(i.key for i in current)
    return expand(remaining)


def build_parser() -> argparse.ArgumentParser:
    """Cria o parser de linha de comando."""
    parser = argparse.ArgumentParser(description="Baseline de erros do pyright.")
    parser.add_argument("command", choices=["generate", "check", "shrink"])
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def format_diagnostic(item: Diagnostic) -> str:
    """Formata um erro como o pyright, para o ``format_feedback.sh``."""
    location = f"{item.file}:{item.line}:{item.column}"
    return f"{location} - error: {item.message} ({item.rule})"


def main(argv: Sequence[str] | None = None) -> int:
    """Executa um subcomando do baseline."""
    args = build_parser().parse_args(argv)
    current = parse_report(args.report.read_text(encoding="utf-8"), args.root)
    baseline = load_baseline(args.baseline)

    if args.command == "generate":
        if args.baseline.exists():
            print(
                f"Baseline {args.baseline} already exists. "
                "Use 'shrink' to remove fixed errors; it can never grow."
            )
            return 2
        save_baseline(args.baseline, current)
        return 0

    if args.command == "shrink":
        save_baseline(args.baseline, shrink(baseline, current))
        return 0

    result = compare(current, baseline)
    for item in result.new:
        print(format_diagnostic(item))
    return 1 if result.new else 0


if __name__ == "__main__":
    raise SystemExit(main())


TypeBaselineViolation = Diagnostic