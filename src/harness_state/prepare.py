"""CLI do job prepare no hub de orquestração."""

import argparse
import json
import re
import sys
from pathlib import Path

from harness_state.allowlist import RepoNotAllowedError, get_repo_config
from harness_state.prompt import (
    Issue,
    IssueTooLargeError,
    IssueTooVagueError,
    UntrustedAuthorError,
    build_task_prompt,
    ensure_trusted,
)


def write_github_output(output_path: Path | None, key: str, value: str) -> None:
    """Escreve pares chave=valor no arquivo de output do GitHub Actions.

    Args:
        output_path: Caminho para GITHUB_OUTPUT.
        key: Nome da variável de saída.
        value: Valor atribuído à variável.
    """
    if output_path:
        with open(output_path, "a", encoding="utf-8") as file:
            file.write(f"{key}={value}\n")


def extract_spec_metadata_from_issue(issue: Issue) -> tuple[str, str]:
    """Extrai spec_id e task_id a partir do título e corpo da issue do GitHub.

    Args:
        issue: Instância da issue com título e corpo.

    Returns:
        Tupla (spec_id, task_id) encontrados ou strings vazias caso ausentes.
    """
    spec_id = ""
    task_id = ""

    match_title = re.search(r"\[(SPEC-[a-zA-Z0-9_\-]+)\]", issue.title)
    if match_title:
        spec_id = match_title.group(1).strip()

    if not spec_id:
        match_body_spec = re.search(
            r"(?:Spec ID|ID da Spec):\s*`?([a-zA-Z0-9_\-]+)`?",
            issue.body,
            re.IGNORECASE,
        )
        if match_body_spec:
            spec_id = match_body_spec.group(1).strip()

    match_task = re.search(
        r"subtarefa\s*`?([a-zA-Z0-9_\-]+)`?",
        issue.body,
        re.IGNORECASE,
    )
    if match_task:
        task_id = match_task.group(1).strip()
    else:
        match_task_alt = re.search(
            r"(?:Task ID|ID da Tarefa):\s*`?([a-zA-Z0-9_\-]+)`?",
            issue.body,
            re.IGNORECASE,
        )
        if match_task_alt:
            task_id = match_task_alt.group(1).strip()

    return spec_id, task_id


def parse_args(args: list[str]) -> argparse.Namespace:
    """Realiza o parsing dos argumentos de linha de comando.

    Args:
        args: Lista de argumentos passados para a execução.

    Returns:
        Namespace com os argumentos parseados.
    """
    parser = argparse.ArgumentParser(description="Prepara e valida a tarefa do agente.")
    parser.add_argument(
        "--allowlist", required=True, type=Path, help="Caminho para repos.yml"
    )
    parser.add_argument(
        "--repo", required=True, type=str, help="Identificador do repositório alvo"
    )
    parser.add_argument(
        "--issue-file", required=True, type=Path, help="Arquivo JSON da issue"
    )
    parser.add_argument(
        "--out-dir", required=True, type=Path, help="Diretório de saída do prompt"
    )
    parser.add_argument(
        "--github-output",
        default=None,
        type=Path,
        help="Caminho do arquivo GITHUB_OUTPUT do runner",
    )
    parser.add_argument(
        "--spec-id",
        default="",
        type=str,
        help="Identificador explícito da spec",
    )
    parser.add_argument(
        "--task-id",
        default="",
        type=str,
        help="Identificador explícito da subtarefa",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do script de preparação.

    Args:
        argv: Argumentos explícitos de linha de comando ou None para sys.argv[1:].

    Returns:
        Código de saída do processo (0 para sucesso/rejeição, 3 para falha).
    """
    args = parse_args(argv if argv is not None else sys.argv[1:])

    # 1. Validação da allowlist de repositórios
    try:
        repo_config = get_repo_config(args.allowlist, args.repo)
    except RepoNotAllowedError as error:
        print(f"Erro de segurança: {error}", file=sys.stderr)
        write_github_output(args.github_output, "proceed", "false")
        write_github_output(args.github_output, "reject_message", str(error))
        return 3

    # 2. Leitura da Issue
    with open(args.issue_file, "r", encoding="utf-8") as file:
        issue_data = json.load(file)

    issue = Issue(
        number=issue_data.get("number", 0),
        title=issue_data.get("title", ""),
        body=issue_data.get("body", ""),
        author_association=issue_data.get("author_association", "NONE"),
        author_login=(issue_data.get("user") or {}).get("login", ""),
    )

    # 3. Validação do autor
    try:
        ensure_trusted(issue)
    except UntrustedAuthorError as error:
        print(f"Autor não autorizado: {error}")
        write_github_output(args.github_output, "proceed", "false")
        msg = f"Autor com associação '{issue.author_association}' não é confiável."
        write_github_output(args.github_output, "reject_message", msg)
        return 0

    # 4. Construção do prompt da tarefa
    try:
        prompt_content = build_task_prompt(issue)
    except (IssueTooLargeError, IssueTooVagueError) as error:
        print(f"Issue inadequada para execução automática: {error}")
        write_github_output(args.github_output, "proceed", "false")
        msg = "Tarefa muito vaga ou grande demais. Favor dividir em tarefas menores."
        write_github_output(args.github_output, "reject_message", msg)
        return 0

    # 5. Gravação de artefatos e sucesso
    args.out_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = args.out_dir / "prompt.md"
    prompt_file.write_text(prompt_content, encoding="utf-8")

    spec_id = args.spec_id.strip() if args.spec_id else ""
    task_id = args.task_id.strip() if args.task_id else ""
    if not spec_id or not task_id:
        extracted_spec, extracted_task = extract_spec_metadata_from_issue(issue)
        if not spec_id:
            spec_id = extracted_spec
        if not task_id:
            task_id = extracted_task

    is_bug = "<!-- flywheel:bug-plan:v1 -->" in issue.body or "[Bug]" in issue.title
    write_github_output(args.github_output, "proceed", "true")
    write_github_output(args.github_output, "is_bug", "true" if is_bug else "false")
    write_github_output(args.github_output, "language", repo_config.language)
    write_github_output(args.github_output, "base_branch", repo_config.base_branch)
    write_github_output(args.github_output, "spec_id", spec_id)
    write_github_output(args.github_output, "task_id", task_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
