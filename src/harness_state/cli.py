"""Interface de linha de comando para o harness-state."""

import asyncio
import json
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

from harness_state.client import StateStore, StateStoreProtocol
from harness_state.models import SpecRun, SubTask, TaskState
from harness_state.spec_parser import parse_spec_tasks

console = Console()


def load_manifest_dependencies(manifest_path: Path | None = None) -> dict[str, list[str]]:
    """Carrega o mapa de dependências a partir do manifest.yaml.

    Args:
        manifest_path: Caminho opcional para o arquivo manifest.yaml.

    Returns:
        Dicionário mapeando nome ou repo do projeto para sua lista de dependências.
    """
    if manifest_path is None or not manifest_path.exists():
        return {}

    try:
        content = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        repos_data = content.get("repositories", [])
        dep_map: dict[str, list[str]] = {}
        for entry in repos_data:
            name = entry.get("name", "")
            repo = entry.get("repo", "")
            deps = entry.get("depends_on", [])
            if name:
                dep_map[name] = deps
            if repo:
                dep_repo = deps
                dep_map[repo] = dep_repo
        return dep_map
    except (yaml.YAMLError, OSError):
        return {}


def load_manifest_project(manifest_path: Path | None = None) -> str:
    """Lê o campo `project` do manifest.yaml (namespace do ecossistema).

    Args:
        manifest_path: Caminho opcional para o arquivo manifest.yaml.

    Returns:
        Nome do projeto/ecossistema (string vazia quando ausente ou ilegível).
    """
    if manifest_path is None or not manifest_path.exists():
        return ""
    try:
        content = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        return str(content.get("project") or "")
    except (yaml.YAMLError, OSError):
        return ""


def calculate_task_wave(tid: str, subtasks: dict[str, SubTask], visited: set[str]) -> int:
    """Calcula a onda de uma subtarefa recursivamente com proteção de ciclo.

    Args:
        tid: Identificador da subtarefa.
        subtasks: Dicionário completo de subtarefas.
        visited: Conjunto de tarefas já visitadas na cadeia para evitar ciclos.

    Returns:
        Número inteiro representando a onda de execução (1, 2, ...).
    """
    if tid in visited:
        return 1
    visited.add(tid)
    task = subtasks.get(tid)
    if task is None or not task.depends_on:
        return 1
    return 1 + max(
        (calculate_task_wave(dep_tid, subtasks, visited) for dep_tid in task.depends_on if dep_tid in subtasks),
        default=0,
    )


def calculate_waves(subtasks: dict[str, SubTask], dep_map: dict[str, list[str]]) -> dict[str, SubTask]:
    """Calcula a onda (wave) e dependências de execução para cada subtarefa.

    Args:
        subtasks: Dicionário de subtarefas extraídas.
        dep_map: Grafo de dependências entre repositórios.

    Returns:
        Dicionário de subtarefas com ondas e dependências preenchidas.
    """
    repo_to_task_id: dict[str, str] = {}
    for tid, task in subtasks.items():
        repo_to_task_id[task.repo] = tid
        repo_to_task_id[task.repo.split("/")[-1]] = tid

    for task in subtasks.values():
        direct_deps = dep_map.get(task.repo, []) or dep_map.get(task.repo.split("/")[-1], [])
        task.depends_on = [
            repo_to_task_id[dep]
            for dep in direct_deps
            if dep in repo_to_task_id and repo_to_task_id[dep] != task.id
        ]

    for tid, task in subtasks.items():
        task.wave = calculate_task_wave(tid, subtasks, set())

    # Ordena as subtarefas pela onda crescente
    ordered = dict(sorted(subtasks.items(), key=lambda item: (item[1].wave, item[0])))
    return ordered


def parse_spec_markdown(
    file_path: Path, manifest_path: Path | None = None, ecosystem: str = ""
) -> tuple[str, str, dict[str, SubTask]]:
    """Extrai identificador, título e subtarefas de uma especificação em markdown.

    Args:
        file_path: Caminho para o arquivo markdown da especificação.
        manifest_path: Caminho opcional para o manifesto com dependências.
        ecosystem: Namespace do ecossistema (prefixa as branches, SPEC-008).

    Returns:
        Tupla contendo (spec_id, title, dict_subtasks).
    """
    spec_id = file_path.stem
    content = file_path.read_text(encoding="utf-8")
    title = spec_id

    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                title = candidate
                break

    parsed_tasks = parse_spec_tasks(
        content.splitlines(), spec_id=spec_id, ecosystem=ecosystem
    )
    subtasks: dict[str, SubTask] = {
        task.task_id: SubTask(
            id=task.task_id,
            repo=task.repo,
            branch=task.branch,
            status=TaskState.APPROVED if task.checked else TaskState.PENDING,
        )
        for task in parsed_tasks
    }

    dep_map = load_manifest_dependencies(manifest_path)
    if dep_map:
        subtasks = calculate_waves(subtasks, dep_map)

    return spec_id, title, subtasks



