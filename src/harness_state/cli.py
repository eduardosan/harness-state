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
from harness_state.spec.discovery import SpecDiscoveryEngine
from harness_state.spec.evolution import SpecEvolutionEngine
from harness_state.spec.lifecycle import approve_spec, resolve_spec_file_path
from harness_state.spec_parser import parse_spec_tasks

console = Console()


def load_manifest_dependencies(
    manifest_path: Path | None = None,
) -> dict[str, list[str]]:
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


def calculate_task_wave(
    tid: str, subtasks: dict[str, SubTask], visited: set[str]
) -> int:
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
        (
            calculate_task_wave(dep_tid, subtasks, visited)
            for dep_tid in task.depends_on
            if dep_tid in subtasks
        ),
        default=0,
    )


def calculate_waves(
    subtasks: dict[str, SubTask], dep_map: dict[str, list[str]]
) -> dict[str, SubTask]:
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
        direct_deps = dep_map.get(task.repo, []) or dep_map.get(
            task.repo.split("/")[-1], []
        )
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
            console.print(
                f"[bold red]Erro:[/bold red] Spec [bold cyan]{spec_id}[/bold cyan] não encontrada."
            )
            return

        table = Table(
            title=f"Spec: {spec.spec_id} - {spec.title} (Status: {spec.status.value})"
        )
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


def check_plan_spec_discovery(
    title: str,
    specs_dir: Path | None,
    target_capability: str | None = None,
) -> bool:
    """Executa a descoberta prévia no comando plan e avisa se spec correlata existir.

    Args:
        title: Título ou prompt proposto no plan.
        specs_dir: Diretório opcional de especificações.
        target_capability: Capability alvo informada ou None.

    Returns:
        True se uma spec existente com alta similaridade foi identificada (interrompe criação).
    """
    target_dir = specs_dir or Path("specs")
    if not target_dir.is_dir():
        return False
    engine = SpecDiscoveryEngine(specs_dir=target_dir)
    matches = engine.discover_related_specs(
        title, target_capability=target_capability, threshold=0.6
    )
    if not matches:
        return False
    top = matches[0]
    if top.similarity_score < 0.75:
        return False

    console.print(
        f"\n[bold yellow]ℹ Spec existente identificada:[/bold yellow] "
        f"[bold cyan]{top.spec_id}[/bold cyan] - {top.title} "
        f"(similaridade: {top.similarity_score})"
    )
    console.print(
        f"Sugestão: execute '[bold green]harness spec update {top.spec_id} -p \"...\"[/bold green]' "
        f"para evoluir a spec existente em vez de duplicar.\n"
        f"[dim](Use --force-new para forçar a criação de uma nova especificação)[/dim]"
    )
    return True


def merge_plan_subtasks(
    existing: SpecRun,
    target_title: str,
    parsed_subtasks: dict[str, SubTask],
) -> None:
    """Mescla subtarefas de um novo plano em uma especificação existente.

    Args:
        existing: Instância de SpecRun existente.
        target_title: Novo título ou atualizado.
        parsed_subtasks: Dicionário de subtarefas parsed.
    """
    existing.title = target_title
    for tid, task in parsed_subtasks.items():
        if tid not in existing.tasks:
            existing.tasks[tid] = task
        else:
            existing.tasks[tid].wave = task.wave
            existing.tasks[tid].depends_on = task.depends_on


def resolve_plan_targets(
    spec_file: str | None,
    manifest_file: str | None,
    spec_id: str | None,
    title: str | None,
) -> tuple[str | None, str, dict[str, SubTask]] | None:
    """Resolve identificador, título e subtarefas a partir dos parâmetros de plan.

    Args:
        spec_file: Caminho opcional do arquivo SPEC.md.
        manifest_file: Caminho opcional do manifest.yaml.
        spec_id: Identificador opcional da spec.
        title: Título opcional da spec.

    Returns:
        Tupla (target_spec_id, target_title, parsed_subtasks) ou None se arquivo inválido.
    """
    target_spec_id = spec_id
    target_title = title or "Nova Especificação"
    parsed_subtasks: dict[str, SubTask] = {}

    if spec_file is not None:
        file_context = resolve_spec_file_context(
            spec_file=spec_file, manifest_file=manifest_file
        )
        if file_context is None:
            return None
        _target_manifest, parsed_id, parsed_title, parsed_subtasks = file_context
        target_spec_id = target_spec_id or parsed_id
        target_title = title or parsed_title

    return target_spec_id, target_title, parsed_subtasks


