"""Sensor de CI/CD para validação de pipelines (SPEC-CICD)."""

import re
from pathlib import Path

import yaml

from harness_state.models import CICDViolation

BUSINESS_RULE_PATTERN = re.compile(r"#\s*Business\s+Rule\s*:", re.IGNORECASE)
SILENT_FAILURE_PATTERN = re.compile(r"\|\|\s*(true|:|echo\s+)", re.IGNORECASE)
CONTINUE_ON_ERROR_PATTERN = re.compile(
    r"^\s*continue-on-error\s*:\s*true", re.IGNORECASE
)
SHELL_MULTILINE_START_PATTERN = re.compile(
    r"^\s*(?:-\s*)?(?:run|args)\s*:\s*(?:[|>]-?|\[\s*'-c'\s*,\s*\|)",
    re.IGNORECASE,
)
SET_E_PATTERN = re.compile(r"\bset\s+-[a-zA-Z]*e[a-zA-Z]*\b")


class CICDValidator:
    """Validador estático de regras de fail-fast e integridade em CI/CD."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = root_dir.resolve()
        self.violations: list[CICDViolation] = []

    def find_target_files(self) -> list[Path]:
        """Localiza todos os arquivos de GitHub Actions e Cloud Build no projeto."""
        files = []
        github_workflows = self.root_dir / ".github" / "workflows"
        if github_workflows.is_dir():
            for pattern in ("*.yml", "*.yaml"):
                files.extend(github_workflows.glob(pattern))

        for pattern in ("cloudbuild*.yaml", "cloudbuild*.yml"):
            files.extend(self.root_dir.glob(pattern))
            files.extend(self.root_dir.rglob(pattern))

        return files

    def run(self) -> int:
        """Executa a validação completa e retorna código de saída."""
        self.violations = []
        for file_path in self.find_target_files():
            self._validate_file(file_path)
        for violation in self.violations:
            print(violation.format_output())
        return 1 if self.violations else 0

    def _validate_file(self, file_path: Path) -> None:
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            self._add_violation(file_path, 1, 1, "CICD000", "Erro de sintaxe YAML")
            return

        try:
            yaml.safe_load(content)
        except yaml.YAMLError as exc:
            self._add_violation(file_path, 1, 1, "CICD000", f"Erro de sintaxe YAML: {exc}")
            return

        lines = content.splitlines()
        in_run_step = False
        run_indent = 0
        multiline_active = False

        for idx, line in enumerate(lines, start=1):
            # Detecta início de step com run multiline
            if re.compile(
                r"^\s*(?:-\s*)?(?:run|args)\s*:\s*(?:[|>]-?|\[\s*'-c'\s*,\s*\|)",
                re.IGNORECASE,
            ).search(line.lstrip()):
                # CICD003: Shell multiline sem fail-fast
                # Verifica se as próximas linhas (o script) têm set -e
                # As linhas do script começam na linha atual (idx), não na próxima
                script_lines = lines[idx:idx+5] if idx + 5 < len(lines) else lines[idx:]
                has_set_e = any(re.search(r"\bset\s+-[a-zA-Z]*e[a-zA-Z]*\b", l) for l in script_lines)
                if not has_set_e:
                    self._add_violation(
                        file_path, idx, 1, "CICD003",
                        "Shell multiline sem fail-fast (set -e ou set -eo pipefail). "
                        "Adicione 'set -e' ou 'set -eo pipefail' no início do script."
                    )

                in_run_step = True
                run_indent = len(line) - len(line.lstrip())
                multiline_active = True
                continue

            if in_run_step:
                if multiline_active and len(line) - len(line.lstrip()) <= run_indent and line.lstrip():
                    in_run_step = False
                    multiline_active = False
                elif multiline_active:
                    if re.search(r"\bset\s+-[a-zA-Z]*e[a-zA-Z]*\b", line.lstrip()):
                        multiline_active = False

            # CICD001: Silent failure (|| true / || :)
            if re.compile(r"\|\|\s*(true|:|echo\s+)", re.IGNORECASE).search(line):
                prev_line = lines[idx - 2] if idx > 1 else ""
                if not re.compile(r"#\s*Business\s+Rule\s*:", re.IGNORECASE).search(lines[idx - 2] if idx > 1 else "") and not re.compile(r"#\s*Business\s+Rule\s*:", re.IGNORECASE).search(line):
                    self._add_violation(
                        file_path, idx, 1, "CICD001",
                        "Mascaramento silencioso de erro (|| true/|| :). "
                        "Adicione '# Business Rule:' na linha anterior ou na mesma linha."
                    )

            # CICD002: continue-on-error: true sem justificativa
            if re.compile(r"continue-on-error\s*:\s*true", re.IGNORECASE).search(line):
                prev_line = lines[idx - 2] if idx > 1 else ""
                if not re.compile(r"#\s*Business\s+Rule\s*:", re.IGNORECASE).search(prev_line) and not re.compile(r"#\s*Business\s+Rule\s*:", re.IGNORECASE).search(line):
                    self._add_violation(
                        file_path, idx, 1, "CICD002",
                        "Uso de 'continue-on-error: true' sem justificativa de negócio. "
                        "Adicione '# Business Rule:' na linha anterior ou na mesma linha."
                    )

            # CICD003: Shell multiline sem fail-fast (duplicate removed)

    def _add_violation(
        self,
        file_path: Path,
        line_number: int,
        col_number: int,
        code: str,
        message: str,
    ) -> None:
        self.violations.append(
            CICDViolation(
                file_path=file_path,
                line_number=line_number,
                col_number=col_number,
                code=code,
                message=message,
            )
        )