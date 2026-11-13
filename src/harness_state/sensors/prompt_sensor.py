"""Sensor de validação de prompts e diretrizes de engenharia (SPEC-PROMPT-01).

Verifica se prompts, templates e instruções seguem as diretrizes de engenharia
do ecossistema Harness (TDD, docstrings, estilo, arquitetura).
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Regras de validação de prompts
PROMPT_RULES = {
    "PROMPT001": {
        "pattern": r"(?i)write\s+tests?\s+first|TDD\s+first|test.?first",
        "message": "Prompt deve mencionar TDD (escrever testes primeiro).",
        "severity": "warning",
    },
    "PROMPT002": {
        "pattern": r"(?i)business\s+rule:",
        "message": "Docstrings de testes devem começar com 'Business Rule:'.",
        "severity": "error",
    },
    "PROMPT003": {
        "pattern": r"(?i)nested\s+function|def\s+\w+\s*\([^)]*\):\s*\n\s+def\s+\w+",
        "message": "Não defina funções aninhadas (exceto decoradores simples com functools.wraps).",
        "severity": "error",
    },
    "PROMPT004": {
        "pattern": r"(?i)try:.*\n\s*except:|except\s*:",
        "message": "Não use try-except genérico. Capture exceções específicas.",
        "severity": "error",
    },
    "PROMPT005": {
        "pattern": r"(?i)if\s+__name__\s*==\s*['\"]__main__['\"]",
        "message": "Evite blocos __main__ em bibliotecas; use entry points.",
        "severity": "warning",
    },
    "PROMPT006": {
        "pattern": r"(?i)_\w+\s*=",
        "message": "Não use prefixo '_' em variáveis de módulo (PYF007).",
        "severity": "error",
    },
    "PROMPT007": {
        "pattern": r"class\s+\w+\s*\(\s*(dict|list|set)\s*\)",
        "message": "Não herde diretamente de dict/list/set; use UserDict/UserList/UserSet (PYF002).",
        "severity": "error",
    },
    "PROMPT008": {
        "pattern": r"raise\s+TypeError\s*(?:\(|\[)",
        "message": "Não levante TypeError em operadores aritméticos/comparação; retorne NotImplemented (PYF003).",
        "severity": "error",
    },
}


@dataclass(slots=True)
class PromptViolation:
    """Violação de diretriz de prompt/engenharia.

    Attributes:
        file_path: Caminho do arquivo analisado.
        line_number: Linha onde a violação foi detectada.
        col_number: Coluna aproximada da violação.
        code: Código identificador da regra (PROMPT001, PROMPT002, etc.).
        message: Mensagem explicativa da violação.
        severity: Severidade (error, warning).
    """

    file_path: Path
    line_number: int
    col_number: int
    code: str
    message: str
    severity: str = "error"

    def format_output(self) -> str:
        """Formata a violação no padrão esperado pelos sensores do harness."""
        return (
            f"{self.file_path}:{self.line_number}:{self.col_number}: "
            f"{self.code} {self.message}"
        )


class PromptSensor:
    """Sensor de validação de prompts e diretrizes de engenharia."""

    def __init__(
        self,
        root_dir: Path,
        custom_rules: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """Inicializa o sensor.

        Args:
            root_dir: Diretório raiz a partir de onde os arquivos serão buscados.
            custom_rules: Regras customizadas adicionais (merge com PROMPT_RULES).
        """
        self.root_dir = root_dir.resolve()
        self.rules = PROMPT_RULES.copy()
        if custom_rules:
            self.rules.update(custom_rules)

    def scan_file(self, file_path: Path) -> list:
        """Escaneia um único arquivo em busca de violações de prompt."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            return []

        violations = []
        for rule_code, rule in self.rules.items():
            pattern = re.compile(rule["pattern"], re.MULTILINE)
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                col_num = match.start() - content.rfind("\n", 0, match.start()) + 1
                violations.append(
                    type(
                        "PromptViolation",
                        (),
                        {
                            "file_path": file_path,
                            "line_number": line_num,
                            "col_number": col_num,
                            "code": rule_code,
                            "message": rule["message"],
                            "severity": rule.get("severity", "error"),
                            "format_output": lambda self: f"{self.file_path}:{self.line_number}:{self.col_number}: {self.code} {self.message}",
                        },
                    )(
                        file_path=file_path,
                        line_number=line_num,
                        col_number=col_num,
                        code=rule_code,
                        message=rule["message"],
                        severity=rule.get("severity", "error"),
                    )
                )
        return violations

    def scan_directory(self, directory: Path | None = None) -> list:
        """Escaneia um diretório recursivamente."""
        target = directory or Path.cwd()
        violations = []
        for file_path in target.rglob("*"):
            if file_path.is_file() and file_path.suffix in {".md", ".py", ".yaml", ".yml", ".txt", ".toml"}:
                violations.extend(self.scan_file(file_path))
        return violations