async def run_plan(
    spec_file: str | None = None,
    spec_id: str | None = None,
    title: str | None = None,
    author: str = "local-dev",
    manifest_file: str | None = None,
    store: StateStoreProtocol | None = None,
    specs_dir: Path | None = None,
    force_new: bool = False,
) -> None:
    """Planeja ou registra uma especificação a partir de parâmetros ou arquivo markdown.

    Args:
        spec_file: Caminho opcional do arquivo SPEC.md.
        spec_id: Identificador opcional da especificação.
        title: Título opcional da especificação.
        author: Autor da especificação.
        manifest_file: Caminho opcional para o manifest.yaml com grafo de dependências.
        store: Instância opcional de persistência.
        specs_dir: Diretório opcional de especificações.
        force_new: Se True, ignora sugestão de evolução de spec existente.
    """
    if (
        title
        and not force_new
        and spec_file is None
        and check_plan_spec_discovery(title=title, specs_dir=specs_dir)
    ):
        return

    targets = resolve_plan_targets(
        spec_file=spec_file,
        manifest_file=manifest_file,
        spec_id=spec_id,
        title=title,
    )
    if targets is None:
        return
    target_spec_id, target_title, parsed_subtasks = targets

    if not target_spec_id:
        console.print("[bold red]Erro:[/bold red] Identificador da spec não informado.")
        return

    active_store = store or StateStore()
    async with active_store:
        existing = await active_store.get_spec(target_spec_id)
        if existing is not None:
            merge_plan_subtasks(existing, target_title, parsed_subtasks)
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
            console.print(
                f"[bold red]Erro:[/bold red] Spec [bold cyan]{spec_id}[/bold cyan] não encontrada."
            )
            return

        if spec.is_complete:
            console.print(
                f"[bold green]✓[/bold green] Todas as tarefas da spec [bold cyan]{spec_id}[/bold cyan] "
                "já foram concluídas!"
            )
            return

        active_tasks = [
            t for t in spec if t.status in (TaskState.PENDING, TaskState.IN_PROGRESS)
        ]
        if not active_tasks:
            console.print(
                f"[bold yellow]Nenhuma tarefa em andamento encontrada para {spec_id}.[/bold yellow]"
            )
            return

        next_task = active_tasks[0]
        console.print(
            f"[bold cyan]Retomando:[/bold cyan] Tarefa [bold green]{next_task.id}[/bold green] "
            f"no repositório [bold magenta]{next_task.repo}[/bold magenta] (branch: [bold yellow]{next_task.branch}[/bold yellow])."
        )
        console.print(
            f"Para iniciar execute: [bold white]git checkout {next_task.branch}[/bold white]"
        )


def list_available_plugins() -> list[Any]:
    """Lista plugins disponíveis no grupo de entry points `harness.plugins`.

    Returns:
        Lista de entry points registrados (vazia quando nenhum plugin).
    """
    from importlib.metadata import entry_points

    return list(entry_points(group="harness.plugins"))


def merge_plugin_spec_commands(target_group: click.Group, plugin_spec: click.Group) -> None:
    """Mescla subcomandos de spec providos por um plugin sem sobrescrever os públicos.

    Args:
        target_group: Grupo público `spec`.
        plugin_spec: Grupo `spec` fornecido pelo plugin.
    """
    for sub_name, sub_cmd in plugin_spec.commands.items():
        if sub_name not in target_group.commands:
            target_group.add_command(sub_cmd, name=sub_name)


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
                f"[harness] plugin '{entry_point.name}' falhou ao carregar: {exc}",
                err=True,
            )
            continue
        for name, command in candidate.commands.items():
            existing = group.commands.get(name)
            if (
                name == "spec"
                and isinstance(existing, click.Group)
                and isinstance(command, click.Group)
            ):
                merge_plugin_spec_commands(existing, command)
                continue
            if name in group.commands:
                click.echo(
                    f"[harness] plugin '{entry_point.name}' tentou sobrescrever "
                    f"o comando '{name}' (público) — rejeitado.",
                    err=True,
                )
                continue
            group.add_command(command, name=name)


