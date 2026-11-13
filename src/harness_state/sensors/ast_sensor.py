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
* ``PYF004``: argumentos padrão mutáveis (list, dict, set) sao proibidos.
* ``PYF005``: blocos try...except aninhados sao proibidos.
* ``PYF006``: é proibido envolver imports em blocos try...except.
* ``PYF007``: prefixo '_' é estritamente proibido fora de classes.

A saída segue o formato do ``ruff`` (``arquivo:linha:coluna: CODIGO mensagem``)
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
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            child.parent = node

    for node in ast.walk(tree):
        # PYF001: nested function definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for child in ast.walk(node):
                if child is node:
                    continue
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Check if it's a functools.wraps wrapper
                    for dec in child.decorator_list:
                        if is_wraps_decorator(dec):
                            break
                    else:
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
                        break

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

        # PYF003: raise TypeError in operator
        if isinstance(node, ast.FunctionDef):
            for base_name in OPERATOR_DUNDERS:
                if node.name == base_name:
                    for child in ast.walk(node):
                        if isinstance(child, ast.Raise) and isinstance(
                            child.exc, ast.Call
                        ) and isinstance(child.exc.func, ast.Name):
                            if child.exc.func.id == "TypeError":
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
                                break

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

        # PYF006: try-except wrapping import
        if isinstance(node, ast.Try):
            for handler in node.handlers:
                for stmt in handler.body:
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

        # PYF007: leading underscore outside class
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.AnnAssign, ast.Assign)):
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                target_name = node.target.id
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                target_name = node.name
            elif isinstance(node, ast.Assign):
                # Handle simple assignments like _var = value
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        target_name = target.id
                        if target_name.startswith("_"):
                            parent = getattr(node, "parent", None)
                            if not isinstance(parent, ast.ClassDef):
                                violations.append(
                                    Violation(
                                        rule="PYF007",
                                        line=node.lineno,
                                        column=node.col_offset + 1,
                                        message=(
                                            "Prefixo '_' e reservado para membros privados de classe. "
                                            "Remova o underscore ou mova para dentro de uma classe."
                                        ),
                                    )
                                )
                else:
                    target_name = None
            if target_name and target_name.startswith("_"):
                parent = getattr(node, "parent", None)
                if not isinstance(parent, ast.ClassDef):
                    violations.append(
                        Violation(
                            rule="PYF007",
                            line=node.lineno,
                            column=node.col_offset + 1,
                            message=(
                                "Prefixo '_' e reservado para membros privados de classe. "
                                "Remova o underscore ou mova para dentro de uma classe."
                            ),
                        )
                    )

    return violations


class AstSensor:
    """Sensor AST deterministico para validar regras Python Fluente."""

    def __init__(self) -> None:
        self.violations: list[Violation] = []

    def run(self, paths: list[Path]) -> list[Violation]:
        """Executa o sensor sobre uma lista de arquivos ou diretorios."""
        self.violations = []
        for path in paths:
            if path.is_file() and path.suffix == ".py":
                self._check_file(path)
            elif path.is_dir():
                for py_file in path.rglob("*.py"):
                    self._check_file(py_file)
        return self.violations

    def _check_file(self, file_path: Path) -> None:
        try:
            source = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return

        violations = check_source(source)
        for v in violations:
            v.file_path = str(v.file_path) if hasattr(v, 'file_path') else str(path)
            v.line = v.line
            v.column = v.column
            v.message = v.message
            v.rule = v.rule
            self.violations.append(v)

    def __len__(self) -> int:
        return len(self.violations)

    def __iter__(self) -> Iterator[Violation]:
        return iter(self.violations)

    def __repr__(self) -> str:
        return f"AstSensor(violations_count={len(self.violations)})"


def main(args: list[str]) -> int:
    """Ponto de entrada CLI para o sensor AST."""
    if not args:
        print("Uso: ast_sensor <arquivo.py> [arquivo2.py ...]", file=sys.stderr)
        return 1

    sensor = AstSensor()
    paths = [Path(arg) for arg in args]
    violations = sensor.run(paths)

    for v in violations:
        print(f"{v.file_path}:{v.line}:{v.column}: {v.rule} {v.message}")

    return 1 if violations else 0