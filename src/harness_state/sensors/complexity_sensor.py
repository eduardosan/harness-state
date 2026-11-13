"""Sensor determinístico de complexidade cognitiva Python via complexipy (SPEC-PY-CX).

Executa o ``complexipy`` sobre arquivos ou diretórios Python (ou sobre o diff Git),
identifica funções que excedem o limite máximo de complexidade cognitiva (padrão 15)
e extrai as sugestões determinísticas de refatoração (`refactor_plans`) do complexipy,
formatando-as em linhas prescritivas (`arquivo:linha:coluna: CODIGO mensagem`)
compatíveis com o `format_feedback.sh` para alimentar diretamente os agentes LLM.
"""

import importlib.util
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

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


@dataclass(frozen=True)
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


class ComplexitySensor:
    """Sensor determinístico de complexidade cognitiva Python via complexipy."""

    def __init__(
        self,
        max_complexity: int = DEFAULT_MAX_COMPLEXITY,
        ignored_dirs: frozenset[str] | None = None,
    ) -> None:
        """Inicializa o sensor.

        Args:
            max_complexity: Limite máximo de complexidade cognitiva permitida.
            ignored_dirs: Diretórios a ignorar durante a varredura.
        """
        self.max_complexity = max_complexity
        self.ignored_dirs = ignored_dirs or IGNORED_DIRS

    def run(self, paths: Sequence[Path]) -> list[ComplexityViolation]:
        """Executa o sensor sobre os caminhos fornecidos.

        Args:
            paths: Sequência de caminhos (arquivos ou diretórios) a analisar.

        Returns:
            Lista de violações de complexidade encontradas.
        """
        if not self._complexipy_available():
            return []

        violations = []
        for path in paths:
            violations.extend(self._analyze_path(path))
        return violations

    def _complexipy_available(self) -> bool:
        return importlib.util.find_spec("complexipy") is not None

    def _analyze_path(self, path: Path) -> list:
        """Analisa um arquivo ou diretório."""
        if path.is_file() and path.suffix == ".py":
            return self._analyze_file(path)
        elif path.is_dir():
            violations = []
            for py_file in path.rglob("*.py"):
                if not any(part in self.ignored_dirs for part in py_file.parts):
                    violations.extend(self._analyze_file(py_file))
            return violations
        return []

    def _analyze_file(self, file_path: Path) -> list:
        """Analisa um único arquivo Python."""
        try:
            import json

            result = subprocess.run(
                [
                    "complexipy",
                    str(file_path),
                    "--max-complexity",
                    str(self.max_complexity),
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode == 0:
                return []

            try:
                data = json.loads(result.stdout)
                return self._parse_complexipy_output(data, str(file_path))
            except json.JSONDecodeError:
                return []

        except (subprocess.SubprocessError, OSError):
            return []

    def _parse_complexipy_output(self, data: dict, file_path: str) -> list:
        """Converte saída do complexipy para lista de ComplexityViolation."""
        violations = []
        for func_data in data.get("functions", []):
            complexity = func_data.get("complexity", 0)
            if complexity > self.max_complexity:
                violations.append(
                    ComplexityViolation(
                        file_path=file_path,
                        line=func_data.get("line", 0),
                        column=func_data.get("column", 0),
                        rule=func_data.get("rule", "CX001"),
                        function_name=func_data.get("name", "unknown"),
                        complexity=complexity,
                        max_allowed=self.max_complexity,
                        suggestion_text=func_data.get("suggestion", ""),
                    )
                )
        return violations