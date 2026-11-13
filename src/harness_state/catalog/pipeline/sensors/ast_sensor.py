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
    target = decorator.func
    if isinstance(target, ast.Name):
        return target.id == "wraps"
    if isinstance(target, ast.Attribute):
        return target.attr == "wraps"
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


MUTABLE_CALL_NAMES = frozenset({"list", "dict", "set"})


class AstSensor(ast.NodeVisitor):
    """Visitante de AST que coleta violacoes das specs Python Fluente.

    Attributes:
        violations: Violacoes encontradas, na ordem de visita.
        function_stack: Funcoes que envolvem o no visitado no momento.
        class_depth: Profundidade de classes ativas.
        try_depth: Profundidade de blocos try...except ativos.
    """

    def __init__(self) -> None:
        """Inicializa o sensor sem violacoes e sem funcoes na pilha."""
        self.violations: list[Violation] = []
        self.function_stack: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
        self.class_depth: int = 0
        self.try_depth: int = 0

    def __repr__(self) -> str:
        """Representacao canonica informativa do sensor de AST."""
        return (
            f"AstSensor(violations_count={len(self.violations)}, "
            f"class_depth={self.class_depth}, try_depth={self.try_depth})"
        )

    def __len__(self) -> int:
        """Retorna o numero de violacoes registradas."""
        return len(self.violations)

    def __iter__(self) -> Iterator[Violation]:
        """Permite iterar diretamente sobre as violacoes encontradas."""
        return iter(self.violations)

    def add_violation(self, node: ast.AST, rule: str, message: str) -> None:
        """Registra uma violacao na posicao de um no.

        Args:
            node: No de AST infrator.
            rule: Codigo da regra violada.
            message: Descricao prescritiva da correcao.
        """
        line = getattr(node, "lineno", 1)
        column = getattr(node, "col_offset", 0) + 1
        self.violations.append(Violation(rule, line, column, message))

    def check_mutable_defaults(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Aplica ``PYF004`` em argumentos padrão mutáveis.

        Args:
            node: Definicao de funcao.
        """
        all_defaults = list(node.args.defaults)
        all_defaults.extend(d for d in node.args.kw_defaults if d is not None)
        for default in all_defaults:
            is_mutable = isinstance(default, (ast.List, ast.Dict, ast.Set))
            if not is_mutable and isinstance(default, ast.Call):
                func = default.func
                if isinstance(func, ast.Name) and func.id in MUTABLE_CALL_NAMES:
                    is_mutable = True
            if is_mutable:
                self.add_violation(
                    default,
                    "PYF004",
                    "Mutable default argument detected. Use None as default "
                    "value and initialize inside function body (SPEC-PY-06).",
                )

    def visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Aplica ``PYF001``, ``PYF004``, ``PYF007`` e visita o corpo da funcao.

        Args:
            node: Definicao de funcao (sincrona ou assincrona).
        """
        if self.function_stack:
            is_decorator_wrapper = len(self.function_stack) == 1 and any(
                is_wraps_decorator(item) for item in node.decorator_list
            )
            if not is_decorator_wrapper:
                self.add_violation(
                    node,
                    "PYF001",
                    f"Nested function '{node.name}'. Move it to module level or "
                    "to a class. Only a decorator wrapper using functools.wraps "
                    "is allowed; parametrized decorators must be classes with "
                    "__call__.",
                )
        elif self.class_depth == 0:
            is_dunder = node.name.startswith("__") and node.name.endswith("__")
            if node.name.startswith("_") and not is_dunder:
                self.add_violation(
                    node,
                    "PYF007",
                    f"Function '{node.name}' has leading underscore outside of a "
                    "class. The '_' prefix is strictly reserved for private "
                    "class members.",
                )

        self.check_mutable_defaults(node)
        self.function_stack.append(node)
        self.generic_visit(node)
        self.function_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Visita uma funcao sincrona.

        Args:
            node: Definicao de funcao.
        """
        self.visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Visita uma funcao assincrona.

        Args:
            node: Definicao de funcao assincrona.
        """
        self.visit_function(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Aplica ``PYF002`` e visita a classe como um novo escopo de funcoes.

        Metodos de uma classe nao sao funcoes aninhadas, mesmo que a classe
        esteja definida dentro de uma funcao.

        Args:
            node: Definicao de classe.
        """
        for base in node.bases:
            if isinstance(base, ast.Name) and base.id in FORBIDDEN_BASES:
                self.add_violation(
                    node,
                    "PYF002",
                    f"Class '{node.name}' subclasses built-in '{base.id}'. "
                    "Use collections.UserDict/UserList or composition.",
                )
        self.class_depth += 1
        outer_stack = self.function_stack
        self.function_stack = []
        self.generic_visit(node)
        self.function_stack = outer_stack
        self.class_depth -= 1

    def visit_Try(self, node: ast.Try) -> None:
        """Aplica ``PYF005`` e ``PYF006`` em instrucoes try...except.

        Args:
            node: Instrucao try...except.
        """
        if self.try_depth > 0:
            self.add_violation(
                node,
                "PYF005",
                "Nested try-except block detected. Keep only one try block per "
                "logical scope with flat except clauses.",
            )
        for item in node.body:
            if isinstance(item, (ast.Import, ast.ImportFrom)):
                self.add_violation(
                    item,
                    "PYF006",
                    "try-except block wrapping import statement is prohibited. "
                    "Imports must be static or use importlib.util.find_spec.",
                )
        self.try_depth += 1
        self.generic_visit(node)
        self.try_depth -= 1

    def visit_Assign(self, node: ast.Assign) -> None:
        """Aplica ``PYF007`` em variaveis soltas com leading underscore fora de classe.

        Args:
            node: Instrucao de atribuicao.
        """
        if self.class_depth == 0 and not self.function_stack:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    is_dunder = target.id.startswith("__") and target.id.endswith("__")
                    if target.id.startswith("_") and not is_dunder:
                        self.add_violation(
                            target,
                            "PYF007",
                            (
                                f"Variable '{target.id}' has leading underscore "
                                "outside of a class. The '_' prefix is strictly "
                                "reserved for private class members."
                            ),
                        )
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Aplica ``PYF007`` em variaveis anotadas fora de classe.

        Args:
            node: Instrucao de atribuicao com tipo anotado.
        """
        if self.class_depth == 0 and not self.function_stack:
            target = node.target
            if isinstance(target, ast.Name):
                is_dunder = target.id.startswith("__") and target.id.endswith("__")
                if target.id.startswith("_") and not is_dunder:
                    self.add_violation(
                        target,
                        "PYF007",
                        f"Variable '{target.id}' has leading underscore outside of a "
                        "class. The '_' prefix is strictly reserved for private "
                        "class members.",
                    )
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        """Aplica ``PYF003`` em operadores que levantam ``TypeError``.

        Args:
            node: Instrucao ``raise``.
        """
        if (
            self.function_stack
            and self.function_stack[-1].name in OPERATOR_DUNDERS
            and raises_type_error(node)
        ):
            self.add_violation(
                node,
                "PYF003",
                f"'{self.function_stack[-1].name}' raises TypeError. "
                "Return NotImplemented so Python can try the reflected operator.",
            )
        self.generic_visit(node)


def check_source(source: str) -> list[Violation]:
    """Verifica um trecho de codigo Python contra as regras do sensor.

    Args:
        source: Codigo-fonte Python.

    Returns:
        Lista de violacoes, vazia quando o codigo esta conforme.

    Raises:
        SyntaxError: Se o codigo-fonte for invalido.
    """
    sensor = AstSensor()
    sensor.visit(ast.parse(source))
    return sensor.violations


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


def main(argv: Sequence[str] | None = None) -> int:
    """Executa o sensor sobre arquivos e imprime violacoes no formato do ruff.

    Args:
        argv: Caminhos dos arquivos ou diretorios. Usa ``sys.argv[1:]`` se omitido.

    Returns:
        0 quando nao ha violacoes e 1 caso contrario.
    """
    targets = sys.argv[1:] if argv is None else argv
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
