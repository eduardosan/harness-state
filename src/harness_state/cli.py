"""Interface de linha de comando para o harness-state."""

import asyncio
import click
from rich.console import Console
from rich.table import Table
from harness_state.client import StateStore
from harness_state.models import SpecRun, SubTask, TaskState

console = Console()


@click.group()
def main():
    """CLI oficial de gerenciamento de estado da Plataforma SDD (eduardosan)."""
    pass


@main.command()
@click.option("--spec-id", required=True, help="Identificador único da spec (ex: SPEC-042)")
@click.option("--title", required=True, help="Título descritivo da funcionalidade")
@click.option("--author", default="local-dev", help="Autor da especificação")
def init(spec_id: str, title: str, author: str):
    """Inicializa uma nova especificação no Redis central."""
    async def _run():
        store = StateStore()
        spec = SpecRun(spec_id=spec_id, title=title, author=author)
        await store.save_spec(spec)
        console.print(f"[bold green]✓[/bold green] Spec [bold cyan]{spec_id}[/bold cyan] inicializada com sucesso no Redis central.")
    asyncio.run(_run())


@main.command()
@click.argument("spec_id")
def status(spec_id: str):
    """Exibe o progresso atual de uma especificação e seus repositórios."""
    async def _run():
        store = StateStore()
        spec = await store.get_spec(spec_id)
        if not spec:
            console.print(f"[bold red]Erro:[/bold red] Spec [bold cyan]{spec_id}[/bold cyan] não encontrada no Redis.")
            return

        table = Table(title=f"Spec: {spec.spec_id} - {spec.title} (Status: {spec.status.value})")
        table.add_column("Tarefa ID", style="cyan")
        table.add_column("Repositório", style="magenta")
        table.add_column("Branch", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("PR", style="blue")
        table.add_column("Último Worker", style="dim")

        for task in spec.tasks.values():
            table.add_row(
                task.id,
                task.repo,
                task.branch,
                task.status.value,
                f"#{task.pr_number}" if task.pr_number else "-",
                task.last_worker or "-"
            )

        console.print(table)
    asyncio.run(_run())


@main.command()
@click.argument("spec_id")
@click.argument("task_id")
@click.argument("new_status")
@click.option("--worker", default="local-dev", help="Identificador do worker atual")
@click.option("--pr", type=int, default=None, help="Número do Pull Request aberto")
def update(spec_id: str, task_id: str, new_status: str, worker: str, pr: int):
    """Atualiza o estado de uma sub-tarefa."""
    async def _run():
        store = StateStore()
        parsed_status = TaskState(new_status.upper())
        updated = await store.update_task_status(spec_id, task_id, parsed_status, worker_id=worker, pr_number=pr)
        if not updated:
            console.print(f"[bold red]Erro:[/bold red] Não foi possível atualizar a tarefa {task_id} na spec {spec_id}.")
            return
        console.print(f"[bold green]✓[/bold green] Tarefa [bold cyan]{task_id}[/bold cyan] atualizada para [bold yellow]{parsed_status.value}[/bold yellow].")
    asyncio.run(_run())