class PluginLoadingGroup(click.Group):
    """Grupo Click que monta os plugins `harness.plugins` antes de despachar.

    O binário `harness` é o único ponto de entrada público da plataforma;
    comandos privados do ecossistema (ex.: `setup`, `spec`, `bug` aportados
    pelo agentic-flywheel via entry point) precisam ser resolvidos no dispatch
    real, não apenas quando um chamador invoca `load_plugins_into`
    manualmente. O click resolve o subcomando por nome ANTES de executar o
    callback do grupo, por isso a garantia vive em `get_command`/`list_commands`.

    Attributes:
        plugins_mounted: Marcador de idempotência da montagem dos plugins.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Inicializa o grupo com o marcador de plugins não montados.

        Args:
            *args: Posicionais repassados a `click.Group`.
            **kwargs: Nomeados repassados a `click.Group`.
        """
        super().__init__(*args, **kwargs)
        self.plugins_mounted = False

    def ensure_plugins_mounted(self) -> None:
        """Monta os plugins uma única vez neste grupo (idempotente)."""
        if self.plugins_mounted:
            return
        self.plugins_mounted = True
        load_plugins_into(self)

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        """Resolve o subcomando garantindo os plugins antes da consulta.

        Args:
            ctx: Contexto Click corrente.
            cmd_name: Nome do subcomando solicitado.

        Returns:
            Comando registrado (núcleo ou plugin) ou None quando inexistente.
        """
        self.ensure_plugins_mounted()
        return super().get_command(ctx, cmd_name)

    def list_commands(self, ctx: click.Context) -> list[str]:
        """Lista os subcomandos incluindo os aportados por plugins.

        Args:
            ctx: Contexto Click corrente.

        Returns:
            Nomes de comandos em ordem de exibição.
        """
        self.ensure_plugins_mounted()
        return super().list_commands(ctx)


@click.group(cls=PluginLoadingGroup)
def main() -> None:
    """CLI oficial de gerenciamento de estado da Plataforma SDD (eduardosan)."""


@main.command()
@click.option(
    "--spec-id", required=True, help="Identificador único da spec (ex: SPEC-042)"
)
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
def update(
    spec_id: str, task_id: str, new_status: str, worker: str, pr: int | None
) -> None:
    """Atualiza o estado de uma subtarefa."""
    asyncio.run(
        run_update(
            spec_id=spec_id,
            task_id=task_id,
            new_status=new_status,
            worker=worker,
            pr=pr,
        )
    )


@main.command()
@click.option(
    "--spec",
    "spec_file",
    type=click.Path(),
    default=None,
    help="Caminho do arquivo de especificação",
)
@click.option(
    "--manifest",
    "manifest_file",
    type=click.Path(),
    default=None,
    help="Caminho do arquivo manifest.yaml",
)
@click.option("--spec-id", default=None, help="Identificador único da spec")
@click.option("--title", default=None, help="Título descritivo da funcionalidade")
@click.option("--author", default="local-dev", help="Autor da especificação")
@click.option(
    "--specs-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Diretório de especificações",
)
@click.option(
    "--force-new",
    is_flag=True,
    default=False,
    help="Força criação de nova spec ignorando correspondência existente",
)
def plan(
    spec_file: str | None,
    manifest_file: str | None,
    spec_id: str | None,
    title: str | None,
    author: str,
    specs_dir: Path | None = None,
    force_new: bool = False,
) -> None:
    """Grava ou atualiza uma nova spec e suas sub-tarefas no barramento central."""
    asyncio.run(
        run_plan(
            spec_file=spec_file,
            manifest_file=manifest_file,
            spec_id=spec_id,
            title=title,
            author=author,
            specs_dir=specs_dir,
            force_new=force_new,
        )
    )


@main.command()
@click.argument("spec_id")
def resume(spec_id: str) -> None:
    """Retoma o trabalho no ambiente atual identificando a próxima tarefa pendente."""
    asyncio.run(run_resume(spec_id=spec_id))


async def save_spec_for_cli(spec: SpecRun, active_store: StateStoreProtocol) -> None:
    """Salva a especificação no StateStore ativo.

    Args:
        spec: Instância do SpecRun a ser persistida.
        active_store: Store de persistência.
    """
    async with active_store:
        await active_store.save_spec(spec)


