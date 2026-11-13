"""Sensor determinístico de complexidade cognitiva Python via complexipy (SPEC-PY-CX).

Executa o ``complexipy`` sobre arquivos ou diretórios Python (ou sobre o diff Git),
identifica funções que excedem o limite máximo de complexidade cognitiva (padrão 15)
e extrai as sugestões determinísticas de refatoração (`refactor_plans`) do complexipy,
formatando-as em linhas prescritivas (`arquivo:linha:coluna: CODIGO mensagem`)
compatíveis com o `format_feedback.sh` para alimentar diretamente os agentes LLM.

Este artefato é copiado para repositórios-alvo pelo instalador, onde ``complexipy``
é dependência opcional: a importação é feita sob demanda via `load_complexipy`,
degradando graciosamente (lista vazia de violações) quando ausente.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import complexipy

DEFAULT_MAX_COMPLEXITY = 15

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".env",
        "node_modules",
        "dist",
        "build",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "templates",
    }
)


@dataclass(frozen=True, slots=True)
class ComplexityViolation:
    """Violação de complexidade cognitiva enriquecida com sugestões do complexipy.

    Attributes:
        file_path: Caminho do arquivo analisado.
        line: Linha inicial da função ou do bloco sugerido para refatoração.
        column: Coluna inicial (1-indexed).
        rule: Código da regra do complexipy (ex: C001, C002, C003 ou CX001).
        function_name: Nome da função ou método infrator.
        complexity: Complexidade cognitiva calculada pelo complexipy.
        max_allowed: Limite máximo de complexidade permitido.
        suggestion_text: Sugestão prescritiva de refatoração gerada pelo complexipy.
    """

    file_path: str
    line: int
    column: int
    rule: str
    function_name: str
    complexity: int
    max_allowed: int
    suggestion_text: str

    def __repr__(self) -> str:
        """Representação canônica informativa da violação de complexidade."""
        return (
            f"ComplexityViolation(file_path={self.file_path!r}, "
            f"function_name={self.function_name!r}, rule={self.rule!r}, "
            f"complexity={self.complexity}, max_allowed={self.max_allowed})"
        )

    def format_output(self) -> str:
        """Formata a violação no padrão consumido pelo `format_feedback.sh`.

        Returns:
            Linha única no padrão `arquivo:linha:coluna: REGRA mensagem`.
        """
        clean_suggestion = " ".join(self.suggestion_text.split())
        return (
            f"{self.file_path}:{self.line}:{self.column}: {self.rule} "
            f"Function '{self.function_name}' has cognitive complexity "
            f"{self.complexity} (max allowed: {self.max_allowed}). "
            f"{clean_suggestion}"
        )


def is_ignored_python_path(py_file: Path) -> bool:
    """Verifica se o caminho contém diretórios ignorados ou ocultos.

    Args:
        py_file: Caminho do arquivo Python.

    Returns:
        True se o arquivo deve ser ignorado na varredura.
    """
    return any(
        part in IGNORED_DIRS or (part.startswith(".") and part != ".")
        for part in py_file.parts
    )


def expand_target_python_files(target_path: Path) -> list[Path]:
    """Expande um único caminho (arquivo ou diretório) em uma lista de `.py`.

    Args:
        target_path: Caminho de arquivo ou diretório.

    Returns:
        Lista ordenada de arquivos Python elegíveis.
    """
    if not target_path.exists():
        return []
    if target_path.is_file():
        return [target_path] if target_path.suffix == ".py" else []
    if not target_path.is_dir():
        return []
    return [
        py_file
        for py_file in sorted(target_path.rglob("*.py"))
        if not is_ignored_python_path(py_file)
    ]


def collect_python_files(targets: Sequence[str], root_dir: Path) -> list[Path]:
    """Coleta arquivos Python elegíveis a partir de alvos (arquivos ou diretórios).

    Args:
        targets: Caminhos passados na linha de comando.
        root_dir: Diretório raiz de referência para cálculo de caminhos relativos.

    Returns:
        Lista ordenada de caminhos para arquivos `.py` sem duplicatas.
    """
    collected: list[Path] = []
    seen: set[Path] = set()
    effective_targets = list(targets) if targets else [str(root_dir)]

    for raw_target in effective_targets:
        for py_file in expand_target_python_files(Path(raw_target)):
            resolved = py_file.resolve()
            if resolved not in seen:
                seen.add(resolved)
                collected.append(py_file)
    return collected


def format_code_suggestion(code_sug: object | None) -> str:
    """Formata o objeto `CodeSuggestion` de um plano de refatoração do complexipy.

    Args:
        code_sug: Instância opcional de `complexipy.CodeSuggestion`.

    Returns:
        Texto compacto com descrição e código substituto sugerido, ou string vazia.
    """
    if code_sug is None:
        return ""
    sug_desc = getattr(code_sug, "description", "")
    replacement = getattr(code_sug, "replacement", "")
    chunks: list[str] = []
    if sug_desc:
        chunks.append(f"Safe refactor: {sug_desc}.")
    if replacement:
        compact_rep = " | ".join(
            line.strip() for line in replacement.splitlines() if line.strip()
        )
        if len(compact_rep) > 240:
            compact_rep = compact_rep[:237] + "..."
        chunks.append(f"Suggested replacement: `{compact_rep}`")
    return " ".join(chunks)


def format_plan_suggestion(plan: object) -> str:
    """Constrói texto prescritivo compacto a partir de um `RefactorPlan` do complexipy.

    Args:
        plan: Instância de `complexipy.RefactorPlan`.

    Returns:
        String em linha única com título, linhas afetadas, redução estimada e ajuda.
    """
    rule_id = getattr(plan, "rule_id", "CX001") or "CX001"
    title = getattr(plan, "title", "") or getattr(plan, "description", "")
    line_start = getattr(plan, "line_start", 1)
    line_end = getattr(plan, "line_end", line_start)
    reduction = getattr(plan, "estimated_reduction", 0)
    after = getattr(plan, "estimated_complexity_after", 0)
    help_text = getattr(plan, "help", "") or getattr(plan, "explanation", "")

    parts = [
        (
            f"Complexipy suggestion [{rule_id}]: {title} "
            f"(lines {line_start}-{line_end}, est. -{reduction} -> {after})."
        )
    ]
    if help_text:
        parts.append(f"Help: {help_text}")

    sug_extra = format_code_suggestion(getattr(plan, "suggestion", None))
    if sug_extra:
        parts.append(sug_extra)

    return " ".join(parts)


def build_violation_from_function(
    display_path: str,
    func: object,
    max_complexity: int,
) -> ComplexityViolation:
    """Cria uma `ComplexityViolation` a partir de um `FunctionComplexity`.

    Args:
        display_path: Caminho do arquivo para exibição.
        func: Instância de `complexipy.FunctionComplexity`.
        max_complexity: Limite máximo de complexidade permitido.

    Returns:
        Instância populada de `ComplexityViolation`.
    """
    func_name = str(getattr(func, "name", "<unknown>"))
    complexity = int(getattr(func, "complexity", 0))
    func_line = int(getattr(func, "line_start", 1)) or 1
    plans = list(getattr(func, "refactor_plans", []) or [])

    if plans:
        primary_plan = plans[0]
        rule_id = str(getattr(primary_plan, "rule_id", "CX001") or "CX001")
        line = int(getattr(primary_plan, "line_start", func_line) or func_line)
        column = int(getattr(primary_plan, "column_start", 1) or 1)
        plan_texts = [format_plan_suggestion(p) for p in plans[:2]]
        suggestion_text = " ".join(plan_texts)
    else:
        rule_id = "CX001"
        line = func_line
        column = 1
        suggestion_text = (
            "Complexipy suggestion: Decompose this function into smaller, "
            "focused helper functions at module/class level or use guard clauses "
            "(early returns/continues) to reduce nesting depth."
        )

    return ComplexityViolation(
        file_path=display_path,
        line=line,
        column=column,
        rule=rule_id,
        function_name=func_name,
        complexity=complexity,
        max_allowed=max_complexity,
        suggestion_text=suggestion_text,
    )


def check_complexity_source(
    source: str,
    file_label: str = "<memory>",
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
) -> list[ComplexityViolation]:
    """Analisa uma string de código Python em memória via `complexipy.code_complexity`.

    Args:
        source: Código-fonte Python a analisar.
        file_label: Rótulo do arquivo para constar nas violações.
        max_complexity: Limite máximo de complexidade cognitiva permitido.

    Returns:
        Lista de `ComplexityViolation` para funções que excedem `max_complexity`.
    """
    module = load_complexipy()
    if module is None:
        return []

    result = module.code_complexity(source, with_plans=True)
    violations: list[ComplexityViolation] = []
    for func in getattr(result, "functions", []):
        if int(getattr(func, "complexity", 0)) > max_complexity:
            violations.append(
                build_violation_from_function(file_label, func, max_complexity)
            )
    return violations


def resolve_relative_file_path(py_file: Path, resolved_root: Path) -> str:
    """Resolve o caminho relativo do arquivo em relação à raiz do repositório.

    Args:
        py_file: Caminho do arquivo Python.
        resolved_root: Diretório raiz de invocação.

    Returns:
        String com o caminho relativo ou original caso fora da raiz.
    """
    try:
        return str(py_file.resolve().relative_to(resolved_root))
    except ValueError:
        return str(py_file)


def load_complexipy() -> ModuleType | None:
    """Importa `complexipy` sob demanda, respeitando sua opcionalidade no alvo.

    Returns:
        Módulo `complexipy` carregado ou None quando não instalado.
    """
    if importlib.util.find_spec("complexipy") is None:
        return None

    import complexipy

    return complexipy


def analyze_single_file(file_path: str) -> complexipy.FileComplexity | None:
    """Executa `complexipy.file_complexity` com tratamento plano de falhas.

    Args:
        file_path: Caminho do arquivo a ser analisado.

    Returns:
        Objeto `FileComplexity` ou None se o arquivo não puder ser
        lido/parseado (contrato documentado do sensor: arquivo ilegível
        não bloqueia a análise dos demais) ou se o `complexipy` não
        estiver disponível.
    """
    module = load_complexipy()
    if module is None:
        return None
    try:
        return module.file_complexity(file_path, with_plans=True)
    except ValueError:
        return None


def analyze_files_batch(
    py_files: Sequence[Path],
    resolved_root: Path,
) -> tuple[list[complexipy.FileComplexity], dict[str, str]]:
    """Analisa todos os arquivos Python coletados com o `complexipy`.

    Args:
        py_files: Sequência de caminhos de arquivos `.py`.
        resolved_root: Diretório raiz de invocação.

    Returns:
        Tupla `(file_results, display_path_map)`.
    """
    file_results: list[complexipy.FileComplexity] = []
    display_map: dict[str, str] = {}
    for py_file in py_files:
        rel_path = resolve_relative_file_path(py_file, resolved_root)
        fc = analyze_single_file(rel_path) or analyze_single_file(str(py_file))
        if fc is None:
            continue
        file_results.append(fc)
        fc_path = str(getattr(fc, "path", rel_path))
        display_map[fc_path] = rel_path
    return file_results, display_map


def is_diff_entry_regressed(entry: complexipy.DiffEntry, max_complexity: int) -> bool:
    """Avalia se uma entrada do diff representa uma regressão acima do limite.

    Args:
        entry: Objeto `complexipy.DiffEntry`.
        max_complexity: Limite máximo permitido.

    Returns:
        True se a função é nova ou aumentou sua complexidade acima do limite.
    """
    new_c = entry.new_complexity
    if new_c is None or int(new_c) <= max_complexity:
        return False
    status_str = str(entry.status)
    old_c = entry.old_complexity
    return (
        "NEW" in status_str
        or "REGRESSED" in status_str
        or (old_c is not None and int(new_c) > int(old_c))
    )


def compute_regressed_keys(
    file_results: list[complexipy.FileComplexity],
    diff_ref: str,
    resolved_root: Path,
    max_complexity: int,
) -> set[tuple[str, str]] | None:
    """Calcula o conjunto de funções novas ou regredidas no diff Git.

    Args:
        file_results: Lista de objetos `FileComplexity`.
        diff_ref: Referência Git (ex: `HEAD`).
        resolved_root: Diretório raiz do repositório.
        max_complexity: Limite máximo de complexidade permitido.

    Returns:
        Conjunto de tuplas `(file_path, func_name)` regredidas, ou None se
        a comparação falhar (ex: erro interno do `compute_diff` ou ambiente
        sem `complexipy` — o contrato do sensor é degradar para análise
        completa sem diff).
    """
    module = load_complexipy()
    if module is None:
        return None

    try:
        diff_entries = module.compute_diff(
            file_results, diff_ref, str(resolved_root)
        )
    except ValueError:
        return None

    return {
        (entry.file_path, entry.func_name)
        for entry in diff_entries
        if is_diff_entry_regressed(entry, max_complexity)
    }


def extract_file_violations(
    fc: object,
    display_path: str,
    max_complexity: int,
    regressed_keys: set[tuple[str, str]] | None,
) -> list[ComplexityViolation]:
    """Extrai violações de um único resultado `FileComplexity`.

    Args:
        fc: Objeto `FileComplexity` do arquivo.
        display_path: Caminho amigável para exibição.
        max_complexity: Limite máximo permitido.
        regressed_keys: Filtro opcional de funções regredidas no diff.

    Returns:
        Lista de `ComplexityViolation` do arquivo.
    """
    fc_path = str(getattr(fc, "path", display_path))
    violations: list[ComplexityViolation] = []
    for func in getattr(fc, "functions", []):
        if int(getattr(func, "complexity", 0)) <= max_complexity:
            continue
        func_name = str(getattr(func, "name", ""))
        if regressed_keys is not None:
            matches_diff = (fc_path, func_name) in regressed_keys or (
                display_path,
                func_name,
            ) in regressed_keys
            if not matches_diff:
                continue
        violations.append(
            build_violation_from_function(display_path, func, max_complexity)
        )
    return violations


def run_complexity_sensor(
    targets: Sequence[str],
    max_complexity: int = DEFAULT_MAX_COMPLEXITY,
    diff_ref: str | None = None,
    root_dir: Path | None = None,
) -> list[ComplexityViolation]:
    """Executa a análise do `complexipy` sobre os arquivos ou diff especificado.

    Quando `diff_ref` é informado (ex: `'HEAD'` no pre-commit ou base branch),
    apenas funções novas ou cuja complexidade piorou acima de `max_complexity`
    em relação a `diff_ref` são reportadas como regressão.

    Args:
        targets: Caminhos de arquivos ou diretórios a inspecionar.
        max_complexity: Limite máximo permitido de complexidade cognitiva.
        diff_ref: Referência Git opcional para checagem apenas de regressões no diff.
        root_dir: Diretório raiz de invocação do repositório.

    Returns:
        Lista de violações com sugestões de refatoração prontas para o LLM.
    """
    if load_complexipy() is None:
        return []

    resolved_root = (root_dir or Path.cwd()).resolve()
    py_files = collect_python_files(targets, resolved_root)
    if not py_files:
        return []

    file_results, display_map = analyze_files_batch(py_files, resolved_root)
    regressed_keys: set[tuple[str, str]] | None = None
    if diff_ref and file_results:
        regressed_keys = compute_regressed_keys(
            file_results, diff_ref, resolved_root, max_complexity
        )

    violations: list[ComplexityViolation] = []
    for fc in file_results:
        fc_path = str(getattr(fc, "path", ""))
        display_path = display_map.get(fc_path, fc_path)
        violations.extend(
            extract_file_violations(fc, display_path, max_complexity, regressed_keys)
        )
    return violations


def build_arg_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos de linha de comando do sensor.

    Returns:
        Instância configurada de `argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Sensor determinístico de complexidade cognitiva Python (complexipy) "
            "com sugestões prescritivas de refatoração para agentes LLM."
        )
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=["."],
        help="Arquivos ou diretórios Python a analisar (padrão: diretório atual).",
    )
    parser.add_argument(
        "--max-complexity-allowed",
        "-m",
        type=int,
        default=DEFAULT_MAX_COMPLEXITY,
        help=(
            "Complexidade cognitiva máxima permitida "
            f"(padrão: {DEFAULT_MAX_COMPLEXITY})."
        ),
    )
    parser.add_argument(
        "--diff",
        "-d",
        dest="diff_ref",
        default=None,
        help=(
            "Compara contra uma referência Git (ex: HEAD) e reprova apenas regressões."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Ponto de entrada CLI do sensor de complexidade cognitiva.

    Args:
        argv: Lista opcional de argumentos CLI.

    Returns:
        0 se nenhuma violação foi encontrada, 1 caso contrário.
    """
    parser = build_arg_parser()
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    violations = run_complexity_sensor(
        targets=args.targets,
        max_complexity=args.max_complexity_allowed,
        diff_ref=args.diff_ref,
    )
    for violation in violations:
        print(violation.format_output())
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
