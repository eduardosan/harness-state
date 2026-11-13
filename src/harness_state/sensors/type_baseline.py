"""Baseline de erros do pyright para adoção gradual do modo ``strict``.

O ``pyright`` não possui baseline nativo. Este módulo compara o relatório de
``pyright --outputjson`` com um arquivo versionado no repositório:

* só erros novos bloqueiam o gate (``check``);
* o baseline só pode encolher (``shrink``);
* a geração inicial (``generate``) recusa sobrescrever um baseline existente,
  porque isso poderia ampliar a dívida silenciosamente.

O baseline guarda arquivo, regra e mensagem com contagem de ocorrências, sem o
número da linha, para que edições triviais não quebrem a comparação.
"""

import argparse
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from operator import attrgetter
from pathlib import Path

DiagnosticKey = tuple[str, str, str]

DEFAULT_BASELINE_PATH = Path("pyright-baseline.json")


@dataclass(frozen=True)
class TypeBaselineViolation:
    """Erro de tipo reportado pelo pyright.

    Attributes:
        file: Caminho do arquivo, relativo à raiz do repositório.
        line: Linha do erro, a partir de 1 (0 quando vindo do baseline).
        column: Coluna do erro, a partir de 1 (0 quando vindo do baseline).
        rule: Regra do pyright (ex: ``reportGeneralTypeIssues``).
        message: Mensagem do diagnóstico.
    """

    file: str
    line: int
    column: int
    rule: str
    message: str

    @property
    def key(self) -> DiagnosticKey:
        """Identidade do erro no baseline, independente da posição.

        Returns:
            Tupla ``(arquivo, regra, mensagem)``.
        """
        return (self.file, self.rule, self.message)


@dataclass(frozen=True)
class TypeBaselineComparison:
    """Resultado da comparação entre o relatório atual e o baseline.

    Attributes:
        new: Erros além do que o baseline permite.
        fixed: Quantidade de erros do baseline que não ocorrem mais.
    """

    new: list[TypeBaselineViolation]
    fixed: int


class TypeBaselineSensor:
    """Sensor de baseline de erros do pyright."""

    def __init__(
        self,
        baseline_path: Path = DEFAULT_BASELINE_PATH,
        root_dir: Path | None = None,
    ) -> None:
        """Inicializa o sensor.

        Args:
            baseline_path: Caminho do arquivo baseline versionado.
            root_dir: Raiz do repositório (padrão: cwd).
        """
        self.baseline_path = baseline_path.resolve()
        self.root_dir = (root_dir or Path.cwd()).resolve()

    def load_baseline(self) -> Counter[DiagnosticKey]:
        """Carrega o baseline versionado.

        Returns:
            Counter com chaves (arquivo, regra, mensagem) e contagens.
        """
        if not self.baseline_path.is_file():
            return Counter()

        try:
            data = json.loads(self.baseline_path.read_text(encoding="utf-8"))
            baseline = Counter()
            for entry in data.get("diagnostics", []):
                key = (entry["file"], entry["rule"], entry["message"])
                baseline[key] = entry.get("count", 1)
            return baseline
        except (json.JSONDecodeError, OSError, KeyError):
            return Counter()

    def run_pyright(self) -> list[TypeBaselineViolation]:
        """Executa pyright e retorna lista de diagnósticos.

        Returns:
            Lista de violações de tipo encontradas.
        """
        import subprocess

        try:
            result = subprocess.run(
                ["pyright", "--outputjson"],
                cwd=self.root_dir,
                capture_output=True,
                text=True,
                check=False,
            )
        except (subprocess.SubprocessError, OSError):
            return []

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        violations = []
        for diag in data.get("generalDiagnostics", []):
            file_rel = self._relative_path(diag.get("file", ""))
            violations.append(
                TypeBaselineViolation(
                    file=file_rel,
                    line=diag.get("range", {}).get("start", {}).get("line", 0) + 1,
                    column=diag.get("range", {}).get("start", {}).get("character", 0) + 1,
                    rule=diag.get("rule", ""),
                    message=diag.get("message", ""),
                )
            )
        return violations

    def _relative_path(self, file: str) -> str:
        path = Path(file)
        if path.is_relative_to(self.root_dir):
            return path.relative_to(self.root_dir).as_posix()
        return path.as_posix()

    def check(self) -> tuple[list[TypeBaselineViolation], int]:
        """Compara execução atual com baseline.

        Returns:
            Tupla (novos_erros, erros_corrigidos).
        """
        baseline = self.load_baseline()
        current = self.run_pyright()

        current_counter = Counter(v.key for v in current)

        new_violations = []
        for v in current:
            allowed = baseline.get(v.key, 0)
            if current_counter[v.key] > allowed:
                new_violations.append(v)

        fixed = sum(max(0, baseline[k] - current_counter.get(k, 0)) for k in baseline)

        return new_violations, fixed

    def generate_baseline(self, force: bool = False) -> None:
        """Gera baseline inicial a partir da execução atual.

        Args:
            force: Se False, recusa sobrescrever baseline existente.
        """
        if self.baseline_path.is_file() and not force:
            raise RuntimeError(
                f"Baseline já existe em {self.baseline_path}. Use --force para sobrescrever."
            )

        violations = self.run_pyright()
        counter = Counter(v.key for v in violations)

        data = {
            "version": 1,
            "diagnostics": [
                {"file": f, "rule": r, "message": m, "count": c}
                for (f, r, m), c in counter.items()
            ],
        }

        self.baseline_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def shrink_baseline(self) -> int:
        """Encolhe o baseline removendo entradas que não ocorrem mais.

        Returns:
            Quantidade de entradas removidas.
        """
        baseline = self.load_baseline()
        current = self.run_pyright()
        current_counter = Counter(v.key for v in current)

        keys_to_remove = [k for k in baseline if k not in current_counter]
        for k in keys_to_remove:
            del baseline[k]

        data = {
            "version": 1,
            "diagnostics": [
                {"file": f, "rule": r, "message": m, "count": c}
                for (f, r, m), c in baseline.items()
            ],
        }

        self.baseline_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return len(keys_to_remove)