def run_spec_update(
    spec_target: str,
    user_prompt: str,
    author: str = "local-dev",
    specs_dir: Path | None = None,
    store: StateStoreProtocol | None = None,
) -> None:
    """Evolui uma especificação existente no spec-hub e no barramento central.

    Args:
        spec_target: Caminho ou identificador da especificação (ex: SPEC-008).
        user_prompt: Instrução do operador descrevendo a evolução.
        author: Autor da revisão.
        specs_dir: Diretório opcional de specs.
        store: Store opcional para persistência de estado.
    """
    resolved_dir = specs_dir or Path("specs")
    resolved_file = resolve_spec_file_path(spec_target, specs_dir=resolved_dir)
    if resolved_file is None or not resolved_file.is_file():
        console.print(f"[bold red]Erro:[/bold red] Especificação {spec_target} não encontrada.")
        return

    engine = SpecEvolutionEngine(spec_hub_dir=resolved_dir.parent)
    active_store = store or StateStore()
    current_run: SpecRun | None = None
    try:
        current_run = asyncio.run(get_spec_for_cli(resolved_file.stem, active_store))
    except (OSError, RuntimeError, ValueError):
        current_run = None

    plan = engine.analyze_spec_evolution(
        spec_path=resolved_file,
        instruction=user_prompt,
        current_run=current_run,
    )

    if plan.has_breaking_changes:
        console.print(
            "[bold yellow]⚠️  Aviso: Breaking change detectada em contratos de tarefas congeladas![/bold yellow]"
        )
        console.print(f"Versão incrementada para MAJOR: [bold red]{plan.target_version}[/bold red]")

    revision = engine.apply_evolution_to_spec(
        spec_path=resolved_file,
        plan=plan,
        author=author,
        instruction=user_prompt,
    )

    if current_run is not None:
        current_run.apply_evolution(plan.target_version, revision, plan.tasks_to_execute)
        asyncio.run(save_spec_for_cli(current_run, active_store))

    console.print(
        f"[bold green]✓[/bold green] Spec [bold cyan]{plan.spec_id}[/bold cyan] "
        f"evoluída para versão [bold cyan]{plan.target_version}[/bold cyan] "
        f"({len(plan.frozen_tasks)} congeladas, {len(plan.tasks_to_execute)} a executar)."
    )


@main.group(name="spec")
def spec_group() -> None:
    """Comandos para gerenciamento do ciclo de vida de especificações (SDD)."""


@spec_group.command(name="update")
@click.argument("spec_target")
@click.option("--prompt", "-p", "user_prompt", required=True, help="Instrução de evolução da spec")
@click.option("--author", default="local-dev", help="Autor da evolução")
@click.option(
    "--specs-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Diretório de especificações",
)
def spec_update_cmd(
    spec_target: str,
    user_prompt: str,
    author: str,
    specs_dir: Path | None,
) -> None:
    """Evolui uma especificação existente preservando tarefas concluídas como congeladas."""
    run_spec_update(
        spec_target=spec_target,
        user_prompt=user_prompt,
        author=author,
        specs_dir=specs_dir,
    )


@spec_group.command(name="plan")
@click.option(
    "--spec",
    "spec_file",
    type=click.Path(),
    default=None,
    help="Caminho do arquivo de especificação",
)
@click.option(
    "--manifest",
    "manifest_file",
    type=click.Path(),
    default=None,
    help="Caminho do arquivo manifest.yaml",
)
@click.option("--spec-id", default=None, help="Identificador único da spec")
@click.option("--title", default=None, help="Título descritivo da funcionalidade")
@click.option("--author", default="local-dev", help="Autor da especificação")
@click.option(
    "--specs-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Diretório de especificações",
)
@click.option(
    "--force-new",
    is_flag=True,
    default=False,
    help="Força criação de nova spec ignorando correspondência existente",
)
def spec_plan_cmd(
    spec_file: str | None,
    manifest_file: str | None,
    spec_id: str | None,
    title: str | None,
    author: str,
    specs_dir: Path | None,
    force_new: bool,
) -> None:
    """Planeja ou registra uma especificação no barramento central."""
    asyncio.run(
        run_plan(
            spec_file=spec_file,
            manifest_file=manifest_file,
            spec_id=spec_id,
            title=title,
            author=author,
            specs_dir=specs_dir,
            force_new=force_new,
        )
    )


@spec_group.command(name="status")
@click.argument("spec_id")
def spec_status_cmd(spec_id: str) -> None:
    """Exibe o progresso atual de uma especificação e suas tarefas."""
    asyncio.run(run_status(spec_id=spec_id))


