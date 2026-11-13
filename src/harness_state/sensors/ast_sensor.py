"""Sensor AST das specs Python Fluente (SPEC-PY-00).

Verifica regras que o ``ruff`` nao cobre:

* ``PYF000``: arquivo com erro de sintaxe.
* ``PYF001``: funcao definida dentro de outra funcao, exceto o ``wrapper``
  de um decorador simples que usa ``functools.wraps``.
* ``PYF002``: classe que herda diretamente de ``dict``, ``list`` ou ``set``.
  Os metodos desses tipos, implementados em C, ignoram as sobrescritas
  (Python Fluente, secao 14.3); use ``UserDict``, ``UserList`` ou composicao.
  ``str`` fica de fora de proposito, por causa do padrao ``class C(str, Enum)``.
* ``PYF003``: ``raise TypeError`` dentro de operador aritmetico ou de
  comparacao, que deveria retornar ``NotImplemented``.
* ``PYF004``: argumentos padrao mutaveis (list, dict, set) sao proibidos.
* ``PYF005``: blocos try...except aninhados sao proibidos.
* ``PYF006``: e proibido envolver imports em blocos try...except.
* ``PYF007``: prefixo '_' e estritamente proibido fora de classes.

A saida segue o formato do ``ruff`` (``arquivo:linha:coluna: CODIGO mensagem``)
para ser interpretada pelo ``format_feedback.sh``.
"""

import ast
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_BASES = frozenset({"dict", "list", "set"})

ARITHMETIC_NAMES = (
    "add",
    "sub",
    "mul",
    "truediv",
    "floordiv",
    "mod",
    "divmod",
    "matmul",
    "pow",
    "and",
    "or",
    "xor",
    "lshift",
    "rshift",
)

COMPARISON_DUNDERS = frozenset(
    {"__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__"}
)

OPERATOR_DUNDERS = COMPARISON_DUNDERS | frozenset(
    f"__{prefix}{name}__" for name in ARITHMETIC_NAMES for prefix in ("", "r", "i")
)


@dataclass(frozen=True)
class Violation:
    """Violacao de uma regra do sensor.

    Attributes:
        rule: Codigo da regra (ex: ``PYF001``).
        line: Linha do codigo infrator, a partir de 1.
        column: Coluna do codigo infrator, a partir de 1.
        message: Descricao prescritiva da correcao.
    """

    rule: str
    line: int
    column: int
    message: str


def is_wraps_decorator(decorator: ast.expr) -> bool:
    """Indica se um decorador e uma chamada a ``functools.wraps``.

    Args:
        decorator: No de AST do decorador.

    Returns:
        True para ``@wraps(...)`` e ``@functools.wraps(...)``.
    """
    if not isinstance(decorator, ast.Call):
        return False
    func = decorator.func
    if isinstance(func, ast.Name):
        return func.id == "wraps"
    if isinstance(func, ast.Attribute):
        return func.attr == "wraps" and isinstance(func.value, ast.Name) and func.value.id == "functools"
    return False


def raises_type_error(node: ast.Raise) -> bool:
    """Indica se um ``raise`` levanta ``TypeError``.

    Args:
        node: No de AST do ``raise``.

    Returns:
        True para ``raise TypeError`` e ``raise TypeError(...)``.
    """
    exc = node.exc
    if isinstance(exc, ast.Call):
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "TypeError"


def has_function_ancestor(parent_map: dict[ast.AST, ast.AST], node: ast.AST) -> bool:
    """Indica se o no esta aninhado (transitivamente) dentro de uma funcao.

    Args:
        parent_map: Mapa filho -> pai construido sobre a arvore AST.
        node: No de AST a partir do qual subir a arvore.

    Returns:
        True quando algum ancestral e FunctionDef ou AsyncFunctionDef.
    """
    current = parent_map.get(node)
    while current is not None:
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return True
        current = parent_map.get(current)
    return False


