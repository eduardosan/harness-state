"""Sensor determinístico de integridade e fail-fast para CI/CD (SPEC-CICD-01).

Inspeciona arquivos do GitHub Actions (.github/workflows/*.yml, action.yml) e
passos do Google Cloud Build (cloudbuild*.yaml) garantindo que:

* ``CICD000``: Arquivo YAML com erro de sintaxe.
* ``CICD001``: Mascaramento de erro (`|| true`, `|| :`) sem `# Business Rule:`.
* ``CICD002``: Uso de `continue-on-error: true` sem justificativa `# Business Rule:`.
* ``CICD003``: Shell multiline sem fail-fast (`set -e` ou `set -eo pipefail`).

A saída segue o formato padronizado (arquivo:linha:coluna: CODIGO mensagem)
para consumo direto pelo format_feedback.sh.
"""

import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

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


@dataclass(slots=True)
class CICDViolation:
    """Representa uma violação de integridade em arquivo de CI/CD.

    Attributes:
        file_path: Caminho do arquivo analisado.
        line_number: Linha onde a violação foi detectada.
        col_number: Coluna aproximada da violação.
        code: Código identificador da regra (CICD001, CICD002, etc.).
        message: Mensagem explicativa da violação.
    """

    file_path: Path
    line_number: int
    col_number: int
    code: str
    message: str

    def format_output(self) -> str:
        """Formata a violação no padrão esperado pelos sensores do harness.

        Returns:
            String no formato 'arquivo:linha:coluna: CODIGO mensagem'.
        """
        return (
            f"{self.file_path}:{self.line_number}:{self.col_number}: "
            f"{self.code} {self.message}"
        )


