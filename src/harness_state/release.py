"""Utilitário de cálculo SemVer e automação de tags/releases."""

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SEMVER_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(slots=True, order=True)
class SemVer:
    """Representação estruturada de uma versão SemVer (`major.minor.patch`).

    Attributes:
        major: Versão principal (breaking changes).
        minor: Versão secundária (novas funcionalidades retrocompatíveis).
        patch: Versão de correção ou manutenção.
    """

    major: int
    minor: int
    patch: int

    def bump(self, part: str) -> "SemVer":
        """Incrementa a parte especificada da versão SemVer.

        Args:
            part: Parte a incrementar ('major', 'minor' ou 'patch').

        Returns:
            Nova instância de `SemVer` incrementada.
        """
        normalized = part.strip().lower()
        if normalized == "major":
            return SemVer(self.major + 1, 0, 0)
        if normalized == "minor":
            return SemVer(self.major, self.minor + 1, 0)
        return SemVer(self.major, self.minor, self.patch + 1)

    def to_tag(self) -> str:
        """Formata a versão como tag Git canônica com prefixo `v`.

        Returns:
            String no formato `vX.Y.Z`.
        """
        return f"v{self.major}.{self.minor}.{self.patch}"

    def to_version(self) -> str:
        """Formata a versão pura sem o prefixo `v`.

        Returns:
            String no formato `X.Y.Z`.
        """
        return f"{self.major}.{self.minor}.{self.patch}"


def parse_semver(raw_tag: str | None, fallback: str = "0.1.0") -> SemVer:
    """Converte uma tag ou string de versão em `SemVer`.

    Args:
        raw_tag: Tag existente (ex: `v0.1.0` ou `0.1.0`).
        fallback: Versão base caso `raw_tag` seja vazia ou inválida.

    Returns:
        Instância de `SemVer`.
    """
    candidate = (raw_tag or "").strip()
    match = SEMVER_PATTERN.match(candidate)
    if not match:
        match = SEMVER_PATTERN.match(fallback.strip())
    if not match:
        return SemVer(0, 1, 0)
    return SemVer(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
    )


def infer_bump_part(
    pr_title: str = "",
    labels: list[str] | None = None,
    explicit_bump: str = "",
) -> str:
    """Determina o tipo de incremento SemVer a partir do título e labels do PR.

    Args:
        pr_title: Título do Pull Request (Conventional Commits).
        labels: Lista opcional de labels associadas ao PR.
        explicit_bump: Incremento explícito ('major', 'minor', 'patch').

    Returns:
        String indicando 'major', 'minor' ou 'patch'.
    """
    clean_explicit = explicit_bump.strip().lower()
    if clean_explicit in ("major", "minor", "patch"):
        return clean_explicit

    normalized_labels = {lbl.strip().lower() for lbl in (labels or []) if lbl.strip()}
    if normalized_labels & {"major", "breaking", "breaking-change"}:
        return "major"
    if normalized_labels & {"minor", "feature", "enhancement"}:
        return "minor"
    if normalized_labels & {"patch", "bug", "fix", "chore", "docs"}:
        return "patch"

    clean_title = pr_title.strip()
    if "!:" in clean_title or "BREAKING CHANGE" in clean_title.upper():
        return "major"
    if re.match(r"^feat(\([^)]+\))?:", clean_title, flags=re.IGNORECASE):
        return "minor"
    return "patch"


def compute_next_release_tag(
    latest_tag: str | None,
    pr_title: str = "",
    labels: list[str] | None = None,
    explicit_bump: str = "",
) -> tuple[str, str, str]:
    """Calcula a próxima tag e versão SemVer para a release do GitHub.

    Args:
        latest_tag: Última tag SemVer existente no repositório (ou None/vazio).
        pr_title: Título do Pull Request mergeado.
        labels: Lista de labels do Pull Request.
        explicit_bump: Override manual opcional ('major', 'minor', 'patch').

    Returns:
        Tupla `(next_tag, next_version, bump_part)`.
    """
    part = infer_bump_part(
        pr_title=pr_title, labels=labels, explicit_bump=explicit_bump
    )
    if not latest_tag or not latest_tag.strip():
        base = SemVer(0, 1, 0)
        return base.to_tag(), base.to_version(), part

    current = parse_semver(latest_tag)
    next_semver = current.bump(part)
    return next_semver.to_tag(), next_semver.to_version(), part


