"""Guard de sanitização (SPEC-009 §7): nenhum valor real de infra em repo público.

O harness-state é publicado sob AGPL; a regra de ouro da spec exige que
documentação e código versionados usem placeholders (`{{SERVER_IP}}`,
`<INTERNAL_HOST>`, TEST-NET) — valores reais vivem apenas em arquivos
gitignored (ex.: `local.mk`).
"""

import re
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {".md", ".py", ".toml", ".yml", ".yaml", ".mk"}

FORBIDDEN_INFRA_PATTERNS = (
    re.compile(r"\b192\.168\.20\.5\b"),
    re.compile(r"\b192\.168\.0\.200\b"),
    re.compile(r"\bpve2\.for\.mat\.br\b"),
    re.compile(r"redis://[^\"\s]*192\.168\.\d{1,3}\.\d{1,3}"),
)


def tracked_text_files() -> list[Path]:
    """Lista arquivos versionados pelo git com sufixo de texto.

    Returns:
        Caminhos relativos à raiz do repositório.
    """
    root = Path(__file__).resolve().parents[2]
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [
        root / line
        for line in out.stdout.splitlines()
        if Path(line).suffix in TEXT_SUFFIXES
        or Path(line).name in {"Makefile", ".gitignore"}
    ]


def test_repos_versionados_nao_contem_ips_u_hosts_reais_de_infra() -> None:
    """Business Rule: nenhum arquivo versionado do pacote público expõe
    IPs/hosts reais da infraestrutura (SPEC-009 §7)."""
    offenders: list[str] = []
    for path in tracked_text_files():
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for pattern in FORBIDDEN_INFRA_PATTERNS:
            if pattern.search(content):
                rel = path.relative_to(path.parents[2])
                offenders.append(f"{rel}: {pattern.pattern}")
    assert offenders == [], (
        "valores reais vazaram no repo público:\n" + "\n".join(offenders)
    )


def test_local_mk_nao_e_versionado_e_gitignore_o_protege() -> None:
    """Business Rule: o arquivo com credenciais/túnel reais do desenvolvedor
    (`local.mk`) fica fora do git e o `.gitignore` o protege por padrão."""
    root = Path(__file__).resolve().parents[2]

    listed = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "local.mk"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert listed.returncode != 0, "local.mk voltou a ser versionado!"

    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "local.mk" in gitignore
    assert (root / "local.mk.example").is_file()
