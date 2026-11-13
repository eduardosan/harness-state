"""Roteador estatico de especificacoes Python Fluente.

Classifica diffs e codigos modificados nos 5 grupos tematicos (A a E)
e nas 13 especificacoes canônicas (PY-01 a PY-13) atraves de padroes
lexicos e sintaticos sem invocar modelos de linguagem.
"""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RoutingResult:
    """Resultado do roteamento de um trecho de codigo ou diff.

    Attributes:
        groups: Conjunto de grupos tematicos ativados (A, B, C, D, E).
        specs: Conjunto de identificadores de specs ativadas (ex: PY-01, PY-05).
    """

    groups: set[str] = field(default_factory=set)
    specs: set[str] = field(default_factory=set)

    def to_dict(self) -> dict[str, list[str]]:
        """Converte o resultado em dicionario serializavel.

        Returns:
            Dicionario contendo listas ordenadas de grupos e specs.
        """
        return {
            "groups": sorted(self.groups),
            "specs": sorted(self.specs),
        }


SPEC_PATTERNS: dict[str, tuple[str, list[re.Pattern[str]]]] = {
    "PY-01": (
        "A",
        [
            re.compile(
                r"\b(__repr__|__str__|__len__|__getitem__|__contains__|"
                r"__bool__|__match_args__|__slots__)\b"
            ),
        ],
    ),
    "PY-02": (
        "A",
        [
            re.compile(r"\[\s*[^\]]+\s+for\s+[^\]]+\s+in\s+[^\]]+\]"),
            re.compile(r"\b(deque|sorted|list\.sort)\b"),
        ],
    ),
    "PY-03": (
        "A",
        [
            re.compile(r"\b(MappingProxyType|defaultdict|Counter|UserDict)\b"),
            re.compile(r"\.setdefault\("),
        ],
    ),
    "PY-04": (
        "D",
        [
            re.compile(r"\.(encode|decode)\("),
            re.compile(r"\bunicodedata\b"),
            re.compile(r"\b(bytes|bytearray)\b"),
        ],
    ),
    "PY-05": (
        "A",
        [
            re.compile(r"@dataclass\b"),
            re.compile(r"\bdataclass\("),
            re.compile(r"\b(NamedTuple|namedtuple)\b"),
        ],
    ),
    "PY-06": (
        "A",
        [
            re.compile(r"\bcopy\.(copy|deepcopy)\b"),
            re.compile(r"\bis\s+(None|not\s+None)\b"),
            re.compile(r"def\s+\w+\([^)]*=\s*(\[\]|\{\})"),
        ],
    ),
    "PY-07": (
        "B",
        [
            re.compile(r"@(functools\.)?(lru_cache|cache|wraps|singledispatch)"),
            re.compile(r"\b(functools|partial)\b"),
            re.compile(r"\blambda\b"),
        ],
    ),
    "PY-08": (
        "B",
        [
            re.compile(r"\b(TypeVar|Generic|overload|TypedDict|ParamSpec|AnyStr)\b"),
        ],
    ),
    "PY-09": (
        "C",
        [
            re.compile(r"\b(Protocol|runtime_checkable|ABC|abstractmethod)\b"),
            re.compile(r"\bsuper\(\)"),
        ],
    ),
    "PY-10": (
        "C",
        [
            re.compile(
                r"\b(__add__|__sub__|__mul__|__matmul__|__truediv__|"
                r"__eq__|__lt__|__gt__|__ne__|__le__|__ge__|NotImplemented)\b"
            ),
        ],
    ),
    "PY-11": (
        "D",
        [
            re.compile(r"\b(yield\s+from|yield)\b"),
            re.compile(r"\bcontextmanager\b"),
            re.compile(r"\bwith\s+"),
            re.compile(r"\b(match|case)\s+"),
        ],
    ),
    "PY-12": (
        "D",
        [
            re.compile(r"\basync\s+(def|with|for)\b"),
            re.compile(r"\b(asyncio|TaskGroup)\b"),
            re.compile(
                r"\b(concurrent\.futures|ThreadPoolExecutor|ProcessPoolExecutor)\b"
            ),
        ],
    ),
    "PY-13": (
        "E",
        [
            re.compile(r"@property\b"),
            re.compile(
                r"\b(__set_name__|__init_subclass__|__getattr__|"
                r"__getattribute__|__setattr__|metaclass=)\b"
            ),
        ],
    ),
}


def extract_added_lines(diff_text: str) -> str:
    """Extrai somente as linhas adicionadas ou modificadas de um git diff.

    Descarta cabecalhos de patch (ex: '+++ b/...') e linhas de contexto ou exclusao.

    Args:
        diff_text: Texto no formato unified diff.

    Returns:
        String consolidada contendo o conteudo das linhas adicionadas.
    """
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    return "\n".join(lines)


def route_code(source: str) -> RoutingResult:
    """Roteia codigo-fonte para grupos e especificacoes correspondentes.

    Args:
        source: Codigo Python ou linhas adicionadas de um diff.

    Returns:
        Instancia de RoutingResult com os grupos e specs ativados.
    """
    matched_groups: set[str] = set()
    matched_specs: set[str] = set()

    for spec_id, (group_id, patterns) in SPEC_PATTERNS.items():
        for pattern in patterns:
            if pattern.search(source):
                matched_specs.add(spec_id)
                matched_groups.add(group_id)
                break

    return RoutingResult(groups=matched_groups, specs=matched_specs)


def route_diff(diff_text: str) -> RoutingResult:
    """Processa um patch unificado do git e determina as specs aplicaveis.

    Args:
        diff_text: Texto bruto de saida do git diff.

    Returns:
        Instancia de RoutingResult.
    """
    added_content = extract_added_lines(diff_text)
    return route_code(added_content)


def build_parser() -> argparse.ArgumentParser:
    """Cria o parser de argumentos de linha de comando.

    Returns:
        ArgumentParser configurado.
    """
    parser = argparse.ArgumentParser(
        description="Roteador estatico de specs Python Fluente."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--diff",
        type=Path,
        help="Caminho para arquivo de diff unificado.",
    )
    group.add_argument(
        "--source",
        type=Path,
        help="Caminho para arquivo de codigo-fonte.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Imprime o resultado em formato JSON.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do script de roteamento.

    Args:
        argv: Lista de argumentos de linha de comando.

    Returns:
        Codigo de saida (0 para sucesso).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.diff:
        content = args.diff.read_text(encoding="utf-8")
        result = route_diff(content)
    else:
        content = args.source.read_text(encoding="utf-8")
        result = route_code(content)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        groups_str = ",".join(sorted(result.groups)) or "None"
        specs_str = ",".join(sorted(result.specs)) or "None"
        print(f"GROUPS: {groups_str}")
        print(f"SPECS: {specs_str}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