@spec_group.command(name="approve")
@click.argument("spec_target")
@click.option("--author", default="antigravity", help="Agente autor da spec")
@click.option(
    "--specs-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Diretório de especificações",
)
def spec_approve_cmd(
    spec_target: str,
    author: str,
    specs_dir: Path | None,
) -> None:
    """Aprova formalmente uma especificação e sincroniza o mapa de capacidades (Gate 2)."""
    resolved_file = resolve_spec_file_path(spec_target, specs_dir=specs_dir)
    if resolved_file is None or not resolved_file.is_file():
        console.print(f"[bold red]Erro:[/bold red] Especificação {spec_target} não encontrada.")
        return
    success = approve_spec(resolved_file, author_agent=author)
    if success:
        console.print(
            f"[bold green]✓[/bold green] Spec [bold cyan]{spec_target}[/bold cyan] "
            "aprovada e mapa de capacidades sincronizado."
        )


@spec_group.command(name="sync-hub")
@click.option(
    "--repo-spec",
    "repo_spec_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Caminho da sub-spec no repositório spoke",
)
@click.option(
    "--hub-spec",
    "hub_spec_path",
    type=click.Path(path_type=Path),
    required=True,
    help="Caminho da spec mestre no spec-hub",
)
@click.option(
    "--workspace-root",
    "workspace_root",
    type=click.Path(path_type=Path),
    default=None,
    help="Raiz do workspace de repositórios",
)
def spec_sync_hub_cmd(
    repo_spec_path: Path,
    hub_spec_path: Path,
    workspace_root: Path | None,
) -> None:
    """Sincroniza sub-spec do spoke de volta para o spec-hub mestre."""
    from harness_state.spec.fanout import sync_spoke_spec_to_hub

    outcome = sync_spoke_spec_to_hub(
        spoke_spec_path=repo_spec_path,
        hub_spec_path=hub_spec_path,
    )
    if not outcome.success:
        console.print(f"[bold red]Erro ao sincronizar spec-hub:[/bold red] {outcome.message}")
        raise click.ClickException(outcome.message)
    console.print(
        f"[bold green]✓ Spec {outcome.spec_id} sincronizada no spec-hub com sucesso![/bold green] "
        f"Seções atualizadas: {', '.join(outcome.updated_sections) if outcome.updated_sections else 'nenhuma'}"
    )


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


@main.command(name="judge")
@click.option(
    "--local",
    is_flag=True,
    default=False,
    help="Executa a auto-avaliação do Judge Local contra as 3 regras normativas",
)
@click.option(
    "--fast",
    is_flag=True,
    default=False,
    help="Executa o Judge em voto único consolidado (< 1 min)",
)
@click.option(
    "--out-file",
    type=click.Path(path_type=Path),
    default=None,
    help="Arquivo de saída com o resultado consolidado do Judge em JSON",
)
@click.option(
    "--repo-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Diretório do repositório para avaliação local",
)
@click.option(
    "--base-ref",
    default=None,
    help="Referência Git base para comparação do diff no Judge Local",
)
def judge_cmd(
    local: bool,
    fast: bool,
    out_file: Path | None,
    repo_dir: Path | None,
    base_ref: str | None,
) -> None:
    """Executa o LLM-as-a-Judge canônico ou a auto-avaliação local."""
    from harness_state.judge import evaluate_local_diff

    if local:
        eval_result = evaluate_local_diff(
            repo_dir=repo_dir,
            base_ref=base_ref,
            out_file=out_file,
        )
        if eval_result.is_approved:
            console.print(
                "[bold green]✓ Auto-avaliação do Judge Local: APROVADO "
                f"({eval_result.compliance_score}/100)[/bold green]"
            )
            raise SystemExit(0)
        console.print(
            "[bold red]✗ Auto-avaliação do Judge Local: REJEITADO "
            f"({eval_result.compliance_score}/100)[/bold red]"
        )
        for violation in eval_result.violations:
            console.print(f"  [red]• {violation}[/red]")
        raise SystemExit(1)


# ============================================================
# Flywheel Management Commands (Onda 1 - SPEC-009)
# ============================================================


@click.group(name="flywheel")
def flywheel_group() -> None:
    """Gerencia o lifecycle do Flywheel Execution Engine.

    Comandos para inicializar, atualizar e monitorar instâncias do flywheel
    que rodam pipelines instalados via harness-state.
    """


