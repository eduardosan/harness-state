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


def extract_added_lines(diff_text: str, file_suffix: str | None = None) -> str:
    """Extrai somente as linhas adicionadas ou modificadas de um git diff.

    Descarta cabecalhos de patch e linhas de contexto ou exclusao.
    Opcionalmente filtra arquivos por sufixo de extensao (ex: '.py').

    Args:
        diff_text: Texto no formato unified diff.
        file_suffix: Extensao opcional para filtrar os arquivos (ex: '.py').

    Returns:
        String consolidada contendo o conteudo das linhas adicionadas.
    """
    lines: list[str] = []
    current_file = ""
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            continue
        if line.startswith("+++ "):
            current_file = line[4:].strip()
            continue
        if file_suffix and current_file and not current_file.endswith(file_suffix):
            continue
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
    return "\n".join(lines)


def line_matches_diff_target_suffix(line: str, file_suffix: str) -> bool:
    """Verifica se uma linha de cabecalho de patch aponta para o sufixo desejado.

    Args:
        line: Linha de cabecalho de diff.
        file_suffix: Extensao esperada (ex: '.py').

    Returns:
        True se a linha declarar um arquivo alvo com o sufixo especificado.
    """
    if line.startswith("+++ b/"):
        return line[6:].strip().endswith(file_suffix)
    if line.startswith("+++ "):
        return line[4:].strip().endswith(file_suffix)
    return False


def filter_diff_by_suffix(diff_text: str, file_suffix: str = ".py") -> str:
    """Filtra blocos de patch do git diff que correspondam ao sufixo de arquivo.

    Args:
        diff_text: Texto no formato unified diff.
        file_suffix: Extensao opcional para filtrar os arquivos (ex: '.py').

    Returns:
        String consolidada contendo os blocos de diff dos arquivos correspondentes.
    """
    blocks: list[str] = []
    current_block: list[str] = []
    include_current = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            if current_block and include_current:
                blocks.append("\n".join(current_block))
            current_block = [line]
            include_current = False
            continue

        if line_matches_diff_target_suffix(line, file_suffix):
            include_current = True

        current_block.append(line)

    if current_block and include_current:
        blocks.append("\n".join(current_block))

    return "\n\n".join(blocks)


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

    Filtra estritamente linhas adicionadas em arquivos Python (.py).

    Args:
        diff_text: Texto bruto de saida do git diff.

    Returns:
        Instancia de RoutingResult.
    """
    added_content = extract_added_lines(diff_text, file_suffix=".py")
    if not added_content.strip():
        if "+++ " not in diff_text:
            return route_code(diff_text)
        return RoutingResult()
    return route_code(added_content)


def get_spec_reference_dir() -> Path | None:
    """Localiza o diretorio de especificacoes de referencia Python Fluente.

    Returns:
        Caminho Path se encontrado, ou None se nenhum diretorio for valido.
    """
    candidates = [
        Path(__file__).resolve().parent
        / "catalog"
        / "skills"
        / "python"
        / "fluent-python"
        / "references",
        Path(__file__).resolve().parent.parent.parent / "specs" / "python",
    ]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return None


def extract_normative_rules(spec_markdown: str) -> str:
    """Extrai exclusivamente a secao de regras normativas de uma especificacao.

    Args:
        spec_markdown: Conteudo Markdown integral da especificacao.

    Returns:
        Texto contendo as regras normativas extraidas.
    """
    start_marker = "## 2. Regras normativas"
    if start_marker not in spec_markdown:
        return spec_markdown.strip()

    section = spec_markdown.split(start_marker, 1)[1]
    end_marker = "## 3."
    if end_marker in section:
        section = section.split(end_marker, 1)[0]

    return section.strip()


def find_spec_file_in_dir(spec_id: str, directory: Path) -> Path | None:
    """Localiza o arquivo de especificacao correspondente ao spec_id no diretorio.

    Args:
        spec_id: Identificador da especificacao (ex: PY-01 ou PY-05).
        directory: Diretorio de busca.

    Returns:
        Path do arquivo encontrado ou None.
    """
    pattern = f"*{spec_id}*.md"
    matches = sorted(directory.glob(pattern))
    if matches:
        return matches[0]
    return None


def collect_fluent_python_guidelines(
    diff_text: str, specs_dir: Path | None = None
) -> str:
    """Coleta e formata as regras normativas das specs de Python Fluente ativadas.

    Args:
        diff_text: Texto do git diff unificado.
        specs_dir: Diretorio opcional contendo os arquivos SPEC-PY-*.md.

    Returns:
        Bloco de diretrizes Markdown ou string vazia se nenhuma spec for ativada.
    """
    result = route_diff(diff_text)
    if not result.specs:
        return ""

    effective_dir = specs_dir if specs_dir is not None else get_spec_reference_dir()
    if effective_dir is None or not effective_dir.is_dir():
        return ""

    guideline_sections: list[str] = []
    for spec_id in sorted(result.specs):
        spec_file = find_spec_file_in_dir(spec_id, effective_dir)
        if spec_file and spec_file.is_file():
            content = spec_file.read_text(encoding="utf-8")
            rules = extract_normative_rules(content)
            guideline_sections.append(
                f"#### SPEC-{spec_id} ({spec_file.stem})\n{rules}"
            )

    if not guideline_sections:
        return ""

    joined_rules = "\n\n".join(guideline_sections)
    return (
        "### Diretrizes Normativas de Python Fluente Aplicáveis ao Diff\n\n"
        "As alterações submetidas ativam os padrões das seguintes "
        "especificações canônicas:\n\n"
        f"{joined_rules}"
    )


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
