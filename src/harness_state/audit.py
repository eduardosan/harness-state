"""Módulo de Auditoria do Harness (SPEC-009E e §7 SPEC-009).

Fornece validação automatizada de integridade, mascaramento de dados sensíveis
(`mask-sensitive-data`) e conformidade de arquivos versionados.
"""

import re
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".mk", ".json", ".sh"}

FORBIDDEN_INFRA_PATTERNS = (
    re.compile(r"\b192\.168\.20\.5\b"),
    re.compile(r"\b192\.168\.0\.200\b"),
    re.compile(r"\bpve2\.for\.mat\.br\b"),
    re.compile(r"redis://[^\"\s]*192\.168\.\d{1,3}\.\d{1,3}"),
    re.compile(r"\bghs_[a-zA-Z0-9]{20,}\b"),
    re.compile(r"\bghp_[a-zA-Z0-9]{20,}\b"),
)


def list_tracked_text_files(project_root: Path) -> list[Path]:
    """Lista os arquivos rastreados pelo git elegíveis para inspeção de texto.

    Args:
        project_root: Diretório raiz do repositório git.

    Returns:
        Lista de caminhos absolutos dos arquivos elegíveis.
    """
    proc = subprocess.run(
        ["git", "ls-files"],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    tracked_files: list[Path] = []
    for line in proc.stdout.splitlines():
        rel_path = line.strip()
        if not rel_path:
            continue
        file_path = project_root / rel_path
        if file_path.suffix in TEXT_SUFFIXES or file_path.name in {
            "Makefile",
            ".gitignore",
            "Dockerfile",
        }:
            tracked_files.append(file_path)

    return tracked_files


def audit_sensitive_data(project_root: Path) -> list[str]:
    """Executa a validação mask-sensitive-data em todos os arquivos versionados.

    Verifica se IPs reais de servidores, tokens ou hostnames internos vazaram
    na documentação versionada (§7 da SPEC-009).

    Args:
        project_root: Raiz do repositório a ser auditado.

    Returns:
        Lista de violações encontradas formatadas como 'arquivo: padrão'.
    """
    offenders: list[str] = []
    files_to_check = list_tracked_text_files(project_root)

    for file_path in files_to_check:
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for pattern in FORBIDDEN_INFRA_PATTERNS:
            match = pattern.search(content)
            if match:
                try:
                    rel = file_path.relative_to(project_root)
                except ValueError:
                    rel = file_path
                offenders.append(f"{rel}: {match.group(0)}")

    return offenders
