"""Parser canônico de subtarefas de spec Markdown (SPEC-008).

Fonte única de extração de subtarefas de uma spec, compartilhada entre a
CLI pública `harness plan` (harness-state) e a esteira do flywheel
(`spec plan`/fan-out), garantindo um único contrato de formato e de nome
de branch (namespaced via SPEC-007).
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedSubTask:
    """Sub-tarefa parseada de uma spec, com branch canônica namespaced.

    Attributes:
        task_id: Identificador da tarefa (ex: `task-1`).
        repo: Repositório como escrito na spec (ex: `agentic-flywheel` ou
            `eduardosan/harness-state`).
        repo_name: Último segmento do slug do repositório.
        branch: Branch canônica (ex: `agent/harness-spec-007-harness-state`).
        title: Título descritivo da tarefa.
        raw_content: Corpo acumulado entre cabeçalhos de tarefa.
        pr_number: Número do PR associado, quando referenciado.
        checked: True quando o checkbox da tarefa está marcado `[x]`.
        wave: Onda de execução (padrão 1; cálculo fica com o consumidor).
    """

    task_id: str
    repo: str
    repo_name: str
    branch: str
    title: str
    raw_content: str = ""
    pr_number: int | None = None
    checked: bool = False
    wave: int = 1


def derive_ecosystem_from_repo(repo: str) -> str:
    """Deriva o namespace do ecossistema a partir do slug do hub (SPEC-007).

    Args:
        repo: Slug do repositório hub (ex: `eduardosan/harness-spec-hub`).

    Returns:
        Nome curto do ecossistema (string vazia quando indeterminável).
    """
    if not repo:
        return ""
    name = repo.split("/")[-1]
    if name.endswith("-spec-hub"):
        return name[: -len("-spec-hub")]
    return name


def resolve_short_spec_id(spec_id: str) -> str:
    """Deriva o prefixo curto da spec usado na branch (ex: `spec-007`).

    Args:
        spec_id: Identificador da spec (ex: `SPEC-007-fanout-ci-real`).

    Returns:
        Prefixo curto em minúsculas.
    """
    parts = spec_id.lower().split("-")
    if len(parts) >= 2 and parts[0] in ("spec", "sdd"):
        return f"{parts[0]}-{parts[1]}"
    return parts[0]


def build_branch(ecosystem: str, short_spec_id: str, repo_name: str) -> str:
    """Monta a branch canônica namespaced para um repositório.

    Args:
        ecosystem: Namespace do ecossistema (vazio omite o prefixo).
        short_spec_id: Prefixo curto da spec.
        repo_name: Último segmento do slug do repositório.

    Returns:
        Nome da branch no formato `agent/{eco}-{spec}-{repo}`.
    """
    if ecosystem:
        return f"agent/{ecosystem}-{short_spec_id}-{repo_name}"
    return f"agent/{short_spec_id}-{repo_name}"


def make_subtask(
    task_id: str,
    repo: str,
    short_spec_id: str,
    ecosystem: str,
    checked: bool,
    pr_number: int | None,
    raw_content: str,
) -> ParsedSubTask:
    """Constrói uma `ParsedSubTask` com branch canônica e título derivado.

    Args:
        task_id: Identificador da tarefa.
        repo: Repositório como escrito na spec.
        short_spec_id: Prefixo curto da spec.
        ecosystem: Namespace do ecossistema.
        checked: Estado do checkbox `[x]`.
        pr_number: Número do PR associado ou None.
        raw_content: Corpo acumulado da tarefa.

    Returns:
        Instância de `ParsedSubTask`.
    """
    repo_name = repo.split("/")[-1]
    return ParsedSubTask(
        task_id=task_id,
        repo=repo,
        repo_name=repo_name,
        branch=build_branch(ecosystem, short_spec_id, repo_name),
        title=f"Implementar {task_id} para {repo_name}",
        raw_content=raw_content,
        pr_number=pr_number,
        checked=checked,
    )


def finalize_task(
    task_id: str | None,
    repo: str,
    checked: bool,
    pr_number: int | None,
    content_lines: list[str],
    short_spec_id: str,
    ecosystem: str,
    tasks: list[ParsedSubTask],
) -> None:
    """Consolida a subtarefa corrente e a adiciona à lista.

    Args:
        task_id: Identificador da tarefa corrente (None quando não há).
        repo: Repositório como escrito na spec.
        checked: Estado do checkbox.
        pr_number: Número do PR associado ou None.
        content_lines: Linhas acumuladas do corpo (esvaziadas após o uso).
        short_spec_id: Prefixo curto da spec.
        ecosystem: Namespace do ecossistema.
        tasks: Lista mutável de destino.
    """
    if task_id is None:
        return
    tasks.append(
        make_subtask(
            task_id=task_id,
            repo=repo,
            short_spec_id=short_spec_id,
            ecosystem=ecosystem,
            checked=checked,
            pr_number=pr_number,
            raw_content="\n".join(content_lines).strip(),
        )
    )
    content_lines.clear()


def parse_spec_tasks(
    lines: list[str],
    *,
    spec_id: str,
    ecosystem: str = "",
) -> list[ParsedSubTask]:
    """Extrai as subtarefas de uma spec em formato canônico ou checkbox genérico.

    Suporta o formato canônico `- [ ] **Sub-tarefa N (`repo`):** ...` e o
    fallback de compatibilidade `- [ ] ... `repo``. Linhas dentro de blocos
    de código (```) são ignoradas.

    Args:
        lines: Linhas do arquivo Markdown da especificação.
        spec_id: Identificador da spec.
        ecosystem: Namespace do ecossistema (prefixa as branches).

    Returns:
        Lista de `ParsedSubTask` na ordem de aparição.
    """
    canonical_re = re.compile(
        r"-\s*\[([ xX])\]\s*\*\*Sub-tarefa\s*(\d+)\s*\(`([^`]+)`\):\*\*(.*)"
    )
    fallback_re = re.compile(r"-\s*\[([ xX])\]\s*.*?`([^`]+)`.*?")
    pr_re = re.compile(r"\[PR #(\d+)\]\((https?://[^\)]+)\)")

    short_spec_id = resolve_short_spec_id(spec_id)
    tasks: list[ParsedSubTask] = []

    cur_id: str | None = None
    cur_repo = ""
    cur_checked = False
    cur_pr: int | None = None
    content_lines: list[str] = []
    in_fence = False
    fallback_index = 1

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        match = canonical_re.search(line)
        if match:
            finalize_task(
                cur_id,
                cur_repo,
                cur_checked,
                cur_pr,
                content_lines,
                short_spec_id,
                ecosystem,
                tasks,
            )
            cur_checked = match.group(1).lower() == "x"
            cur_id = f"task-{match.group(2)}"
            cur_repo = match.group(3).strip()
            pr_match = pr_re.search(match.group(4).strip())
            cur_pr = int(pr_match.group(1)) if pr_match else None
            continue

        if cur_id is None:
            fallback_match = fallback_re.search(line)
            if fallback_match:
                tasks.append(
                    make_subtask(
                        task_id=f"task-{fallback_index}",
                        repo=fallback_match.group(2).strip(),
                        short_spec_id=short_spec_id,
                        ecosystem=ecosystem,
                        checked=fallback_match.group(1).lower() == "x",
                        pr_number=None,
                        raw_content="",
                    )
                )
                fallback_index += 1
            continue

        if stripped.startswith(("## ", "---")):
            finalize_task(
                cur_id,
                cur_repo,
                cur_checked,
                cur_pr,
                content_lines,
                short_spec_id,
                ecosystem,
                tasks,
            )
            cur_id = None
            cur_repo = ""
            cur_checked = False
            cur_pr = None
            continue

        content_lines.append(line)

    finalize_task(
        cur_id,
        cur_repo,
        cur_checked,
        cur_pr,
        content_lines,
        short_spec_id,
        ecosystem,
        tasks,
    )
    return tasks
