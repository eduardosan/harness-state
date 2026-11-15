"""Módulo de Coleta de Artefatos, Diffs e Telemetria do Cross-Repo Gate."""

import base64
import os
import re
import subprocess
import sys
from pathlib import Path


def execute_gh_command(args: list[str]) -> subprocess.CompletedProcess:
    """Executa um comando gh CLI injetando token caso presente no ambiente.

    Args:
        args: Argumentos da linha de comando para o binário gh.

    Returns:
        subprocess.CompletedProcess com retorno e saídas do comando.
    """
    env = os.environ.copy()
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def fetch_file_content_from_repo(repo: str, fpath: str) -> str:
    """Busca o conteúdo decodificado de um arquivo via GitHub API.

    Args:
        repo: Nome do repositório (ex: org/repo).
        fpath: Caminho relativo do arquivo no repositório.

    Returns:
        Conteúdo em texto do arquivo decodificado, ou string vazia se indisponível.
    """
    cmd = ["api", f"repos/{repo}/contents/{fpath}", "--jq", ".content"]
    res = execute_gh_command(cmd)
    if res.returncode == 0 and res.stdout.strip():
        try:
            b64_str = res.stdout.strip().replace("\n", "")
            return base64.b64decode(b64_str).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
    return ""


def enrich_patch_with_source_code(
    repos: set[str],
    spec_file: Path | None,
    diffs_out: Path,
) -> None:
    """Anexa código implementado quando o diff contiver apenas markdown.

    Args:
        repos: Conjunto de repositórios envolvidos.
        spec_file: Caminho do arquivo spec.md para introspecção.
        diffs_out: Arquivo de patch de saída.
    """
    spec_text = (
        spec_file.read_text(encoding="utf-8")
        if spec_file and spec_file.is_file()
        else ""
    )
    pattern = r"[\`\s]([a-zA-Z0-9_\-\./]+\.(?:py|go|ts|js))[\`\s]"
    mentioned_files = set(re.findall(pattern, spec_text))

    enrichment_blocks: list[str] = []
    for repo in sorted(repos):
        for fpath in sorted(mentioned_files):
            code = fetch_file_content_from_repo(repo, fpath)
            if code:
                header = f"\n=== CODIGO FONTE IMPLEMENTADO: {repo}/{fpath} ===\n"
                enrichment_blocks.append(f"{header}{code}\n")

    if enrichment_blocks:
        with open(diffs_out, "a", encoding="utf-8") as file_handle:
            file_handle.writelines(enrichment_blocks)


def collect_diffs(
    tasks: list[tuple[str, int, str]],
    spec_file: Path | None,
    diffs_out: Path,
) -> Path:
    """Coleta os diffs consolidados dos PRs envolvidos e enriquece com código-fonte.

    Args:
        tasks: Lista de tuplas (repositorio, pr_number, task_id).
        spec_file: Arquivo spec.md para enriquecimento de código fonte.
        diffs_out: Caminho do arquivo de patch consolidado.

    Returns:
        Caminho do arquivo gravado.
    """
    diffs_out.parent.mkdir(parents=True, exist_ok=True)
    all_chunks: list[str] = []
    repos: set[str] = set()

    for repo, pr_num, _ in tasks:
        repos.add(repo)
        print(
            f"[Collector] Baixando diff do PR #{pr_num} em {repo}...",
            file=sys.stderr,
        )
        res = execute_gh_command(["pr", "diff", str(pr_num), "--repo", repo])
        all_chunks.append(f"=== REPOSITORIO: {repo} (PR #{pr_num}) ===\n")
        if res.returncode == 0:
            all_chunks.append(res.stdout)
        else:
            all_chunks.append(
                f"# Erro ao coletar diff: {res.stderr.strip() or 'Falha desconhecida'}\n"
            )

    diffs_out.write_text("\n".join(all_chunks), encoding="utf-8")
    enrich_patch_with_source_code(repos, spec_file, diffs_out)
    return diffs_out