class CICDValidator:
    """Validador estático de regras de fail-fast e integridade em CI/CD."""

    def __init__(self, root_dir: Path) -> None:
        """Inicializa o validador com o diretório raiz do projeto.

        Args:
            root_dir: Diretório raiz a partir de onde os arquivos serão buscados.
        """
        self.root_dir = root_dir.resolve()
        self.violations: list[CICDViolation] = []

    def find_target_files(self) -> list[Path]:
        """Localiza todos os arquivos de GitHub Actions e Cloud Build no projeto.

        Returns:
            Lista de caminhos de arquivos de CI/CD encontrados.
        """
        targets: list[Path] = []
        workflows_dir = self.root_dir / ".github" / "workflows"
        if workflows_dir.is_dir():
            targets.extend(workflows_dir.glob("*.y*ml"))

        for action_file in self.root_dir.glob("**/action.y*ml"):
            if ".venv" not in str(action_file) and "node_modules" not in str(
                action_file
            ):
                targets.append(action_file)

        for cb_file in self.root_dir.glob("**/cloudbuild*.y*ml"):
            if ".venv" not in str(cb_file) and "node_modules" not in str(cb_file):
                targets.append(cb_file)

        return sorted(set(targets))

    def validate_file(self, file_path: Path) -> None:
        """Executa validação sintática e semântica em um arquivo de CI/CD.

        Args:
            file_path: Arquivo YAML a ser validado.
        """
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as err:
            self.violations.append(
                CICDViolation(
                    file_path=file_path,
                    line_number=1,
                    col_number=1,
                    code="CICD000",
                    message=f"Falha ao ler arquivo: {err}",
                )
            )
            return

        try:
            yaml.safe_load(content)
        except yaml.YAMLError as err:
            line = 1
            col = 1
            problem_mark = getattr(err, "problem_mark", None)
            if problem_mark is not None:
                line = problem_mark.line + 1
                col = problem_mark.column + 1
            self.violations.append(
                CICDViolation(
                    file_path=file_path,
                    line_number=line,
                    col_number=col,
                    code="CICD000",
                    message=f"Erro de sintaxe YAML: {err}",
                )
            )
            return

        lines = content.splitlines()
        self.check_line_rules(file_path, lines)

    def _has_business_rule_justification(
        self, lines: list[str], idx: int, line: str
    ) -> bool:
        """Verifica se a linha ou a linha imediatamente anterior declara Business Rule.

        Args:
            lines: Lista completa de linhas do arquivo.
            idx: Índice base-1 da linha atual.
            line: Conteúdo textual da linha atual.

        Returns:
            True se houver justificativa `# Business Rule:`.
        """
        return bool(
            BUSINESS_RULE_PATTERN.search(line)
            or (idx > 1 and BUSINESS_RULE_PATTERN.search(lines[idx - 2]))
        )

    def _check_single_line_patterns(
        self, file_path: Path, lines: list[str], idx: int, line: str
    ) -> None:
        """Verifica mascaramento silencioso (CICD001) e continue-on-error (CICD002).

        Args:
            file_path: Caminho do arquivo sendo analisado.
            lines: Lista completa de linhas do arquivo.
            idx: Índice base-1 da linha atual.
            line: Conteúdo da linha atual.
        """
        if SILENT_FAILURE_PATTERN.search(
            line
        ) and not self._has_business_rule_justification(lines, idx, line):
            self.violations.append(
                CICDViolation(
                    file_path=file_path,
                    line_number=idx,
                    col_number=1,
                    code="CICD001",
                    message=(
                        "Mascaramento silencioso de erro detectado. "
                        "O pipeline deve falhar imediatamente; "
                        "supressão de erro só é permitida mediante "
                        "anotação explícita de '# Business Rule: <motivo>'."
                    ),
                )
            )

        if CONTINUE_ON_ERROR_PATTERN.search(
            line
        ) and not self._has_business_rule_justification(lines, idx, line):
            self.violations.append(
                CICDViolation(
                    file_path=file_path,
                    line_number=idx,
                    col_number=1,
                    code="CICD002",
                    message=(
                        "continue-on-error: true detectado sem justificativa. "
                        "O pipeline deve falhar sempre que der um erro, exceto "
                        "se decorrer de regra explícita de negócio "
                        "(documentada com '# Business Rule:')."
                    ),
                )
            )

    def _append_missing_set_e_violation(
        self, file_path: Path, script_start_line: int
    ) -> None:
        """Registra violação CICD003 para bloco multiline sem `set -e`.

        Args:
            file_path: Caminho do arquivo analisado.
            script_start_line: Linha de início do bloco multiline.
        """
        self.violations.append(
            CICDViolation(
                file_path=file_path,
                line_number=script_start_line,
                col_number=1,
                code="CICD003",
                message=(
                    "Script shell multiline em CI/CD deve iniciar "
                    "com fail-fast ('set -e' ou 'set -eo pipefail') "
                    "para abortar imediatamente a qualquer falha."
                ),
            )
        )

    def _update_multiline_script_state(
        self,
        file_path: Path,
        line: str,
        stripped: str,
        in_multiline_script: bool,
        script_has_set_e: bool,
        script_start_line: int,
        script_indent: int,
    ) -> tuple[bool, bool]:
        """Atualiza o estado do bloco shell multiline na linha atual.

        Args:
            file_path: Caminho do arquivo analisado.
            line: Linha de texto atual.
            stripped: Linha sem espaços nas extremidades.
            in_multiline_script: Se estamos dentro de um bloco multiline.
            script_has_set_e: Se `set -e` já foi encontrado no bloco.
            script_start_line: Linha de início do bloco.
            script_indent: Recuo do cabeçalho do bloco.

        Returns:
            Tupla `(in_multiline_script, script_has_set_e)`.
        """
        if not in_multiline_script:
            return False, script_has_set_e

        current_indent = len(line) - len(line.lstrip())
        if stripped and current_indent <= script_indent:
            if not script_has_set_e:
                self._append_missing_set_e_violation(file_path, script_start_line)
            return False, script_has_set_e

        if SET_E_PATTERN.search(line):
            return True, True
        return True, script_has_set_e

    def check_line_rules(self, file_path: Path, lines: list[str]) -> None:
        """Verifica regras de fail-fast linha a linha no arquivo de CI/CD.

        Args:
            file_path: Caminho do arquivo sendo analisado.
            lines: Linhas de texto do arquivo.
        """
        in_multiline_script = False
        script_has_set_e = False
        script_start_line = 1
        script_indent = 0

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            self._check_single_line_patterns(file_path, lines, idx, line)

            in_multiline_script, script_has_set_e = self._update_multiline_script_state(
                file_path=file_path,
                line=line,
                stripped=stripped,
                in_multiline_script=in_multiline_script,
                script_has_set_e=script_has_set_e,
                script_start_line=script_start_line,
                script_indent=script_indent,
            )

            if SHELL_MULTILINE_START_PATTERN.search(line) and not in_multiline_script:
                in_multiline_script = True
                script_has_set_e = False
                script_start_line = idx
                script_indent = len(line) - len(line.lstrip())

        if in_multiline_script and not script_has_set_e:
            self._append_missing_set_e_violation(file_path, script_start_line)

    def run(self) -> int:
        """Executa a validação em todos os arquivos de CI/CD encontrados.

        Returns:
            0 se não houver violações; 1 caso contrário.
        """
        target_files = self.find_target_files()
        for f in target_files:
            self.validate_file(f)

        for v in self.violations:
            print(v.format_output(), file=sys.stderr)

        return 1 if self.violations else 0


def main() -> None:
    """Ponto de entrada do sensor determinístico de CI/CD."""
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    validator = CICDValidator(root)
    sys.exit(validator.run())


if __name__ == "__main__":
    main()