def pyf007_violation(line: int, col_offset: int) -> Violation:
    """Constrói a violação PYF007 (prefixo '_' fora de classe).

    Args:
        line: Linha da definição infratora (a partir de 1).
        col_offset: Coluna base zero do nó infrator.

    Returns:
        Violation pronta para ser anexada à lista de resultados.
    """
    return Violation(
        rule="PYF007",
        line=line,
        column=col_offset + 1,
        message=(
            "Prefixo '_' e reservado para membros privados de classe. "
            "Remova o underscore ou mova para dentro de uma classe."
        ),
    )


def check_source(source: str) -> list[Violation]:
    """Verifica um trecho de codigo fonte contra as regras do sensor AST.

    Args:
        source: Codigo Python a ser verificado.

    Returns:
        Lista de violacoes encontradas.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [
            Violation(
                rule="PYF000",
                line=exc.lineno or 1,
                column=exc.offset or 1,
                message=f"SyntaxError: {exc.msg}",
            )
        ]

    violations: list[Violation] = []

    # Add parent references to nodes for context-aware checks
    # Use a dict to track parent relationships since AST nodes are immutable
    parent_map: dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parent_map[child] = node

    for node in ast.walk(tree):
        # PYF001: nested function definitions — filhos DIRETOS apenas, para nao
        # duplicar violacoes de netos (que sao checados quando o pai e visitado).
        # A excecao de functools.wraps cobre apenas o wrapper de um decorador de
        # nivel de modulo; wrapper dentro de decorador aninhado (factory) tambem
        # viola — o padrao prescrito e classe com __call__.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in node.body:
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                is_wraps_wrapper = any(
                    is_wraps_decorator(dec) for dec in child.decorator_list
                )
                if is_wraps_wrapper and not has_function_ancestor(parent_map, node):
                    continue
                violations.append(
                    Violation(
                        rule="PYF001",
                        line=child.lineno,
                        column=child.col_offset + 1,
                        message=(
                            "Funcao definida dentro de outra funcao. "
                            "Use functools.wraps para decoradores ou extraia para o nivel do modulo."
                        ),
                    )
                )

        # PYF002: subclassing builtin containers
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                if isinstance(base, ast.Name) and base.id in FORBIDDEN_BASES:
                    violations.append(
                        Violation(
                            rule="PYF002",
                            line=node.lineno,
                            column=node.col_offset + 1,
                            message=(
                                f"Classe herda diretamente de {base.id}. "
                                "Os metodos desses tipos, implementados em C, ignoram as "
                                "sobrescritas; use UserDict, UserList ou composicao."
                            ),
                        )
                    )

        # PYF003: raise TypeError in operator (inclui operadores async)
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name in OPERATOR_DUNDERS
        ):
            for child in ast.walk(node):
                if isinstance(child, ast.Raise) and raises_type_error(child):
                    violations.append(
                        Violation(
                            rule="PYF003",
                            line=child.lineno,
                            column=child.col_offset + 1,
                            message=(
                                "Levantar TypeError em operador impede "
                                "o operador reflexo; retorne NotImplemented."
                            ),
                        )
                    )

        # PYF004: mutable default arguments
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    violations.append(
                        Violation(
                            rule="PYF004",
                            line=node.lineno,
                            column=node.col_offset + 1,
                            message=(
                                "Argumento padrao mutavel (list, dict, set). "
                                "Use None como padrao e crie o objeto dentro da funcao."
                            ),
                        )
                    )

        # PYF005: nested try-except
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, ast.Try):
                    violations.append(
                        Violation(
                            rule="PYF005",
                            line=child.lineno,
                            column=child.col_offset + 1,
                            message=(
                                "Blocos try...except aninhados sao proibidos. "
                                "Use um unico bloco try com multiplos except."
                            ),
                        )
                    )
                    break

        # PYF006: try-except wrapping import — cobre body do try, handlers,
        # orelse e finalbody: o import esta "dentro" do try-except em qualquer
        # dessas posicoes.
        if isinstance(node, ast.Try):
            try_body_stmts = [
                *node.body,
                *(stmt for handler in node.handlers for stmt in handler.body),
                *node.orelse,
                *node.finalbody,
            ]
            for stmt in try_body_stmts:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    violations.append(
                        Violation(
                            rule="PYF006",
                            line=stmt.lineno,
                            column=stmt.col_offset + 1,
                            message=(
                                "Imports dentro de try-except sao proibidos. "
                                "Use importlib.util.find_spec para imports condicionais."
                            ),
                        )
                    )
                    break

        # PYF007: leading underscore outside class — o prefixo '_' e reservado
        # para membros privados no interior de classes. Aplica-se a funcoes,
        # anotacoes simples e cada Name target de Assign (atributos como
        # self._x chegam aqui como ast.Attribute e, portanto, nao sao targets).
        parent = parent_map.get(node)
        in_class = isinstance(parent, ast.ClassDef)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_") and not in_class:
                violations.append(pyf007_violation(node.lineno, node.col_offset))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.startswith("_") and not in_class:
                violations.append(pyf007_violation(node.lineno, node.col_offset))
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id.startswith("_")
                    and not in_class
                ):
                    violations.append(pyf007_violation(node.lineno, node.col_offset))

    return violations


def check_file(path: Path) -> list[Violation]:
    """Verifica um arquivo Python, convertendo erro de sintaxe em violacao.

    Args:
        path: Caminho do arquivo.

    Returns:
        Lista de violacoes encontradas no arquivo.
    """
    try:
        return check_source(path.read_text(encoding="utf-8"))
    except SyntaxError as error:
        line = error.lineno or 1
        column = error.offset or 1
        return [Violation("PYF000", line, column, f"Syntax error: {error.msg}")]
    except (OSError, UnicodeDecodeError):
        return []


def collect_paths(targets: Sequence[str]) -> list[Path]:
    """Coleta caminhos de arquivos .py a partir de arquivos e diretorios.

    Args:
        targets: Lista de caminhos para arquivos ou diretorios.

    Returns:
        Lista ordenada de caminhos para arquivos Python.
    """
    resolved: list[Path] = []
    for item in targets:
        path = Path(item)
        if path.is_file() and path.suffix == ".py":
            resolved.append(path)
        elif path.is_dir():
            resolved.extend(
                sorted(
                    file_path
                    for file_path in path.rglob("*.py")
                    if not any(part.startswith(".") for part in file_path.parts)
                )
            )
    return resolved


class AstSensor:
    """Sensor AST deterministico para validar regras Python Fluente."""

    def __init__(self) -> None:
        self.violations: list[Violation] = []

    def run(self, paths: list[Path]) -> list[Violation]:
        """Executa o sensor sobre uma lista de arquivos ou diretorios."""
        self.violations = []
        for path in paths:
            if path.is_file() and path.suffix == ".py":
                self.violations.extend(check_file(path))
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    self.violations.extend(check_file(py_file))
        return self.violations

    def __len__(self) -> int:
        return len(self.violations)

    def __iter__(self) -> Iterator[Violation]:
        return iter(self.violations)

    def __repr__(self) -> str:
        return f"AstSensor(violations_count={len(self.violations)})"


def main(args: Sequence[str] | None = None) -> int:
    """Executa o sensor sobre arquivos e imprime violacoes no formato do ruff.

    Args:
        args: Caminhos dos arquivos ou diretorios. Usa ``sys.argv[1:]`` se omitido.

    Returns:
        0 quando nao ha violacoes e 1 caso contrario.
    """
    targets = sys.argv[1:] if args is None else args
    paths = collect_paths(targets)
    found = False
    for path in paths:
        for violation in check_file(path):
            found = True
            print(
                f"{path}:{violation.line}:{violation.column}: "
                f"{violation.rule} {violation.message}"
            )
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())