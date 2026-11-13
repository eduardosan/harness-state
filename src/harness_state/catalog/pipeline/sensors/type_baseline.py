"""Baseline de erros do pyright para adocao gradual do modo ``strict``.

O ``pyright`` nao possui baseline nativo. Este modulo compara o relatorio de
``pyright --outputjson`` com um arquivo versionado no repositorio:

* so erros novos bloqueiam o gate (``check``);
* o baseline so pode encolher (``shrink``);
* a geracao inicial (``generate``) recusa sobrescrever um baseline existente,
  porque isso poderia ampliar a divida silenciosamente.

O baseline guarda arquivo, regra e mensagem com contagem de ocorrencias, sem o
numero da linha, para que edicoes triviais nao quebrem a comparacao.
"""

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path

DiagnosticKey = tuple[str, str, str]


@dataclass(frozen=True)
class Diagnostic:
    """Erro de tipo reportado pelo pyright.

    Attributes:
        file: Caminho do arquivo, relativo a raiz do repositorio.
        line: Linha do erro, a partir de 1 (0 quando vindo do baseline).
        column: Coluna do erro, a partir de 1 (0 quando vindo do baseline).
        rule: Regra do pyright (ex: ``reportGeneralTypeIssues``).
        message: Mensagem do diagnostico.
    """

    file: str
    line: int
    column: int
    rule: str
    message: str

    @property
    def key(self) -> DiagnosticKey:
        """Identidade do erro no baseline, independente da posicao.

        Returns:
            Tupla ``(arquivo, regra, mensagem)``.
        """
        return (self.file, self.rule, self.message)


@dataclass(frozen=True)
class Comparison:
    """Resultado da comparacao entre o relatorio atual e o baseline.

    Attributes:
        new: Erros alem do que o baseline permite.
        fixed: Quantidade de erros do baseline que nao ocorrem mais.
    """

    new: list[Diagnostic]
    fixed: int


def relative_path(file: str, root: Path) -> str:
    """Converte um caminho para relativo a raiz, quando possivel.

    Args:
        file: Caminho emitido pelo pyright.
        root: Raiz do repositorio.

    Returns:
        Caminho relativo em formato POSIX, ou o original se estiver fora da raiz.
    """
    path = Path(file)
    if path.is_relative_to(root):
        return path.relative_to(root).as_posix()
    return path.as_posix()


def parse_report(report: str, root: Path) -> list[Diagnostic]:
    """Extrai os erros de um relatorio ``pyright --outputjson``.

    Args:
        report: Texto JSON do relatorio.
        root: Raiz do repositorio, usada para relativizar caminhos.

    Returns:
        Apenas diagnosticos de severidade ``error``, com linhas base 1.
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
    """Converte contagens do baseline em diagnosticos sem posicao.

    Args:
        counts: Ocorrencias por chave de diagnostico.

    Returns:
        Diagnosticos repetidos conforme a contagem, em ordem deterministica.
    """
    result: list[Diagnostic] = []
    for (file, rule, message), count in sorted(counts.items()):
        result.extend([Diagnostic(file, 0, 0, rule, message)] * count)
    return result


def save_baseline(path: Path, diagnostics: Sequence[Diagnostic]) -> None:
    """Grava o baseline de forma deterministica.

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
    """Le o baseline; arquivo ausente equivale a baseline vazio.

    Args:
        path: Arquivo de baseline.

    Returns:
        Diagnosticos sem posicao, repetidos conforme a contagem registrada.
    """
    if not path.is_file():
        return []
    entries = json.loads(path.read_text(encoding="utf-8"))
    counts: Counter[DiagnosticKey] = Counter()
    for entry in entries:
        key = (entry["file"], entry["rule"], entry["message"])
        counts[key] += entry["count"]
    return expand(counts)


def compare(
    current: Sequence[Diagnostic], baseline: Sequence[Diagnostic]
) -> Comparison:
    """Separa erros novos dos ja conhecidos e conta os corrigidos.

    Para cada erro repetido alem do que o baseline permite, as ocorrencias
    nas ultimas linhas sao consideradas novas.

    Args:
        current: Erros do relatorio atual.
        baseline: Erros registrados no baseline.

    Returns:
        Comparacao com os erros novos e a quantidade corrigida.
    """
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
    """Remove do baseline os erros corrigidos, sem nunca adicionar novos.

    Args:
        baseline: Erros registrados no baseline.
        current: Erros do relatorio atual.

    Returns:
        Interseccao entre o baseline e o relatorio atual.
    """
    remaining = Counter(i.key for i in baseline) & Counter(i.key for i in current)
    return expand(remaining)


def build_parser() -> argparse.ArgumentParser:
    """Cria o parser de linha de comando.

    Returns:
        Parser com os subcomandos ``generate``, ``check`` e ``shrink``.
    """
    parser = argparse.ArgumentParser(description="Baseline de erros do pyright.")
    parser.add_argument("command", choices=["generate", "check", "shrink"])
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    return parser


def format_diagnostic(item: Diagnostic) -> str:
    """Formata um erro como o pyright, para o ``format_feedback.sh``.

    Args:
        item: Erro a formatar.

    Returns:
        Linha ``arquivo:linha:coluna - error: mensagem (regra)``.
    """
    location = f"{item.file}:{item.line}:{item.column}"
    return f"{location} - error: {item.message} ({item.rule})"


def main(argv: Sequence[str] | None = None) -> int:
    """Executa um subcomando do baseline.

    Args:
        argv: Argumentos de linha de comando. Usa ``sys.argv`` se omitido.

    Returns:
        0 em sucesso, 1 quando ha erros novos e 2 em uso incorreto.
    """
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
