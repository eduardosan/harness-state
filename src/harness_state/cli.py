"""Interface de linha de comando para o harness-state."""

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from harness_state.client import StateStore, StateStoreProtocol
from harness_state.models import SpecRun, TaskState

console = Console()


def parse_spec_markdown(file_path: Path) -> tuple[str, str]:
    """Extrai o identificador e o título de uma especificação em markdown.

    Args:
        file_path: Caminho para o arquivo markdown da especificação.

    Returns:
        Tupla contendo (spec_id, title).
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
    return spec_id, title


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
        table.add_column("Repositório", style="magenta")
        table.add_column("Branch", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("PR", style="blue")
        table.add_column("Último Worker", style="dim")

        for task in spec:
            table.add_row(
                task.id,
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
    store: StateStoreProtocol | None = None,
) -> None:
    """Planeja ou registra uma especificação a partir de parâmetros ou arquivo markdown.

    Args:
        spec_file: Caminho opcional do arquivo SPEC.md.
        spec_id: Identificador opcional da especificação.
        title: Título opcional da especificação.
        author: Autor da especificação.
        store: Instância opcional de persistência.
    """
    target_spec_id = spec_id
    target_title = title or "Nova Especificação"

    if spec_file is not None:
        file_path = Path(spec_file)
        if not file_path.exists():
            console.print(f"[bold red]Erro:[/bold red] Arquivo {spec_file} não encontrado.")
            return
        parsed_id, parsed_title = parse_spec_markdown(file_path)
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
            await active_store.save_spec(existing)
            console.print(
                f"[bold green]✓[/bold green] Plano para [bold cyan]{target_spec_id}[/bold cyan] "
                "atualizado com sucesso."
            )
            return

        new_spec = SpecRun(spec_id=target_spec_id, title=target_title, author=author)
        await active_store.save_spec(new_spec)
        console.print(
            f"[bold green]✓[/bold green] Plano para [bold cyan]{target_spec_id}[/bold cyan] "
            "registrado com sucesso."
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
@click.option("--spec-id", default=None, help="Identificador único da spec")
@click.option("--title", default=None, help="Título descritivo da funcionalidade")
@click.option("--author", default="local-dev", help="Autor da especificação")
def plan(spec_file: str | None, spec_id: str | None, title: str | None, author: str) -> None:
    """Grava ou atualiza uma nova spec e suas sub-tarefas no barramento central."""
    asyncio.run(run_plan(spec_file=spec_file, spec_id=spec_id, title=title, author=author))


@main.command()
@click.argument("spec_id")
def resume(spec_id: str) -> None:
    """Retoma o trabalho no ambiente atual identificando a próxima tarefa pendente."""
    asyncio.run(run_resume(spec_id=spec_id))
