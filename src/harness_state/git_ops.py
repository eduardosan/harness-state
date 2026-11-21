"""Operações e utilitários Git para o ciclo de vida do Harness SDD."""

import json
import re
import subprocess
from pathlib import Path

from harness_state.labels import ensure_labels_exist

SEMVER_TAG_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+$")


def get_current_branch(repo_dir: Path) -> str | None:
    """Retorna o nome da branch Git atualmente ativa no repositório.

    Args:
        repo_dir: Diretório raiz do repositório local.

    Returns:
        Nome da branch ativa ou None se o diretório não for um repositório Git.
    """
    proc = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    return branch or None


def ensure_working_branch(repo_dir: Path, branch_name: str) -> bool:
    """Garante que o repositório esteja na branch de trabalho especificada.

    Caso o repositório esteja na branch `main` ou em outra branch diferente,
    faz checkout da branch de trabalho. Se a branch ainda não existir, cria-a
    a partir de `origin/main` (ou `main`), protegendo a branch principal.

    Args:
        repo_dir: Diretório raiz do repositório local.
        branch_name: Nome da branch de trabalho desejada (ex: feat/spec-004-crm).

    Returns:
        True se a branch de trabalho estiver ativa, False caso ocorra erro.
    """
    clean_branch = branch_name.strip()
    if not clean_branch:
        return False

    current = get_current_branch(repo_dir)
    if current == clean_branch:
        return True

    # Tenta alternar para a branch se ela já existir localmente
    checkout_proc = subprocess.run(
        ["git", "checkout", clean_branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if checkout_proc.returncode == 0:
        return True

    # Verifica se a branch existe no remoto
    remote_proc = subprocess.run(
        ["git", "checkout", "-b", clean_branch, f"origin/{clean_branch}"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if remote_proc.returncode == 0:
        return True

    # Cria nova branch a partir do estado atual da branch principal
    create_proc = subprocess.run(
        ["git", "checkout", "-b", clean_branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return create_proc.returncode == 0


def sync_repo_release_tags(repo_dir: Path) -> bool:
    """Atualiza as tags de release do repositório a partir do remoto `origin`.

    Permite que o orquestrador detecte novas releases publicadas por esteiras
    de CI/CD remotas logo após a aprovação e merge de Pull Requests.

    Args:
        repo_dir: Diretório raiz do repositório local.

    Returns:
        True se o fetch das tags ocorreu com sucesso, False caso contrário.
    """
    proc = subprocess.run(
        ["git", "fetch", "--tags", "origin"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0


def get_active_pr_info(
    repo_dir: Path, branch_name: str
) -> tuple[int | None, str | None]:
    """Consulta informações de Pull Request existente para a branch via GitHub CLI.

    Args:
        repo_dir: Diretório raiz do repositório local.
        branch_name: Nome da branch de trabalho.

    Returns:
        Tupla contendo `(pr_number, pr_url)` ou `(None, None)` se não houver PR.
    """
    proc = subprocess.run(
        ["gh", "pr", "view", branch_name, "--json", "number,url"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None, None

    try:
        data = json.loads(proc.stdout)
        if isinstance(data, dict):
            num = int(data.get("number", 0)) or None
            url = str(data.get("url", "")) or None
            return num, url
    except (json.JSONDecodeError, ValueError):
        pass

    return None, None


def ensure_pr_linked_to_issue(
    repo_dir: Path,
    pr_number: int,
    issue_number: int,
) -> bool:
    """Garante que o corpo do Pull Request existente contenha 'Closes #{issue_number}'.

    Se o PR já estiver aberto mas seu corpo não referenciar a issue para fechamento
    automático no merge, executa `gh pr edit` adicionando a diretiva 'Closes #N'.

    Args:
        repo_dir: Diretório raiz do repositório local.
        pr_number: Número do Pull Request aberto.
        issue_number: Número da issue a ser vinculada.

    Returns:
        True se o PR já estava vinculado ou foi atualizado com sucesso.
    """
    view_proc = subprocess.run(
        ["gh", "pr", "view", str(pr_number), "--json", "body", "-q", ".body"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if view_proc.returncode != 0:
        return False

    current_body = view_proc.stdout.strip()
    close_pattern = re.compile(
        rf"\b(?:closes|closed|fix|fixes|fixed|resolve|resolves|resolved)\s+#{issue_number}\b",
        re.IGNORECASE,
    )
    if close_pattern.search(current_body):
        return True

    updated_body = f"{current_body}\n\nCloses #{issue_number}\n".strip()
    edit_proc = subprocess.run(
        ["gh", "pr", "edit", str(pr_number), "--body", updated_body],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return edit_proc.returncode == 0


def publish_task_pr(
    repo_dir: Path,
    spec_id: str,
    branch_name: str,
    spec_title: str = "",
    sub_spec_path: str = "",
    issue_number: int | None = None,
) -> tuple[int | None, str | None, str]:
    """Publica a branch e cria Pull Request no repositório spoke via GitHub CLI.

    Executa `git push -u origin <branch>` e, caso ainda não exista PR aberto,
    executa `gh pr create` referenciando formalmente a especificação e issue vinculada.
    Caso o PR já exista, assegura que seu corpo referencie a issue com
    `Closes #{issue_number}`.

    Args:
        repo_dir: Diretório raiz do repositório local.
        spec_id: Identificador da especificação (ex: SPEC-004).
        branch_name: Nome da branch de trabalho da tarefa.
        spec_title: Título descritivo da funcionalidade.
        sub_spec_path: Caminho da especificação vinculada.
        issue_number: Número opcional da issue de rastreamento no GitHub.

    Returns:
        Tupla contendo `(pr_number, pr_url, status_message)`.
    """
    # 1. Faz push da branch para o repositório remoto
    push_proc = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if push_proc.returncode != 0:
        err = push_proc.stderr.strip()
        return None, None, f"Falha no push da branch {branch_name}: {err}"

    target_issue = issue_number
    if target_issue is None:
        active_issue_num, _ = get_active_issue_info(repo_dir, spec_id)
        target_issue = active_issue_num

    # 2. Verifica se o PR já existe
    existing_num, existing_url = get_active_pr_info(repo_dir, branch_name)
    if existing_num is not None:
        if target_issue is not None:
            ensure_pr_linked_to_issue(repo_dir, existing_num, target_issue)
            msg = (
                f"Pull Request #{existing_num} já existente e vinculado à "
                f"issue #{target_issue}: {existing_url}"
            )
            return existing_num, existing_url, msg
        msg = f"Pull Request #{existing_num} já existente: {existing_url}"
        return existing_num, existing_url, msg

    # 3. Cria novo Pull Request no GitHub
    title_text = f"feat: [{spec_id}] {spec_title}".strip()
    body_lines = [
        f"## Implementação da {spec_id}\n",
        "Pull Request gerado e validado deterministamente pelo Harness SDD.\n",
        f"- **Especificação:** `{sub_spec_path or spec_id}`",
        f"- **Branch:** `{branch_name}`",
    ]
    if target_issue is not None:
        body_lines.append(f"- **Issue de Rastreamento:** #{target_issue}")
    body_lines.append(
        "- **Sensores de Validação:** `just verify` aprovado com Score 100%.\n"
    )
    if target_issue is not None:
        body_lines.append(f"Closes #{target_issue}\n")
    body_text = "\n".join(body_lines)

    create_proc = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            title_text,
            "--body",
            body_text,
            "--head",
            branch_name,
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if create_proc.returncode != 0:
        err = create_proc.stderr.strip()
        return None, None, f"Falha ao criar Pull Request via gh: {err}"

    created_url = create_proc.stdout.strip()
    num_match = re.search(r"/pull/(\d+)", created_url)
    created_num = int(num_match.group(1)) if num_match else None
    return created_num, created_url, "Pull Request criado com sucesso."


def publish_spec_hub_pr(
    spec_hub_dir: Path,
    spec_path: Path,
    spec_id: str,
    spec_title: str = "",
) -> tuple[int | None, str | None, str]:
    """Garante que a spec principal esteja no spec-hub e abre o PR central.

    Caso o arquivo da spec esteja fora do diretório `specs/` do `spec-hub`,
    copia o arquivo para `<spec-hub>/specs/`. Em seguida, cria/alterna para
    a branch `spec/<spec_id_lower>`, realiza stage/commit dos artefatos de
    governança (`specs/`, `capabilities/`, `SPECS_INDEX.md`, `DOMAIN_MAP.md`),
    faz push e abre (ou recupera) o Pull Request no repositório `spec-hub`.

    Args:
        spec_hub_dir: Diretório local do repositório `<project>-spec-hub`.
        spec_path: Caminho do arquivo da especificação mestre.
        spec_id: Identificador da especificação (ex: SPEC-004).
        spec_title: Título descritivo da especificação.

    Returns:
        Tupla `(pr_number, pr_url, status_message)`.
    """
    if not spec_hub_dir.is_dir():
        return None, None, "Diretório spec-hub não encontrado."

    hub_specs_dir = spec_hub_dir / "specs"
    hub_specs_dir.mkdir(parents=True, exist_ok=True)
    hub_spec_file = hub_specs_dir / spec_path.name
    if spec_path.is_file() and spec_path.resolve() != hub_spec_file.resolve():
        hub_spec_file.write_text(
            spec_path.read_text(encoding="utf-8"), encoding="utf-8"
        )

    if not (spec_hub_dir / ".git").exists():
        return None, None, f"Spec sincronizada localmente em {hub_spec_file}."

    branch_name = f"spec/{spec_id.lower()}"
    if not ensure_working_branch(spec_hub_dir, branch_name):
        return (
            None,
            None,
            f"Não foi possível criar/alternar branch {branch_name} no spec-hub.",
        )

    subprocess.run(
        ["git", "add", "."],
        cwd=spec_hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=spec_hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if status_proc.returncode == 0 and status_proc.stdout.strip():
        commit_title = f"docs(spec): [{spec_id}] {spec_title or spec_id}".strip()
        subprocess.run(
            ["git", "commit", "-m", commit_title],
            cwd=spec_hub_dir,
            capture_output=True,
            text=True,
            check=False,
        )

    push_proc = subprocess.run(
        ["git", "push", "-u", "origin", branch_name],
        cwd=spec_hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if push_proc.returncode != 0:
        err = push_proc.stderr.strip()
        return None, None, f"Falha no push da branch {branch_name} no spec-hub: {err}"

    existing_num, existing_url = get_active_pr_info(spec_hub_dir, branch_name)
    if existing_num is not None:
        return (
            existing_num,
            existing_url,
            f"PR central #{existing_num} já aberto no spec-hub: {existing_url}",
        )

    pr_title = f"docs(spec): [{spec_id}] {spec_title or spec_id}".strip()
    pr_body = (
        f"## Especificação Central — {spec_id}\n\n"
        f"- **Título:** {spec_title or spec_id}\n"
        f"- **Arquivo:** `specs/{hub_spec_file.name}`\n"
        f"- **Branch:** `{branch_name}`\n\n"
        "Pull Request central aberto automaticamente durante o fan-out pelo "
        "Agentic Flywheel."
    )
    create_proc = subprocess.run(
        [
            "gh",
            "pr",
            "create",
            "--title",
            pr_title,
            "--body",
            pr_body,
            "--head",
            branch_name,
        ],
        cwd=spec_hub_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if create_proc.returncode != 0:
        err = create_proc.stderr.strip()
        return None, None, f"Falha ao criar PR no spec-hub via gh: {err}"

    created_url = create_proc.stdout.strip()
    num_match = re.search(r"/pull/(\d+)", created_url)
    created_num = int(num_match.group(1)) if num_match else None
    return (
        created_num,
        created_url,
        f"PR central #{created_num} aberto no spec-hub: {created_url}",
    )


def get_active_issue_info(
    repo_dir: Path, spec_id: str
) -> tuple[int | None, str | None]:
    """Consulta informações de issue aberta associada à especificação no repositório.

    Args:
        repo_dir: Diretório raiz do repositório local.
        spec_id: Identificador da especificação (ex: SPEC-004).

    Returns:
        Tupla contendo `(issue_number, issue_url)` ou `(None, None)` se não encontrada.
    """
    proc = subprocess.run(
        ["gh", "issue", "list", "--state", "open", "--json", "number,title,url"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        proc.returncode != 0
        or not isinstance(proc.stdout, str)
        or not proc.stdout.strip()
    ):
        return None, None

    try:
        items = json.loads(proc.stdout)
        if isinstance(items, list):
            target_tag = f"[{spec_id.upper()}]"
            for item in items:
                if isinstance(item, dict):
                    title = str(item.get("title", ""))
                    if target_tag in title.upper():
                        num = int(item.get("number", 0)) or None
                        url = str(item.get("url", "")) or None
                        return num, url
    except (json.JSONDecodeError, ValueError):
        pass

    return None, None


def compose_task_issue_body(
    spec_id: str,
    task_id: str,
    wave: int,
    repo_name: str,
    sub_spec_path: str,
    depends_on: list[str] | None = None,
    expected_version: str | None = None,
    sub_spec_content: str | None = None,
) -> str:
    """Compõe o corpo da issue de rastreamento com a especificação da subtarefa.

    Args:
        spec_id: Identificador da especificação (ex: SPEC-004).
        task_id: Identificador da tarefa (ex: task-1).
        wave: Onda de execução da subtarefa.
        repo_name: Nome do repositório.
        sub_spec_path: Caminho da especificação vinculada.
        depends_on: Lista de tarefas predecessoras.
        expected_version: Versão esperada para release.
        sub_spec_content: Conteúdo completo em Markdown da especificação do repositório.

    Returns:
        String contendo o corpo da issue pronto para publicação no GitHub.
    """
    dep_text = ", ".join(depends_on) if depends_on else "Nenhuma"
    ver_text = expected_version or "N/A"
    header_lines = [
        f"## Rastreamento de Subtarefa - {spec_id}\n",
        f"- **Tarefa:** `{task_id}`",
        f"- **Onda de Execução:** `Onda {wave}`",
        f"- **Repositório:** `{repo_name}`",
        f"- **Especificação:** `{spec_id}` ({sub_spec_path or spec_id})",
        f"- **Dependências:** `{dep_text}`",
        f"- **Versão Esperada:** `{ver_text}`",
        (
            "- **Diretriz de Pull Request:** Ao abrir o PR via `gh pr create`, "
            "inclua obrigatoriamente `Closes #<issue_number>` no corpo do PR "
            "para encerramento automático da issue após o merge.\n"
        ),
    ]
    if sub_spec_content:
        header_lines.append("---\n")
        header_lines.append(sub_spec_content.strip())
    else:
        header_lines.append("### Descrição e Requisitos\n")
        header_lines.append(
            f"Implementação e validação da capacidade referente a `{spec_id}` "
            "via Harness SDD.\n"
        )

    full_body = "\n".join(header_lines)
    if len(full_body) > 65000:
        trunc_note = (
            f"\n\n> [!NOTE]\n> Especificação disponível em `{sub_spec_path}`.\n"
        )
        full_body = full_body[:64500] + trunc_note
    return full_body


def maybe_upgrade_existing_issue_body(
    repo_dir: Path,
    existing_num: int,
    sub_spec_content: str | None,
    body_text: str,
) -> None:
    """Atualiza o corpo da issue existente caso contenha apenas um stub inicial.

    Args:
        repo_dir: Diretório raiz do repositório local.
        existing_num: Número da issue existente no GitHub.
        sub_spec_content: Conteúdo completo da especificação do repositório.
        body_text: Novo corpo enriquecido da issue.
    """
    if not sub_spec_content or len(sub_spec_content.strip()) <= 20:
        return
    view_proc = subprocess.run(
        [
            "gh",
            "issue",
            "view",
            str(existing_num),
            "--json",
            "body",
            "-q",
            ".body",
        ],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if view_proc.returncode != 0:
        return
    current_issue_body = view_proc.stdout.strip()
    if "via Harness SDD" in current_issue_body and len(current_issue_body) < 1000:
        subprocess.run(
            [
                "gh",
                "issue",
                "edit",
                str(existing_num),
                "--body",
                body_text,
            ],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )


def resolve_task_issue_labels(ci_mode: bool, wave: int) -> list[str]:
    """Determina as labels aplicadas à issue da tarefa com base no ambiente.

    Args:
        ci_mode: Flag indicando ambiente CI/remoto.
        wave: Onda de execução da subtarefa.

    Returns:
        Lista de labels do GitHub.
    """
    if ci_mode:
        return ["agent-run", "agent-spec"] if wave == 1 else ["agent-spec"]
    return ["agent-local", "agent-spec"]


def execute_issue_creation(
    repo_dir: Path,
    cmd: list[str],
    labels: list[str],
) -> subprocess.CompletedProcess[str]:
    """Executa a criação de issue via gh CLI com auto-recuperação de labels ausentes.

    Args:
        repo_dir: Diretório raiz do repositório local.
        cmd: Comando gh estruturado.
        labels: Lista de labels necessárias.

    Returns:
        Resultado da execução do subprocess.
    """
    proc = subprocess.run(
        cmd,
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0 and labels:
        stderr_text = (proc.stderr or proc.stdout).strip()
        ensure_labels_exist(
            labels,
            run_gh=lambda args: subprocess.run(
                ["gh", *args],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                check=False,
            ),
        )
        proc = subprocess.run(
            cmd,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"gh issue create com labels falhou em {repo_dir.name}: "
                f"{(proc.stderr or proc.stdout).strip() or stderr_text} — as "
                f"labels {', '.join(labels)} são obrigatórias para a esteira "
                "(gatilho de execução); corrija permissões/labels e re-execute "
                "o fan-out. Issue NÃO é criada sem rótulo (mascaramento "
                "proibido pela diretriz de RCA)."
            )
    return proc


def ensure_task_issue(
    repo_dir: Path,
    spec_id: str,
    task_id: str,
    task_title: str = "",
    wave: int = 1,
    depends_on: list[str] | None = None,
    expected_version: str | None = None,
    sub_spec_path: str = "",
    sub_spec_content: str | None = None,
    ci_mode: bool = False,
) -> tuple[int | None, str | None]:
    """Garante que a issue de rastreamento da subtarefa exista no repositório spoke.

    Consulta se já existe issue aberta referenciando `[{spec_id}]`. Caso não
    exista, cria uma nova issue via `gh issue create` com a especificação.
    Caso já exista com descrição curta, atualiza com a especificação completa.

    No modo local (`ci_mode=False`), aplica as labels `['agent-local', 'agent-spec']`
    para manter os runners da nuvem em repouso.
    No modo cloud (`ci_mode=True`), aplica `['agent-run', 'agent-spec']` na Onda 1.

    Args:
        repo_dir: Diretório raiz do repositório local.
        spec_id: Identificador da especificação (ex: SPEC-004).
        task_id: Identificador da tarefa (ex: task-1).
        task_title: Título descritivo da funcionalidade.
        wave: Onda de execução da subtarefa.
        depends_on: Lista de tarefas predecessoras.
        expected_version: Versão esperada para release da subtarefa.
        sub_spec_path: Caminho da especificação vinculada.
        sub_spec_content: Conteúdo completo em Markdown da especificação do repositório.
        ci_mode: Flag indicando se a execução ocorre em ambiente CI/Remoto.

    Returns:
        Tupla contendo `(issue_number, issue_url)` ou `(None, None)` em falha.
    """
    body_text = compose_task_issue_body(
        spec_id=spec_id,
        task_id=task_id,
        wave=wave,
        repo_name=repo_dir.name,
        sub_spec_path=sub_spec_path,
        depends_on=depends_on,
        expected_version=expected_version,
        sub_spec_content=sub_spec_content,
    )

    existing_num, existing_url = get_active_issue_info(repo_dir, spec_id)
    if existing_num is not None:
        maybe_upgrade_existing_issue_body(
            repo_dir=repo_dir,
            existing_num=existing_num,
            sub_spec_content=sub_spec_content,
            body_text=body_text,
        )
        return existing_num, existing_url

    title_text = f"feat: [{spec_id}] {task_title or f'Implementar {task_id}'}".strip()
    labels = resolve_task_issue_labels(ci_mode=ci_mode, wave=wave)

    cmd = ["gh", "issue", "create", "--title", title_text, "--body", body_text]
    for lbl in labels:
        cmd.extend(["--label", lbl])

    proc = execute_issue_creation(repo_dir=repo_dir, cmd=cmd, labels=labels)
    if proc.returncode != 0:
        return None, None

    created_url = proc.stdout.strip()
    num_match = re.search(r"/issues/(\d+)", created_url)
    created_num = int(num_match.group(1)) if num_match else None
    return created_num, created_url


def sync_consumer_dependency(repo_dir: Path, dependency_name: str) -> tuple[int, str]:
    """Sincroniza e atualiza o lockfile do módulo consumidor via `uv`.

    Executa `uv lock --upgrade-package <dep> && uv sync` para absorver
    a nova release publicada pela dependência em ondas anteriores.

    Args:
        repo_dir: Diretório raiz do módulo consumidor (ex: paralax-support).
        dependency_name: Nome do pacote a ser atualizado (ex: paralax-evo-crm).

    Returns:
        Tupla contendo `(returncode, output_text)`.
    """
    clean_dep = dependency_name.split("/")[-1].strip()
    lock_proc = subprocess.run(
        ["uv", "lock", "--upgrade-package", clean_dep],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if lock_proc.returncode != 0:
        err = (lock_proc.stdout + "\n" + lock_proc.stderr).strip()
        return lock_proc.returncode, err

    sync_proc = subprocess.run(
        ["uv", "sync"],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    output = (sync_proc.stdout + "\n" + sync_proc.stderr).strip()
    return sync_proc.returncode, output