def get_repo_declared_version(repo_dir: Path) -> str | None:
    """Extrai a versão declarada no arquivo de configuração do repositório.

    Inspeciona `pyproject.toml` (Python) ou `package.json` (Node.js/TS).

    Args:
        repo_dir: Diretório raiz do repositório local.

    Returns:
        Versão declarada (ex: '0.2.0') ou None se não encontrada.
    """
    pyproject_file = repo_dir / "pyproject.toml"
    if pyproject_file.is_file():
        try:
            content = pyproject_file.read_text(encoding="utf-8")
            match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
            if match:
                return match.group(1).strip()
        except OSError:
            pass

    package_json = repo_dir / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "version" in data:
                return str(data["version"]).strip()
        except (OSError, json.JSONDecodeError):
            pass

    return None


def get_repo_latest_release_tag(repo_dir: Path) -> str | None:
    """Obtém a tag SemVer da release mais recente existente no repositório Git.

    Args:
        repo_dir: Diretório raiz do repositório local.

    Returns:
        Tag da última release válida (ex: 'v0.0.17') ou None se não houver tags.
    """
    try:
        proc = subprocess.run(
            ["git", "tag", "-l"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        valid_tags: list[tuple[SemVer, str]] = []
        for line in proc.stdout.splitlines():
            raw_tag = line.strip()
            if not raw_tag:
                continue
            match = SEMVER_PATTERN.match(raw_tag)
            if match:
                semver_obj = SemVer(
                    major=int(match.group(1)),
                    minor=int(match.group(2)),
                    patch=int(match.group(3)),
                )
                valid_tags.append((semver_obj, raw_tag))
        if not valid_tags:
            return None
        valid_tags.sort(key=lambda item: item[0])
        return valid_tags[-1][1]
    except OSError:
        return None


def is_dependency_release_satisfied(
    expected_version: str | None,
    latest_release_tag: str | None,
) -> bool:
    """Verifica se a última release válida do repositório satisfaz a versão esperada.

    Args:
        expected_version: Versão esperada da dependência (ex: '0.2.0').
        latest_release_tag: Tag da última release publicada (ex: 'v0.0.17').

    Returns:
        True se a release publicada for maior ou igual à versão esperada.
    """
    if not expected_version or not expected_version.strip():
        return True
    if not latest_release_tag or not latest_release_tag.strip():
        return False

    expected_semver = parse_semver(expected_version)
    latest_semver = parse_semver(latest_release_tag)
    return latest_semver >= expected_semver


def build_arg_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos CLI do calculador de release.

    Returns:
        Instância configurada de `ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        description="Calcula a próxima tag SemVer para GitHub Releases."
    )
    parser.add_argument(
        "--latest-tag",
        default="",
        help="Última tag SemVer encontrada no git (ex: v0.1.0)",
    )
    parser.add_argument(
        "--pr-title",
        default="",
        help="Título do Pull Request mergeado",
    )
    parser.add_argument(
        "--labels",
        default="",
        help="Labels do PR separadas por vírgula",
    )
    parser.add_argument(
        "--bump",
        default="",
        help="Override explícito de incremento (patch, minor, major)",
    )
    parser.add_argument(
        "--github-output",
        default="",
        help="Caminho do arquivo $GITHUB_OUTPUT para exportar variáveis",
    )
    return parser


def main() -> None:
    """Ponto de entrada CLI para cálculo de versão no workflow de release."""
    parser = build_arg_parser()
    args = parser.parse_args()
    label_list = [item.strip() for item in args.labels.split(",") if item.strip()]

    next_tag, next_version, bump_part = compute_next_release_tag(
        latest_tag=args.latest_tag,
        pr_title=args.pr_title,
        labels=label_list,
        explicit_bump=args.bump,
    )

    if args.github_output:
        with open(args.github_output, "a", encoding="utf-8") as out_handle:
            out_handle.write(f"tag={next_tag}\n")
            out_handle.write(f"version={next_version}\n")
            out_handle.write(f"bump={bump_part}\n")

    print(next_tag)


if __name__ == "__main__":
    main()