@flywheel_group.command(name="init")
@click.argument("path", type=click.Path(path_type=Path))
@click.option(
    "--version",
    default=None,
    help="Versão fixa do harness-state/agentic-flywheel (ex: 0.4.0)",
)
@click.option(
    "--config",
    type=click.Path(path_type=Path),
    default=None,
    help="Arquivo de configuração customizado",
)
def flywheel_init(path: Path, version: str | None, config: Path | None) -> None:
    """Inicializa um novo Flywheel Execution Engine em <path>.

    Cria estrutura de pastas, pyproject.toml com dependências,
    workflows CI e config.yaml inicial.
    """
    from .flywheel import init_flywheel

    init_flywheel(path, version=version, config_file=config)


@flywheel_group.command(name="update")
@click.argument("path", type=click.Path(path_type=Path))
@click.option(
    "--version",
    default=None,
    help="Versão fixa do harness-state/agentic-flywheel (ex: 0.4.1)",
)
@click.option(
    "--dry-run", is_flag=True, help="Apenas mostra o que seria alterado sem aplicar"
)
def flywheel_update(path: Path, version: str | None, dry_run: bool) -> None:
    """Atualiza um Flywheel existente: bump de versões, regenera workflows, valida imports."""
    from .flywheel import update_flywheel

    update_flywheel(path, version=version, dry_run=dry_run)


@flywheel_group.command(name="status")
@click.argument("path", type=click.Path(path_type=Path))
def flywheel_status(path: Path) -> None:
    """Mostra health check do flywheel: versões instaladas vs disponíveis, validação de imports."""
    from .flywheel import check_flywheel_status

    check_flywheel_status(path)


@flywheel_group.command(name="update-all")
@click.option("--dry-run", is_flag=True, help="Apenas mostra o que seria feito")
@click.option(
    "--strategy",
    type=click.Choice(["patch", "minor", "major"]),
    default="patch",
    help="Estratégia semver para release",
)
@click.option(
    "--only", default=None, help="Atualiza apenas um flywheel específico pelo nome"
)
def flywheel_update_all(dry_run: bool, strategy: str, only: str | None) -> None:
    """Atualiza todos os flywheels configurados no config.yaml com release automático."""
    from .flywheel import update_all_flywheels

    update_all_flywheels(
        dry_run=dry_run, strategy=only or None, strategy_semver=strategy
    )


main.add_command(flywheel_group)


@main.command(name="install")
@click.option(
    "--path",
    "project_path",
    type=click.Path(path_type=Path),
    default=Path("."),
    help="Raiz do pacote local onde as skills e o pipeline serão instalados",
)
def install_cmd(project_path: Path) -> None:
    """Instala templates de harness, skills e isolamento em um spoke."""
    from harness_state.installer import install_module_harness

    res = install_module_harness(project_path)
    console.print(
        f"[bold green]✓ Harness instalado com sucesso em {res.project_root} (linguagem: {res.language})[/bold green]"
    )


@main.command(name="release")
@click.option(
    "--repo-dir",
    type=click.Path(path_type=Path),
    default=Path("."),
    help="Diretório do repositório alvo",
)
@click.option(
    "--strategy",
    type=click.Choice(["patch", "minor", "major"]),
    default="patch",
    help="Estratégia semver para release",
)
def release_cmd(repo_dir: Path, strategy: str) -> None:
    """Calcula ou emite a próxima release semântica do repositório."""
    from harness_state.release import (
        compute_next_release_tag,
        get_repo_declared_version,
        get_repo_latest_release_tag,
    )

    latest_tag = get_repo_latest_release_tag(repo_dir) or get_repo_declared_version(
        repo_dir
    )
    next_tag, next_version, bump_part = compute_next_release_tag(
        latest_tag=latest_tag,
        explicit_bump=strategy,
    )
    console.print(
        f"Próxima tag de release: [bold cyan]{next_tag}[/bold cyan] (versão: {next_version}, bump: {bump_part})"
    )