async def run_init(
    spec_id: str,
    title: str,
    author: str,
    store: StateStoreProtocol | None = None,
) -> None:
    """Executa a lógica assíncrona de inicialização de uma especificação.

    Args:
        spec_id: Identificador único da especificação.
        title: Título descritivo.
        author: Autor ou responsável.
        store: Instância opcional de persistência compatível com StateStoreProtocol.
    """
    active_store = store or StateStore()
    async with active_store:
        spec = SpecRun(spec_id=spec_id, title=title, author=author)
        await active_store.save_spec(spec)
        console.print(
            f"[bold green]✓[/bold green] Spec [bold cyan]{spec_id}[/bold cyan] "
            "inicializada com sucesso no barramento central."
        )


async def run_status(
    spec_id: str,
    store: StateStoreProtocol | None = None,
) -> None:
    """Executa a recuperação e exibição do status de uma especificação.

    Args:
        spec_id: Identificador da especificação.
        store: Instância opcional de persistência.
    """
    active_store = store or StateStore()
    async with active_store:
        spec = await active_store.get_spec(spec_id)
        if spec is None:
            console.print(f"[bold red]Erro:[/bold red] Spec [bold cyan]{spec_id}[/bold cyan] não encontrada.")
            return

        table = Table(title=f"Spec: {spec.spec_id} - {spec.title} (Status: {spec.status.value})")
        table.add_column("Tarefa ID", style="cyan")
        table.add_column("Onda", style="bold green", justify="center")
        table.add_column("Repositório", style="magenta")
        table.add_column("Branch", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("PR", style="blue")
        table.add_column("Último Worker", style="dim")

        for task in spec:
            table.add_row(
                task.id,
                f"Onda {task.wave}",
                task.repo,
                task.branch,
                task.status.value,
                f"#{task.pr_number}" if task.pr_number is not None else "-",
                task.last_worker or "-",
            )

        console.print(table)


async def run_update(
    spec_id: str,
    task_id: str,
    new_status: str,
    worker: str = "local-dev",
    pr: int | None = None,
    store: StateStoreProtocol | None = None,
) -> None:
    """Executa a atualização de estado de uma subtarefa.

    Args:
        spec_id: Identificador da especificação.
        task_id: Identificador da subtarefa.
        new_status: Nome do novo status (ex: READY, IN_PROGRESS).
        worker: Identificador do worker.
        pr: Número opcional do Pull Request.
        store: Instância opcional de persistência.
    """
    active_store = store or StateStore()
    parsed_status = TaskState(new_status.upper())
    async with active_store:
        updated = await active_store.update_task_status(
            spec_id=spec_id,
            task_id=task_id,
            status=parsed_status,
            worker_id=worker,
            pr_number=pr,
        )
        if updated is None:
            console.print(
                f"[bold red]Erro:[/bold red] Não foi possível atualizar a tarefa {task_id} na spec {spec_id}."
            )
            return
        console.print(
            f"[bold green]✓[/bold green] Tarefa [bold cyan]{task_id}[/bold cyan] "
            f"atualizada para [bold yellow]{parsed_status.value}[/bold yellow]."
        )


async def run_plan(
    spec_file: str | None = None,
    spec_id: str | None = None,
    title: str | None = None,
    author: str = "local-dev",
    manifest_file: str | None = None,
    store: StateStoreProtocol | None = None,
) -> None:
    """Planeja ou registra uma especificação a partir de parâmetros ou arquivo markdown.

    Args:
        spec_file: Caminho opcional do arquivo SPEC.md.
        spec_id: Identificador opcional da especificação.
        title: Título opcional da especificação.
        author: Autor da especificação.
        manifest_file: Caminho opcional para o manifest.yaml com grafo de dependências.
        store: Instância opcional de persistência.
    """
    target_spec_id = spec_id
    target_title = title or "Nova Especificação"

    parsed_subtasks: dict[str, SubTask] = {}
    if spec_file is not None:
        file_context = resolve_spec_file_context(
            spec_file=spec_file, manifest_file=manifest_file
        )
        if file_context is None:
            return
        _target_manifest, parsed_id, parsed_title, parsed_subtasks = file_context
        target_spec_id = target_spec_id or parsed_id
        target_title = title or parsed_title


    if not target_spec_id:
        console.print("[bold red]Erro:[/bold red] Identificador da spec não informado.")
        return

    active_store = store or StateStore()
    async with active_store:
        existing = await active_store.get_spec(target_spec_id)
        if existing is not None:
            existing.title = target_title
            for tid, task in parsed_subtasks.items():
                if tid not in existing.tasks:
                    existing.tasks[tid] = task
                else:
                    existing.tasks[tid].wave = task.wave
                    existing.tasks[tid].depends_on = task.depends_on
            await active_store.save_spec(existing)
            console.print(
                f"[bold green]✓[/bold green] Plano para [bold cyan]{target_spec_id}[/bold cyan] "
                f"atualizado com sucesso ({len(existing.tasks)} subtarefas)."
            )
            return

        new_spec = SpecRun(
            spec_id=target_spec_id,
            title=target_title,
            author=author,
            tasks=parsed_subtasks,
        )
        await active_store.save_spec(new_spec)
        console.print(
            f"[bold green]✓[/bold green] Plano para [bold cyan]{target_spec_id}[/bold cyan] "
            f"registrado com sucesso ({len(parsed_subtasks)} subtarefas)."
        )


async def run_resume(
    spec_id: str,
    store: StateStoreProtocol | None = None,
) -> None:
    """Identifica a próxima tarefa pendente de uma especificação e instrui o operador.

    Args:
        spec_id: Identificador da especificação.
        store: Instância opcional de persistência.
    """
    active_store = store or StateStore()
    async with active_store:
        spec = await active_store.get_spec(spec_id)
        if spec is None:
            console.print(f"[bold red]Erro:[/bold red] Spec [bold cyan]{spec_id}[/bold cyan] não encontrada.")
            return

        if spec.is_complete:
            console.print(
                f"[bold green]✓[/bold green] Todas as tarefas da spec [bold cyan]{spec_id}[/bold cyan] "
                "já foram concluídas!"
            )
            return

        active_tasks = [t for t in spec if t.status in (TaskState.PENDING, TaskState.IN_PROGRESS)]
        if not active_tasks:
            console.print(f"[bold yellow]Nenhuma tarefa em andamento encontrada para {spec_id}.[/bold yellow]")
            return

        next_task = active_tasks[0]
        console.print(
            f"[bold cyan]Retomando:[/bold cyan] Tarefa [bold green]{next_task.id}[/bold green] "
            f"no repositório [bold magenta]{next_task.repo}[/bold magenta] (branch: [bold yellow]{next_task.branch}[/bold yellow])."
        )
        console.print(f"Para iniciar execute: [bold white]git checkout {next_task.branch}[/bold white]")




def list_available_plugins() -> list[Any]:
    """Lista plugins disponíveis no grupo de entry points `harness.plugins`.

    Returns:
        Lista de entry points registrados (vazia quando nenhum plugin).
    """
    from importlib.metadata import entry_points

    return list(entry_points(group="harness.plugins"))


def load_plugins_into(group: click.Group) -> None:
    """Carrega plugins externos dentro do grupo da CLI pública.

    Plugins declaram um entry point no grupo `harness.plugins` apontando
    para uma função `register(group: click.Group) -> None`. Cada um:

    - registra subgrupos/comandos privados sobre o núcleo;
    - NUNCA sobrescreve um comando público já existente (skip + aviso);
    - falha de plugin é reportada no stderr e não derruba a CLI.

    Args:
        group: Grupo click de destino (o grupo raiz `harness`).
    """
    for entry_point in list_available_plugins():
        try:
            register = entry_point.load()
            candidate = click.Group(f"__probe_{entry_point.name}")
            register(candidate)
        except Exception as exc:  # noqa: BLE001 — aviso e continuação são o contrato do plugin registry
            click.echo(
                f"[harness] plugin '{entry_point.name}' falhou ao carregar: "
                f"{exc}",
                err=True,
            )
            continue
        for name, command in candidate.commands.items():
            if name in group.commands:
                click.echo(
                    f"[harness] plugin '{entry_point.name}' tentou sobrescrever "
                    f"o comando '{name}' (público) — rejeitado.",
                    err=True,
                )
                continue
            group.add_command(command, name=name)




@click.group()
def main() -> None:
    """CLI oficial de gerenciamento de estado da Plataforma SDD (eduardosan)."""


@main.command()
@click.option("--spec-id", required=True, help="Identificador único da spec (ex: SPEC-042)")
@click.option("--title", required=True, help="Título descritivo da funcionalidade")
@click.option("--author", default="local-dev", help="Autor da especificação")
def init(spec_id: str, title: str, author: str) -> None:
    """Inicializa uma nova especificação no barramento central."""
    asyncio.run(run_init(spec_id=spec_id, title=title, author=author))


@main.command()
@click.argument("spec_id")
def status(spec_id: str) -> None:
    """Exibe o progresso atual de uma especificação e seus repositórios."""
    asyncio.run(run_status(spec_id=spec_id))


@main.command()
@click.argument("spec_id")
@click.argument("task_id")
@click.argument("new_status")
@click.option("--worker", default="local-dev", help="Identificador do worker atual")
@click.option("--pr", type=int, default=None, help="Número do Pull Request aberto")
def update(spec_id: str, task_id: str, new_status: str, worker: str, pr: int | None) -> None:
    """Atualiza o estado de uma subtarefa."""
    asyncio.run(run_update(spec_id=spec_id, task_id=task_id, new_status=new_status, worker=worker, pr=pr))


@main.command()
@click.option("--spec", "spec_file", type=click.Path(), default=None, help="Caminho do arquivo de especificação")
@click.option("--manifest", "manifest_file", type=click.Path(), default=None, help="Caminho do arquivo manifest.yaml")
@click.option("--spec-id", default=None, help="Identificador único da spec")
@click.option("--title", default=None, help="Título descritivo da funcionalidade")
@click.option("--author", default="local-dev", help="Autor da especificação")
def plan(
    spec_file: str | None,
    manifest_file: str | None,
    spec_id: str | None,
    title: str | None,
    author: str,
) -> None:
    """Grava ou atualiza uma nova spec e suas sub-tarefas no barramento central."""
    asyncio.run(
        run_plan(
            spec_file=spec_file,
            manifest_file=manifest_file,
            spec_id=spec_id,
            title=title,
            author=author,
        )
    )


@main.command()
@click.argument("spec_id")
def resume(spec_id: str) -> None:
    """Retoma o trabalho no ambiente atual identificando a próxima tarefa pendente."""
    asyncio.run(run_resume(spec_id=spec_id))


def run_get_spec(
    spec_id: str,
    store: StateStoreProtocol | None = None,
) -> None:
    """Executa o `get-spec` read-only: imprime o SpecRun em JSON.

    Args:
        spec_id: Referência da spec (`ecosistema/SPEC-XXX` ou `SPEC-XXX`).
        store: Instância opcional de persistência.
    """
    active_store = store or StateStore()
    spec = asyncio.run(get_spec_for_cli(spec_id, active_store))
    if spec is None:
        console.print(
            f"[bold red]Erro:[/bold red] Spec [bold cyan]{spec_id}[/bold cyan] "
            "não encontrada."
        )
        raise SystemExit(1)
    console.print_json(json.dumps(spec.model_dump(mode="json")))


async def get_spec_for_cli(
    spec_id: str, active_store: StateStoreProtocol
) -> SpecRun | None:
    async with active_store:
        return await active_store.get_spec(spec_id)


@main.command(name="get-spec")
@click.argument("spec_id")
def get_spec_cmd(spec_id: str) -> None:
    """Imprime o SpecRun como JSON (read-only, para agentes e integrações)."""
    run_get_spec(spec_id=spec_id)


load_plugins_into(main)


def resolve_spec_file_context(
    spec_file: str, manifest_file: str | None
) -> tuple[Path | None, str, str, dict[str, SubTask]] | None:
    """Resolve o contexto de arquivo de spec e manifest para o run_plan.

    Auto-descobre manifest.yaml quando não fornecido (cwd do arquivo, pai ou
    o hub declarado oficialmente).

    Args:
        spec_file: Caminho informado pelo operador.
        manifest_file: Manifest do hub, quando declarado.

    Returns:
        Tupla `(manifest_resolvido, spec_id, title, subtasks)` — None quando
        o arquivo informado não existe (erro já impresso no console).
    """
    file_path = Path(spec_file)
    if not file_path.exists():
        console.print(f"[bold red]Erro:[/bold red] Arquivo {spec_file} não encontrado.")
        return None

    # Auto-descobre manifest.yaml se não fornecido
    target_manifest = Path(manifest_file) if manifest_file else None
    if target_manifest is None:
        # Procura no diretório pai ou no hub paralax-spec-hub
        candidate_same_dir = file_path.parent / "manifest.yaml"
        candidate_parent = file_path.parent.parent / "manifest.yaml"
        if candidate_same_dir.exists():
            target_manifest = candidate_same_dir
        elif candidate_parent.exists():
            target_manifest = candidate_parent

    parsed_id, parsed_title, parsed_subtasks = parse_spec_markdown(
        file_path,
        manifest_path=target_manifest,
        ecosystem=load_manifest_project(target_manifest),
    )
    return target_manifest, parsed_id, parsed_title, parsed_subtasks