@main.command(name="audit")
@click.option(
    "--path",
    "project_path",
    type=click.Path(path_type=Path),
    default=Path("."),
    help="Raiz do repositório a ser auditado",
)
@click.option(
    "--mask-sensitive-data",
    "check_sensitive",
    is_flag=True,
    default=True,
    help="Executa a verificação mask-sensitive-data (§7 SPEC-009)",
)
def audit_cmd(project_path: Path, check_sensitive: bool) -> None:
    """Audita repositório quanto a dados sensíveis e conformidade."""
    from harness_state.audit import audit_sensitive_data

    if check_sensitive:
        offenders = audit_sensitive_data(project_path.resolve())
        if offenders:
            console.print(
                "[bold red]Violações de dados sensíveis encontradas:[/bold red]"
            )
            for off in offenders:
                console.print(f"  [red]✗[/red] {off}")
            raise click.ClickException("Auditoria de mask-sensitive-data falhou.")
        console.print(
            "[bold green]✓ mask-sensitive-data: Nenhuma violação detectada.[/bold green]"
        )


def run_local_verify(project_root: Path) -> bool:
    """Executa verificação estática local de conformidade (ast_sensor, complexidade).

    Args:
        project_root: Diretório raiz do módulo a ser verificado.

    Returns:
        True se todas as verificações foram bem-sucedidas, False caso contrário.
    """
    from harness_state.sensors.ast_sensor import AstSensor, collect_paths
    from harness_state.sensors.complexity_sensor import run_complexity_sensor

    console.print(f"[bold blue]Iniciando verificação estática em {project_root}...[/bold blue]")
    passed = True

    py_files = [
        p for p in project_root.rglob("*.py")
        if not any(part.startswith(".") for part in p.parts)
    ]
    if py_files:
        collected = collect_paths([str(project_root)])
        violations = AstSensor().run(collected)
        if violations:
            console.print(f"[bold red]✗ AST Sensor:[/bold red] {len(violations)} violações detectadas.")
            for v in violations[:10]:
                console.print(f"  [red]- {v.rule}: {v.message} ({v.line}:{v.column})[/red]")
            passed = False
        else:
            console.print("[bold green]✓ AST Sensor: Aprovado sem violações.[/bold green]")

    complexity_violations = run_complexity_sensor([str(project_root)])
    if complexity_violations:
        console.print(f"[bold red]✗ Complexidade Cognitiva:[/bold red] {len(complexity_violations)} violações detectadas.")
        for cv in complexity_violations[:10]:
            console.print(f"  [red]- {cv.file_path}:{cv.line} - {cv.function_name} (complexidade: {cv.complexity})[/red]")
        passed = False
    else:
        console.print("[bold green]✓ Complexidade Cognitiva: Aprovada.[/bold green]")

    return passed


@main.command(name="verify")
@click.option(
    "--path",
    "project_path",
    type=click.Path(path_type=Path),
    default=Path("."),
    help="Raiz do repositório a ser verificado",
)
def verify_cmd(project_path: Path) -> None:
    """Verificação estática local de conformidade (ast_sensor, complexidade, pyright)."""
    success = run_local_verify(project_path.resolve())
    if not success:
        raise click.ClickException("Verificação estática falhou.")
    console.print("[bold green]✓ Conformidade estática aprovada.[/bold green]")


@main.command(name="map-all")
@click.option(
    "--spec-hub-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Diretório do spec-hub (auto-descoberto se omitido)",
)
@click.option(
    "--workspace-root",
    type=click.Path(path_type=Path),
    default=None,
    help="Raiz do workspace de repositórios",
)
def map_all_cmd(spec_hub_dir: Path | None, workspace_root: Path | None) -> None:
    """Mapeia e sincroniza o grafo de produtos, capacidades e contratos de todo o ecossistema."""
    from harness_state.capabilities import DomainInspector, print_map_all_report

    target_hub = spec_hub_dir
    if target_hub is None:
        candidates = [
            Path("../harness-spec-hub"),
            Path("../paralax-spec-hub"),
            Path("../../harness-spec-hub"),
            Path("../../paralax-spec-hub"),
            Path("."),
        ]
        for cand in candidates:
            if (cand / "manifest.yaml").is_file() and (cand / "capabilities").is_dir():
                target_hub = cand
                break
    if target_hub is None or not target_hub.exists():
        console.print("[bold red]Erro:[/bold red] Diretório do spec-hub não encontrado. Especifique via --spec-hub-dir.")
        raise click.ClickException("spec-hub não encontrado")

    inspector = DomainInspector()
    report = inspector.map_all_repositories(target_hub, workspace_root)
    print_map_all_report(report)


# ============================================================
# Config and Flywheel Module Imports (lazy loaded)
# ============================================================


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
