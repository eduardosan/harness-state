"""Orquestrador semi-automatizado de tarefas SDD (`harness spec run`) local e remoto."""

import inspect
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console

from harness_state.agents import AgentRunner, DetectedAgent
from harness_state.capabilities import DomainInspector
from harness_state.client import StateStore, StateStoreProtocol
from harness_state.collector import collect_diffs
from harness_state.config import (
    ConfigurationError,
    HarnessLocalConfig,
    SSHTunnelManager,
    TunnelStatus,
    apply_config_to_environment,
    load_harness_config,
)
from harness_state.contracts import ContractValidationResult
from harness_state.gate import GateGitHubCLIClient, TransactionalGateClosure
from harness_state.git_ops import (
    ensure_task_issue,
    ensure_working_branch,
    publish_spec_hub_pr,
    publish_task_pr,
    sync_consumer_dependency,
    sync_repo_release_tags,
)
from harness_state.installer import install_module_harness
from harness_state.judge import JudgeEvaluation, evaluate_spec_diff
from harness_state.models import SpecRun, SubTask, TaskState
from harness_state.prompt_manager import LangfusePromptManager
from harness_state.release import (
    get_repo_declared_version,
    get_repo_latest_release_tag,
    is_dependency_release_satisfied,
)
from harness_state.sensors.prompt_sensor import (
    PromptGovernanceSensor,
    pull_prompts_from_langfuse_ssot,
    sync_modified_prompts_as_draft,
)
from harness_state.spec.fanout import (
    MergeOutcome,
    fanout_all_repository_specs,
    generate_repo_spec,
    mark_repo_spec_status,
    merge_completed_hub_branches,
    save_repo_spec,
    sync_spoke_spec_to_hub,
)
from harness_state.spec.lifecycle import (
    SpecRefineOutcome,
    approve_spec,
    build_spec_refine_prompt,
    ensure_spec_has_prompts,
    extract_yaml_frontmatter,
    get_frozen_and_pending_tasks,
    merge_refined_spec,
)
from harness_state.spec_parser import (
    build_branch,
    derive_ecosystem_from_repo,
    parse_spec_tasks,
    resolve_short_spec_id,
)
from harness_state.workspace import preflight_spec_workspace

console = Console()


@dataclass(slots=True)
class PipelineStepOutcome:
    """Resultado de uma execução ou transição do orquestrador `harness spec run`.

    Attributes:
        spec_id: Identificador da especificação processada.
        active_task_id: Identificador da tarefa processada nesta rodada.
        active_repo: Repositório alvo da tarefa ativa.
        wave: Número da onda da tarefa processada.
        task_status: Estado final da tarefa após a rodada.
        all_waves_complete: Indica se todas as ondas da spec já concluíram.
        hub_synced: Indica se o `<project>-spec-hub` foi sincronizado.
        feedback: Mensagem ou saída de verificação dos sensores.
        tunnel_status: Status da verificação/abertura do túnel SSH.
        next_task_id: Identificador da próxima tarefa pendente ou None.
        next_repo: Repositório alvo da próxima tarefa pendente ou None.
        next_wave: Número da onda da próxima tarefa pendente ou None.
        blocked_by_dep: Nome do repositório da dependência aguardando release.
        expected_release: Versão esperada da release da dependência.
        latest_release: Tag da última release válida da dependência.
        pr_number: Número do Pull Request aberto para a tarefa.
        pr_url: URL completa do Pull Request aberto no GitHub.
        issue_number: Número da issue de rastreamento no GitHub.
        issue_url: URL completa da issue de rastreamento no GitHub.
        gate_waiting: Descrição do Gate Humano aguardando revisão.
        is_draft_blocked: Indica se a spec está bloqueada no Gate 2 (DRAFT).
    """

    spec_id: str
    active_task_id: str | None
    active_repo: str | None
    wave: int
    task_status: TaskState
    all_waves_complete: bool = False
    hub_synced: bool = False
    feedback: str = ""
    tunnel_status: TunnelStatus | None = None
    next_task_id: str | None = None
    next_repo: str | None = None
    next_wave: int | None = None
    blocked_by_dep: str | None = None
    expected_release: str | None = None
    latest_release: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    gate_waiting: str | None = None
    is_draft_blocked: bool = False
    is_awaiting_closure: bool = False
    prompts_promoted: list[str] = field(default_factory=list)
    judge_score: float | None = None


def load_manifest_dependencies(
    manifest_path: Path | None = None,
) -> dict[str, list[str]]:
    """Carrega o mapa de dependências a partir do `manifest.yaml` do spec-hub.

    Args:
        manifest_path: Caminho opcional para o arquivo `manifest.yaml`.

    Returns:
        Dicionário mapeando nome ou slug do repositório para suas dependências.
    """
    if manifest_path is None or not manifest_path.is_file():
        return {}

    try:
        content = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        repos_data = content.get("repositories", [])
        dep_map: dict[str, list[str]] = {}
        for entry in repos_data:
            name = entry.get("name", "")
            repo = entry.get("repo", "")
            deps = entry.get("depends_on", [])
            if name:
                dep_map[name] = deps
            if repo:
                dep_map[repo] = deps
        return dep_map
    except (yaml.YAMLError, OSError):
        return {}


def calculate_task_wave(
    tid: str, subtasks: dict[str, SubTask], visited: set[str]
) -> int:
    """Calcula a onda de uma subtarefa recursivamente com proteção de ciclo.

    Args:
        tid: Identificador da subtarefa.
        subtasks: Dicionário completo de subtarefas.
        visited: Conjunto de tarefas já visitadas na cadeia.

    Returns:
        Número inteiro representando a onda de execução (`1`, `2`, ...).
    """
    if tid in visited:
        task = subtasks.get(tid)
        return task.wave if task and task.wave >= 1 else 1
    visited.add(tid)
    task = subtasks.get(tid)
    if task is None:
        return 1
    base_wave = max(task.wave, 1)
    if not task.depends_on:
        return base_wave
    dep_max = max(
        (
            calculate_task_wave(dep_tid, subtasks, visited)
            for dep_tid in task.depends_on
            if dep_tid in subtasks
        ),
        default=0,
    )
    return max(base_wave, 1 + dep_max)


def calculate_waves(
    subtasks: dict[str, SubTask], dep_map: dict[str, list[str]]
) -> dict[str, SubTask]:
    """Calcula a onda (`wave`) e dependências de execução para cada subtarefa.

    Args:
        subtasks: Dicionário de subtarefas extraídas da spec.
        dep_map: Grafo de dependências entre repositórios.

    Returns:
        Dicionário de subtarefas ordenado por onda crescente.
    """
    repo_to_task_id: dict[str, str] = {}
    for tid, task in subtasks.items():
        repo_to_task_id[task.repo] = tid
        repo_to_task_id[task.repo.split("/")[-1]] = tid

    for task in subtasks.values():
        short_name = task.repo.split("/")[-1]
        direct_deps = dep_map.get(task.repo, []) or dep_map.get(short_name, [])
        declared_deps = list(task.depends_on)
        all_deps: list[str] = []
        for dep in declared_deps + direct_deps:
            resolved_dep = repo_to_task_id.get(dep, dep)
            if (
                resolved_dep
                and resolved_dep != task.id
                and resolved_dep in subtasks
                and resolved_dep not in all_deps
            ):
                all_deps.append(resolved_dep)
        task.depends_on = all_deps

    for tid, task in subtasks.items():
        task.wave = calculate_task_wave(tid, subtasks, set())

    ordered = dict(sorted(subtasks.items(), key=lambda item: (item[1].wave, item[0])))
    return ordered


def extract_first_markdown_heading(body: str) -> str:
    """Extrai o primeiro título Markdown (`# ...`) do corpo da especificação.

    Args:
        body: Corpo Markdown da spec.

    Returns:
        Texto do título ou string vazia.
    """
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue
        candidate = stripped.lstrip("#").strip()
        if candidate:
            return candidate
    return ""


def resolve_spec_id_and_title(
    frontmatter: dict[str, Any],
    body: str,
    file_path: Path,
) -> tuple[str, str]:
    """Resolve o identificador canônico (`spec_id`) e o título da especificação.

    Args:
        frontmatter: Metadados YAML extraídos da spec.
        body: Corpo Markdown da spec.
        file_path: Caminho do arquivo da spec.

    Returns:
        Tupla `(spec_id, title)`.
    """
    spec_id = str(
        frontmatter.get("spec_id") or file_path.stem.split("-")[0] or file_path.stem
    )
    if spec_id.upper().startswith("SPEC") and "-" in file_path.stem:
        parts = file_path.stem.split("-")
        if len(parts) >= 2 and parts[1].isdigit():
            spec_id = f"{parts[0].upper()}-{parts[1]}"

    title = (
        str(frontmatter.get("title") or "")
        or extract_first_markdown_heading(body)
        or spec_id
    )
    return spec_id, title


def resolve_spec_origin_module(
    frontmatter: dict[str, Any],
    file_path: Path,
) -> str:
    """Resolve o módulo de origem (`origin_module`) do frontmatter ou diretório.

    Args:
        frontmatter: Metadados YAML extraídos da spec.
        file_path: Caminho do arquivo da spec.

    Returns:
        Nome do módulo de origem.
    """
    raw_origin = str(frontmatter.get("origin_module") or "").strip()
    if raw_origin and raw_origin not in ("module-name", "unknown"):
        return raw_origin

    parent_dir_name = file_path.resolve().parent.parent.name
    is_hub = parent_dir_name.endswith(("-hub", "-spec-hub"))
    is_invalid = parent_dir_name in ("specs", "paralax-ia", "")
    if not is_hub and not is_invalid:
        return parent_dir_name
    return "paralax-common"


def build_subtask_from_target_repo_item(
    item: Any,
    tid: str,
    spec_id: str,
    origin_module: str,
    file_path: Path,
    ecosystem: str = "",
) -> SubTask | None:
    """Constrói uma `SubTask` a partir de um item de `target_repositories`.

    Args:
        item: Dicionário ou string declarada em `target_repositories`.
        tid: Identificador sequencial da tarefa (ex: `task-1`).
        spec_id: Identificador da spec.
        origin_module: Módulo de origem resolvido.
        file_path: Caminho da spec.
        ecosystem: Namespace do ecossistema (prefixa a branch, SPEC-008).

    Returns:
        Instância de `SubTask` ou None se o item não declarar repositório.
    """
    if isinstance(item, dict):
        repo = str(item.get("repo", "")).strip()
        explicit_wave = int(item.get("wave", 1))
        explicit_deps_raw = item.get("depends_on", [])
        if isinstance(explicit_deps_raw, list):
            explicit_deps = [str(d) for d in explicit_deps_raw]
        elif explicit_deps_raw:
            explicit_deps = [str(explicit_deps_raw)]
        else:
            explicit_deps = []
    else:
        repo = str(item).strip()
        explicit_wave = 1
        explicit_deps = []

    if not repo:
        return None
    if "module-name" in repo:
        repo = repo.replace("module-name", origin_module)
    short_repo = repo.split("/")[-1]
    if short_repo in ("module-name", "unknown"):
        short_repo = origin_module

    return SubTask(
        id=tid,
        repo=repo,
        branch=build_branch(ecosystem, resolve_short_spec_id(spec_id), short_repo),
        wave=explicit_wave,
        depends_on=explicit_deps,
        sub_spec_path=str(file_path),
    )


def extract_initial_subtasks(
    frontmatter: dict[str, Any],
    body: str,
    spec_id: str,
    origin_module: str,
    file_path: Path,
    ecosystem: str = "",
) -> dict[str, SubTask]:
    """Extrai o mapa inicial de `SubTask` do frontmatter ou checkboxes do corpo.

    Args:
        frontmatter: Metadados YAML da spec.
        body: Corpo Markdown da spec.
        spec_id: Identificador da spec.
        origin_module: Módulo de origem.
        file_path: Caminho do arquivo da spec.
        ecosystem: Namespace do ecossistema (prefixa as branches, SPEC-008).

    Returns:
        Dicionário de `SubTask` indexado por ID.
    """
    subtasks: dict[str, SubTask] = {}
    target_repos = frontmatter.get("target_repositories", [])
    task_index = 1

    if isinstance(target_repos, list) and target_repos:
        for item in target_repos:
            tid = f"task-{task_index}"
            subtask = build_subtask_from_target_repo_item(
                item, tid, spec_id, origin_module, file_path, ecosystem
            )
            if subtask is not None:
                subtasks[tid] = subtask
                task_index += 1

    if not subtasks:
        parsed_tasks = parse_spec_tasks(
            body.splitlines(), spec_id=spec_id, ecosystem=ecosystem
        )
        for parsed in parsed_tasks:
            subtasks[parsed.task_id] = SubTask(
                id=parsed.task_id,
                repo=parsed.repo,
                branch=parsed.branch,
                status=TaskState.APPROVED if parsed.checked else TaskState.PENDING,
                sub_spec_path=str(file_path),
            )

    if not subtasks:
        subtasks["task-1"] = SubTask(
            id="task-1",
            repo=origin_module,
            branch=build_branch(
                ecosystem, resolve_short_spec_id(spec_id), origin_module
            ),
            wave=1,
            sub_spec_path=str(file_path),
        )

    return subtasks


def extract_prompts_from_spec(
    frontmatter: dict[str, Any],
    raw_text: str,
) -> list[str]:
    """Extrai os nomes dos prompts declarados no frontmatter ou corpo da spec.

    Args:
        frontmatter: Metadados YAML da spec.
        raw_text: Texto completo da spec.

    Returns:
        Lista de nomes de prompts governados.
    """
    raw_prompts = frontmatter.get("prompts", [])
    extracted_prompts: list[str] = []
    if isinstance(raw_prompts, list):
        for p_item in raw_prompts:
            if isinstance(p_item, dict) and p_item.get("name"):
                extracted_prompts.append(str(p_item["name"]))
            elif p_item and not isinstance(p_item, dict):
                extracted_prompts.append(str(p_item))
    elif isinstance(raw_prompts, str) and raw_prompts.strip():
        extracted_prompts.append(raw_prompts.strip())

    return extracted_prompts


def resolve_spec_ecosystem(
    frontmatter: dict[str, Any], manifest_path: Path | None
) -> str:
    """Resolve o namespace do ecossistema da spec (SPEC-007/008).

    O frontmatter `ecosystem` tem precedência; na ausência, deriva do
    diretório do spec-hub (ex: `harness-spec-hub` → `harness`).

    Args:
        frontmatter: Metadados YAML da spec.
        manifest_path: Caminho do `manifest.yaml` do spec-hub, se conhecido.

    Returns:
        Nome curto do ecossistema (string vazia quando indeterminável).
    """
    declared = str(frontmatter.get("ecosystem") or "")
    if declared:
        return declared
    if (
        manifest_path is not None
        and manifest_path.parent.name.endswith("-spec-hub")
    ):
        return derive_ecosystem_from_repo(manifest_path.parent.name)
    return ""


def parse_spec_with_waves(
    file_path: Path,
    manifest_path: Path | None = None,
    author: str = "local-dev",
) -> SpecRun:
    """Lê uma especificação em `<modulo>/specs/SPEC-XXX.md` e calcula suas ondas.

    Args:
        file_path: Caminho para o arquivo da especificação.
        manifest_path: Caminho opcional para o `manifest.yaml` do spec-hub.
        author: Autor ou identificador do planejador.

    Returns:
        Instância de `SpecRun` populada com metadados DDD e tarefas ordenadas por onda.
    """
    raw_text = file_path.read_text(encoding="utf-8")
    frontmatter, body = extract_yaml_frontmatter(raw_text)

    spec_id, title = resolve_spec_id_and_title(frontmatter, body, file_path)

    raw_product = frontmatter.get("product", [])
    if isinstance(raw_product, str):
        products = [raw_product]
    elif isinstance(raw_product, list):
        products = [str(item) for item in raw_product]
    else:
        products = []

    capability = str(frontmatter.get("capability") or "")
    scope = str(frontmatter.get("scope") or "platform")
    origin_module = resolve_spec_origin_module(frontmatter, file_path)

    if manifest_path is None:
        from harness_state.workspace import find_manifest_path

        manifest_path = find_manifest_path(workspace_root=file_path.resolve().parent)

    ecosystem = resolve_spec_ecosystem(frontmatter, manifest_path)

    subtasks = extract_initial_subtasks(
        frontmatter, body, spec_id, origin_module, file_path, ecosystem
    )

    dep_map = load_manifest_dependencies(manifest_path)
    if dep_map:
        subtasks = calculate_waves(subtasks, dep_map)
    else:
        for tid, task in subtasks.items():
            task.wave = calculate_task_wave(tid, subtasks, set())
        subtasks = dict(
            sorted(subtasks.items(), key=lambda item: (item[1].wave, item[0]))
        )

    declared_status = str(frontmatter.get("status") or "APPROVED")
    extracted_prompts = extract_prompts_from_spec(frontmatter, raw_text)

    return SpecRun(
        spec_id=spec_id,
        title=title,
        author=author,
        product=products,
        capability=capability,
        scope=scope,
        origin_module=origin_module,
        declared_status=declared_status,
        tasks=subtasks,
        prompts=extracted_prompts,
    )


def default_verify_runner(project_root: Path) -> tuple[int, str]:
    """Executa o pipeline semi-automatizado `just verify` no módulo alvo.

    Args:
        project_root: Diretório raiz do pacote local.

    Returns:
        Tupla contendo `(returncode, output_text)`.
    """
    sensor_script = project_root / ".harness" / "sensors" / "format_feedback.sh"
    cmd = (
        [str(sensor_script), "verify", "--", "just", "verify"]
        if sensor_script.is_file()
        else ["just", "verify"]
    )
    proc = subprocess.run(
        cmd,
        cwd=project_root,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        check=False,
    )
    output = (proc.stdout + "\n" + proc.stderr).strip()
    return proc.returncode, output


AgentRunnerCallback = Callable[
    [DetectedAgent, Path, SubTask, Path, str], tuple[int, str]
]
JudgeEvaluatorCallback = Callable[[Path, Path, str], JudgeEvaluation]


class HarnessOrchestrator:
    """Motor de esteira guiado por estado (`harness spec run`) local e remoto."""

    def __init__(
        self,
        project_root: Path,
        store: StateStoreProtocol | None = None,
        spec_hub_dir: Path | None = None,
        verify_runner: Callable[[Path], tuple[int, str]] | None = None,
        agent_runner: AgentRunnerCallback | None = None,
        config: HarnessLocalConfig | None = None,
        config_path: Path | None = None,
        tunnel_manager: SSHTunnelManager | None = None,
        confirm_close_callback: Callable[[SpecRun, list[dict]], bool] | None = None,
        confirm_approve_callback: Callable[[SpecRun, Path], bool] | None = None,
        github_client: Any | None = None,
        judge_evaluator: JudgeEvaluatorCallback | None = None,
    ) -> None:
        """Inicializa o orquestrador de esteira SDD.

        Args:
            project_root: Raiz do módulo local.
            store: Instância opcional de `StateStoreProtocol` (Redis ou memória).
            spec_hub_dir: Caminho opcional para o repositório `<project>-spec-hub`.
            verify_runner: Callback opcional para execução do `just verify`.
            agent_runner: Callback opcional para acionamento do agente de IA de código.
            config: Configuração local do Harness; se omitida, é lida do disco.
            config_path: Caminho opcional explícito do `config.yaml`.
            tunnel_manager: Gerenciador do túnel SSH para abertura automática.
            confirm_close_callback: Callback opcional para aprovação interativa
                do Gate 5.
            confirm_approve_callback: Callback opcional para aprovação interativa
                do Gate 2 quando a spec está em DRAFT.
            github_client: Cliente opcional da API do GitHub para fechamento
                transacional.
            judge_evaluator: Callback opcional para avaliação de conformidade LLM.
        """
        self.project_root = project_root.resolve()
        if config is not None:
            self.config = config
            self.config_path = config_path
        else:
            try:
                self.config, self.config_path = load_harness_config(
                    project_root=self.project_root,
                    explicit_path=config_path,
                    ensure_exists=False,
                )
            except ConfigurationError:
                self.config = HarnessLocalConfig()
                self.config_path = None
        self.tunnel_manager = tunnel_manager or SSHTunnelManager()
        self.store: StateStoreProtocol = store or StateStore()
        self.spec_hub_dir = (
            spec_hub_dir.resolve()
            if spec_hub_dir is not None
            else self._discover_spec_hub()
        )
        self.verify_runner = verify_runner or default_verify_runner
        self.agent_runner = agent_runner or AgentRunner().run
        self.confirm_close_callback = confirm_close_callback
        self.confirm_approve_callback = confirm_approve_callback
        self.github_client = github_client
        self.judge_evaluator = judge_evaluator

    def _discover_spec_hub(self) -> Path | None:
        """Localiza o diretório `<project>-spec-hub` no workspace pai ou local.

        Returns:
            Path para o spec-hub encontrado ou None.
        """
        rel_cfg = self.config.spec_hub.local_relative_path
        if rel_cfg:
            configured_candidate = (self.project_root / rel_cfg).resolve()
            if configured_candidate.is_dir():
                return configured_candidate

        for candidate in (
            sorted(self.project_root.iterdir()) if self.project_root.is_dir() else []
        ):
            if candidate.is_dir() and candidate.name.endswith("-spec-hub"):
                return candidate

        parent = self.project_root.parent
        for candidate in sorted(parent.iterdir()) if parent.is_dir() else []:
            if candidate.is_dir() and candidate.name.endswith("-spec-hub"):
                return candidate
        return None

    def resolve_manifest_path(
        self, explicit_manifest: Path | None = None
    ) -> Path | None:
        """Resolve o caminho do arquivo `manifest.yaml` no spec-hub.

        Args:
            explicit_manifest: Caminho fornecido explicitamente.

        Returns:
            Path válido para `manifest.yaml` ou None.
        """
        if explicit_manifest is not None and explicit_manifest.is_file():
            return explicit_manifest
        if self.spec_hub_dir is not None:
            candidate = self.spec_hub_dir / "manifest.yaml"
            if candidate.is_file():
                return candidate
        return None

    def resolve_target_repo_dir(self, repo_slug: str) -> Path:
        """Resolve o diretório local do repositório alvo da tarefa.

        Args:
            repo_slug: Identificador ou slug do repositório (ex: paralax-ia/crm).

        Returns:
            Path para a raiz do repositório local.
        """
        short_name = repo_slug.split("/")[-1]
        if self.project_root.name == short_name:
            return self.project_root

        candidate = self.project_root / short_name
        if candidate.is_dir():
            return candidate

        sibling = self.project_root.parent / short_name
        if sibling.is_dir():
            return sibling

        return self.project_root

    def check_dependencies_release(
        self, spec: SpecRun, task: SubTask
    ) -> tuple[SubTask, str, str | None] | None:
        """Verifica se todas as dependências da tarefa possuem release válida publicada.

        A versão só é atualizada no repositório da dependência quando o PR é aprovado
        e mergeado em main. Caso a última release válida não atinja a versão esperada,
        a tarefa dependente deve permanecer aguardando a release.

        Args:
            spec: Especificação contendo todas as subtarefas.
            task: Subtarefa que está sendo avaliada para execução.

        Returns:
            Tupla `(dep_task, expected_version, latest_release_tag)` se alguma
            dependência estiver bloqueada aguardando release, ou None se todas
            as dependências estiverem satisfeitas.
        """
        if not task.depends_on:
            return None

        for dep_id in task.depends_on:
            dep_task = spec.tasks.get(dep_id)
            if dep_task is None:
                continue

            dep_repo_dir = self.resolve_target_repo_dir(dep_task.repo)
            expected_ver = dep_task.expected_version or get_repo_declared_version(
                dep_repo_dir
            )
            if not expected_ver:
                continue

            sync_repo_release_tags(dep_repo_dir)
            latest_tag = get_repo_latest_release_tag(dep_repo_dir)
            if not is_dependency_release_satisfied(expected_ver, latest_tag):
                return dep_task, expected_ver, latest_tag

        return None

    def _reconnect_tunnel(self, ci_mode: bool = False) -> bool:
        """Força a reabertura do túnel SSH para o Redis fechando processos antigos.

        Args:
            ci_mode: Se True, não abre túnel (modo Cloud).

        Returns:
            True se o túnel estiver ativo, False caso contrário.
        """
        status = self.tunnel_manager.ensure_tunnel(
            config=self.config,
            ci_mode=ci_mode,
            force_reconnect=True,
        )
        return status.active

    def _evaluate_gate2_draft_status(
        self,
        parsed_spec: SpecRun,
        spec_path: Path,
        ci_mode: bool,
        tunnel_status: TunnelStatus | None,
    ) -> PipelineStepOutcome | None:
        """Avalia o Gate 2 caso a especificação esteja com status `DRAFT`.

        Args:
            parsed_spec: Especificação carregada.
            spec_path: Caminho do arquivo da spec.
            ci_mode: Indica modo CI/Cloud.
            tunnel_status: Status do túnel SSH.

        Returns:
            `PipelineStepOutcome` de bloqueio caso continue DRAFT, ou None se aprovada.
        """
        if parsed_spec.declared_status.upper() != "DRAFT" or ci_mode:
            return None

        approved_now = (
            self.confirm_approve_callback(parsed_spec, spec_path)
            if self.confirm_approve_callback is not None
            else False
        )
        if approved_now and approve_spec(spec_path, workspace_root=self.project_root):
            parsed_spec.declared_status = "APPROVED"
            refreshed = parse_spec_with_waves(spec_path)
            if refreshed.prompts:
                parsed_spec.prompts = refreshed.prompts
            if self.spec_hub_dir is not None and self.spec_hub_dir.is_dir():
                DomainInspector().update_spec_status(
                    spec_hub_dir=self.spec_hub_dir,
                    spec_id=parsed_spec.spec_id,
                    new_status="APPROVED",
                )
            console.print(
                f"  • [bold green]✓[/bold green] Especificação "
                f"[bold cyan]{parsed_spec.spec_id}[/bold cyan] aprovada "
                "(Gate 2 concluído). Prosseguindo execução..."
            )
            return None

        msg = (
            f"Gate 2 (Aprovação de Spec): A especificação "
            f"{parsed_spec.spec_id} está com status DRAFT. A esteira só "
            "inicia após a aprovação formal da especificação.\n"
            "Para aprovar a especificação, execute: "
            f"harness spec approve {spec_path}"
        )
        return PipelineStepOutcome(
            spec_id=parsed_spec.spec_id,
            active_task_id=None,
            active_repo=None,
            wave=0,
            task_status=TaskState.PENDING,
            feedback=msg,
            tunnel_status=tunnel_status,
            gate_waiting="Gate 2: Aprovação Formal da Especificação (DRAFT)",
            is_draft_blocked=True,
        )

    async def _fanout_and_persist_spec_state(
        self,
        spec_path: Path,
        ws_root: Path,
        active_spec: SpecRun,
        existing_is_none: bool,
        resolved_manifest: Path | None,
        ci_mode: bool,
        prompts_updated: bool = False,
    ) -> None:
        """Executa o fanout cirúrgico de sub-specs, abre PR no hub e salva no store.

        Args:
            spec_path: Caminho da spec principal.
            ws_root: Diretório raiz do workspace.
            active_spec: Instância ativa de `SpecRun`.
            existing_is_none: True se a spec ainda não existia no store.
            resolved_manifest: Caminho do `manifest.yaml`.
            ci_mode: Indica modo CI/Cloud.
            prompts_updated: Se True, indica que a lista de prompts foi atualizada.
        """
        saved_specs = fanout_all_repository_specs(
            main_spec_path=spec_path,
            workspace_root=ws_root,
            main_spec=active_spec,
            manifest_path=resolved_manifest,
        )
        if self.spec_hub_dir is not None and not ci_mode:
            hub_pr_num, hub_pr_url, hub_pr_msg = publish_spec_hub_pr(
                spec_hub_dir=self.spec_hub_dir,
                spec_path=spec_path,
                spec_id=active_spec.spec_id,
                spec_title=active_spec.title,
            )
            if hub_pr_num is not None:
                active_spec.hub_pr_number = hub_pr_num
                active_spec.hub_pr_url = hub_pr_url
            if hub_pr_url:
                console.print(
                    f"  • [bold green]✓ Spec Hub PR:[/bold green] {hub_pr_msg}"
                )
        if existing_is_none or prompts_updated or active_spec.hub_pr_number is not None:
            for task in active_spec:
                if task.repo in saved_specs:
                    saved_sub_spec = saved_specs[task.repo]
                    task.sub_spec_path = f"specs/{saved_sub_spec.name}"
            await self.store.save_spec(active_spec)

    async def _mark_satisfied_dependencies_approved(
        self,
        active_spec: SpecRun,
        next_task: SubTask,
    ) -> None:
        """Marca dependências satisfeitas da tarefa como `APPROVED` e `IMPLEMENTED`.

        Args:
            active_spec: Especificação ativa.
            next_task: Tarefa prestes a iniciar execução.
        """
        for dep_id in next_task.depends_on:
            dep_subtask = active_spec.tasks.get(dep_id)
            if not dep_subtask:
                continue
            if dep_subtask.status != TaskState.APPROVED:
                await self.store.update_task_status(
                    spec_id=active_spec.spec_id,
                    task_id=dep_id,
                    status=TaskState.APPROVED,
                )
            dep_repo_dir = self.resolve_target_repo_dir(dep_subtask.repo)
            if dep_repo_dir.is_dir():
                mark_repo_spec_status(
                    repo_dir=dep_repo_dir,
                    spec_id=active_spec.spec_id,
                    new_status="IMPLEMENTED",
                )

    def _sync_wave_consumer_dependencies(
        self,
        active_spec: SpecRun,
        next_task: SubTask,
        target_repo_dir: Path,
    ) -> None:
        """Sincroniza pacotes dependentes no spoke consumidor quando em Onda 2+.

        Args:
            active_spec: Especificação ativa.
            next_task: Tarefa atual.
            target_repo_dir: Diretório local do spoke.
        """
        if next_task.wave <= 1 or not next_task.depends_on:
            return
        for dep_id in next_task.depends_on:
            dep_subtask = active_spec.tasks.get(dep_id)
            if dep_subtask:
                sync_consumer_dependency(target_repo_dir, dep_subtask.repo)

    def _pull_ssot_prompts_before_agent(
        self,
        active_spec: SpecRun,
        target_repo_dir: Path,
    ) -> None:
        """Sincroniza os prompts declarados a partir do Langfuse SSOT antes do agente.

        Args:
            active_spec: Especificação ativa.
            target_repo_dir: Diretório local do spoke.
        """
        if not active_spec.prompts:
            return
        prompt_mgr = LangfusePromptManager()
        if not prompt_mgr.is_configured:
            return
        ssot_pulled = pull_prompts_from_langfuse_ssot(
            project_root=target_repo_dir,
            prompt_manager=prompt_mgr,
            target_prompts=active_spec.prompts,
        )
        for p_name, p_ver, p_file in ssot_pulled:
            console.print(
                f"  • [bold green]✓[/bold green] Langfuse SSOT: Prompt "
                f"'{p_name}' (v{p_ver}) sincronizado em {p_file} "
                "antes da iteração."
            )

    def _run_agent_verify_loop(
        self,
        active_spec: SpecRun,
        next_task: SubTask,
        target_repo_dir: Path,
        spec_path: Path,
        selected_agent: DetectedAgent | None,
        was_already_in_progress: bool,
        max_iterations: int,
    ) -> tuple[int, str]:
        """Executa o loop de implementação do agente e verificação com sensores.

        Args:
            active_spec: Especificação ativa.
            next_task: Subtarefa atual.
            target_repo_dir: Diretório local do spoke.
            spec_path: Caminho da spec principal.
            selected_agent: Agente de IA selecionado.
            was_already_in_progress: Indica se a tarefa já estava `IN_PROGRESS`.
            max_iterations: Limite de iterações agente-sensor.

        Returns:
            Tupla `(exit_code, output)`.
        """
        if was_already_in_progress:
            pre_code, pre_output = self.verify_runner(target_repo_dir)
            if pre_code == 0:
                console.print(
                    "\n[bold green]✓[/bold green] Sensores já aprovados "
                    f"(`just verify`) em [dim]{target_repo_dir.name}[/dim]! "
                    "Aproveitando código existente sem acionar o agente."
                )
                return 0, pre_output

        if selected_agent is None or self.agent_runner is None:
            return self.verify_runner(target_repo_dir)

        self._pull_ssot_prompts_before_agent(active_spec, target_repo_dir)

        code = 1
        output = ""
        current_feedback = ""
        for iteration in range(1, max_iterations + 1):
            model_label = (
                f" [dim](modelo: {selected_agent.default_model})[/dim]"
                if selected_agent.default_model
                else ""
            )
            console.print(
                f"\n[bold blue]🤖 [Iteração {iteration}/{max_iterations}]"
                "[/bold blue] "
                f"Acionando agente: [bold green]{selected_agent.name}"
                f"[/bold green]{model_label}..."
            )
            agent_code, agent_output = self.agent_runner(
                selected_agent,
                target_repo_dir,
                next_task,
                spec_path,
                current_feedback,
            )
            if agent_code != 0:
                return agent_code, agent_output

            console.print(
                f"\n[bold cyan]🔍 [Iteração {iteration}][/bold cyan] "
                f"Executando sensores de validação (`just verify`) em "
                f"[dim]{target_repo_dir.name}[/dim]..."
            )
            code, output = self.verify_runner(target_repo_dir)
            if code == 0:
                console.print(
                    f"[bold green]✓[/bold green] Sensores aprovados na "
                    f"iteração {iteration}!"
                )
                return 0, output
            current_feedback = output

        return code, output

    def _finalize_completed_spec_spokes(
        self,
        final_spec: SpecRun,
        spec_path: Path,
    ) -> bool:
        """Marca as sub-specs dos spokes como `IMPLEMENTED` e reconcilia com o hub.

        Args:
            final_spec: Especificação com todas as tarefas concluídas.
            spec_path: Caminho da spec central.

        Returns:
            True se o spec-hub foi sincronizado.
        """
        if not final_spec.is_complete:
            return False
        for completed_task in final_spec:
            c_repo_dir = self.resolve_target_repo_dir(completed_task.repo)
            if c_repo_dir.is_dir():
                mark_repo_spec_status(
                    repo_dir=c_repo_dir,
                    spec_id=final_spec.spec_id,
                    new_status="IMPLEMENTED",
                )
                sub_spec_file = c_repo_dir / "specs" / f"{final_spec.spec_id}.md"
                if sub_spec_file.is_file():
                    sync_spoke_spec_to_hub(
                        spoke_spec_path=sub_spec_file,
                        hub_spec_path=spec_path,
                    )
        return self._sync_spec_hub_if_complete(final_spec)

    def _prepare_task_workspace_and_issue(
        self,
        active_spec: SpecRun,
        next_task: SubTask,
        spec_path: Path,
        ci_mode: bool,
    ) -> tuple[Path, int | None, str | None]:
        """Prepara o diretório local da tarefa, gera sub-spec e garante Issue no GitHub.

        Args:
            active_spec: Especificação ativa.
            next_task: Subtarefa atual.
            spec_path: Caminho da spec central.
            ci_mode: Indica modo CI/Cloud.

        Returns:
            Tupla `(target_repo_dir, issue_num, issue_url)`.
        """
        target_repo_dir = self.resolve_target_repo_dir(next_task.repo)
        install_module_harness(project_root=target_repo_dir, ci_mode=ci_mode)
        self._sync_wave_consumer_dependencies(active_spec, next_task, target_repo_dir)
        ensure_working_branch(target_repo_dir, next_task.branch)

        repo_spec_text = generate_repo_spec(
            main_spec_path=spec_path,
            repo_name=next_task.repo,
            task=next_task,
            tasks=[t for t in active_spec.tasks.values() if t.repo == next_task.repo],
            main_spec=active_spec,
        )
        saved_sub_spec = save_repo_spec(
            repo_dir=target_repo_dir,
            spec_id=active_spec.spec_id,
            content=repo_spec_text,
            task_id=next_task.id,
        )
        sub_spec_rel_path = f"specs/{saved_sub_spec.name}"
        next_task.sub_spec_path = sub_spec_rel_path

        issue_num, issue_url = ensure_task_issue(
            repo_dir=target_repo_dir,
            spec_id=active_spec.spec_id,
            task_id=next_task.id,
            task_title=active_spec.title,
            wave=next_task.wave,
            depends_on=next_task.depends_on,
            expected_version=next_task.expected_version,
            sub_spec_path=sub_spec_rel_path,
            sub_spec_content=repo_spec_text,
            ci_mode=ci_mode,
        )
        if issue_num is not None:
            next_task.issue_number = issue_num
            next_task.issue_url = issue_url

        return target_repo_dir, issue_num, issue_url

    def _build_ready_step_outcome(
        self,
        final_spec: SpecRun,
        next_task: SubTask,
        hub_synced: bool,
        output: str,
        tunnel_status: TunnelStatus | None,
        pr_num: int | None,
        pr_url: str | None,
    ) -> PipelineStepOutcome:
        """Constrói o `PipelineStepOutcome` final quando a tarefa atinge `READY`.

        Args:
            final_spec: Especificação atualizada.
            next_task: Tarefa concluída nesta rodada.
            hub_synced: Indica se o spec-hub foi sincronizado.
            output: Saída de verificação.
            tunnel_status: Status do túnel SSH.
            pr_num: Número do PR aberto.
            pr_url: URL do PR aberto.

        Returns:
            Instância de `PipelineStepOutcome`.
        """
        next_unblocked = (
            None if final_spec.is_complete else final_spec.get_next_unblocked_task()
        )
        next_task_id = next_unblocked.id if next_unblocked is not None else None
        next_repo = next_unblocked.repo if next_unblocked is not None else None
        next_wave = next_unblocked.wave if next_unblocked is not None else None
        blocked_by_dep = None
        expected_release = None
        latest_release = None
        if next_unblocked is not None:
            dep_block = self.check_dependencies_release(final_spec, next_unblocked)
            if dep_block is not None:
                dep_task, expected_release, latest_release = dep_block
                blocked_by_dep = dep_task.repo

        return PipelineStepOutcome(
            spec_id=final_spec.spec_id,
            active_task_id=next_task.id,
            active_repo=next_task.repo,
            wave=next_task.wave,
            task_status=TaskState.READY,
            all_waves_complete=final_spec.is_complete,
            hub_synced=hub_synced,
            feedback=output,
            tunnel_status=tunnel_status,
            next_task_id=next_task_id,
            next_repo=next_repo,
            next_wave=next_wave,
            blocked_by_dep=blocked_by_dep,
            expected_release=expected_release,
            latest_release=latest_release,
            pr_number=pr_num,
            pr_url=pr_url,
            issue_number=next_task.issue_number,
            issue_url=next_task.issue_url,
            gate_waiting="Gate 3: Revisão Humana de Código (Merge do PR)",
        )

    def _publish_task_pr_if_local(
        self,
        target_repo_dir: Path,
        active_spec: SpecRun,
        next_task: SubTask,
        spec_path: Path,
        ci_mode: bool,
    ) -> tuple[int | None, str | None]:
        """Publica o Pull Request da subtarefa e reconecta o túnel se em modo local.

        Args:
            target_repo_dir: Diretório local do spoke.
            active_spec: Especificação ativa.
            next_task: Subtarefa concluída.
            spec_path: Caminho da spec central.
            ci_mode: Indica modo CI/Cloud.

        Returns:
            Tupla `(pr_num, pr_url)`.
        """
        if ci_mode:
            return None, None
        pr_num, pr_url, pr_msg = publish_task_pr(
            repo_dir=target_repo_dir,
            spec_id=active_spec.spec_id,
            branch_name=next_task.branch,
            spec_title=active_spec.title,
            sub_spec_path=next_task.sub_spec_path or str(spec_path),
            issue_number=next_task.issue_number,
        )
        if pr_msg:
            console.print(
                f"  • [bold blue]Entrega de Código (Gate 3):[/bold blue] {pr_msg}"
            )
        self.tunnel_manager.ensure_tunnel(config=self.config, ci_mode=ci_mode)
        return pr_num, pr_url

    async def _execute_active_task_step(
        self,
        active_spec: SpecRun,
        next_task: SubTask,
        spec_path: Path,
        ci_mode: bool,
        auto_verify: bool,
        worker_id: str,
        selected_agent: DetectedAgent | None,
        max_iterations: int,
        tunnel_status: TunnelStatus | None,
    ) -> PipelineStepOutcome:
        """Executa o fluxo completo de uma tarefa desbloqueada na esteira.

        Args:
            active_spec: Especificação ativa.
            next_task: Tarefa desbloqueada selecionada.
            spec_path: Caminho da spec central.
            ci_mode: Indica modo CI/Cloud.
            auto_verify: Se True, roda o loop agente-sensor.
            worker_id: Identificador do executor.
            selected_agent: Agente de IA selecionado.
            max_iterations: Limite de iterações.
            tunnel_status: Status do túnel SSH.

        Returns:
            `PipelineStepOutcome` da execução da tarefa.
        """
        blocked_dep = self.check_dependencies_release(active_spec, next_task)
        if blocked_dep is not None:
            dep_task, exp_ver, latest_tag = blocked_dep
            dep_label = latest_tag if latest_tag else "nenhuma"
            msg = (
                f"Tarefa {next_task.id} (Onda {next_task.wave} em "
                f"{next_task.repo}) aguardando release da dependência "
                f"'{dep_task.repo}' ({dep_task.id}): versão esperada {exp_ver} "
                f"vs última release válida {dep_label}. A versão só é "
                "atualizada quando o PR é aprovado e mergeado em main."
            )
            return PipelineStepOutcome(
                spec_id=active_spec.spec_id,
                active_task_id=next_task.id,
                active_repo=next_task.repo,
                wave=next_task.wave,
                task_status=TaskState.PENDING,
                all_waves_complete=False,
                hub_synced=False,
                feedback=msg,
                tunnel_status=tunnel_status,
                next_task_id=next_task.id,
                next_repo=next_task.repo,
                next_wave=next_task.wave,
                blocked_by_dep=dep_task.repo,
                expected_release=exp_ver,
                latest_release=latest_tag,
            )

        await self._mark_satisfied_dependencies_approved(active_spec, next_task)

        target_repo_dir, issue_num, issue_url = self._prepare_task_workspace_and_issue(
            active_spec, next_task, spec_path, ci_mode
        )

        was_already_in_progress = next_task.status == TaskState.IN_PROGRESS
        await self.store.update_task_status(
            spec_id=active_spec.spec_id,
            task_id=next_task.id,
            status=TaskState.IN_PROGRESS,
            worker_id=worker_id,
            issue_number=issue_num,
            issue_url=issue_url,
        )

        if not auto_verify:
            msg = (
                f"Pronto para implementar {next_task.repo} "
                f"na branch {next_task.branch}."
            )
            return PipelineStepOutcome(
                spec_id=active_spec.spec_id,
                active_task_id=next_task.id,
                active_repo=next_task.repo,
                wave=next_task.wave,
                task_status=TaskState.IN_PROGRESS,
                all_waves_complete=False,
                hub_synced=False,
                feedback=msg,
                tunnel_status=tunnel_status,
            )

        code, output = self._run_agent_verify_loop(
            active_spec=active_spec,
            next_task=next_task,
            target_repo_dir=target_repo_dir,
            spec_path=spec_path,
            selected_agent=selected_agent,
            was_already_in_progress=was_already_in_progress,
            max_iterations=max_iterations,
        )
        if code != 0:
            return PipelineStepOutcome(
                spec_id=active_spec.spec_id,
                active_task_id=next_task.id,
                active_repo=next_task.repo,
                wave=next_task.wave,
                task_status=TaskState.IN_PROGRESS,
                all_waves_complete=False,
                hub_synced=False,
                feedback=output,
                tunnel_status=tunnel_status,
                issue_number=next_task.issue_number,
                issue_url=next_task.issue_url,
            )

        if active_spec.prompts:
            sync_modified_prompts_as_draft(
                project_root=target_repo_dir,
                target_prompts=active_spec.prompts,
            )

        prompt_sensor = PromptGovernanceSensor(project_root=target_repo_dir)
        prompt_violations = prompt_sensor.validate(declared_prompts=active_spec.prompts)
        if prompt_violations:
            prompt_err = "\n".join(v.format_output() for v in prompt_violations)
            console.print(
                "\n[bold red]🛑 Violação de Governança de Prompts (SPEC-PROMPT-01):"
                f"[/bold red]\n{prompt_err}"
            )
            return PipelineStepOutcome(
                spec_id=active_spec.spec_id,
                active_task_id=next_task.id,
                active_repo=next_task.repo,
                wave=next_task.wave,
                task_status=TaskState.IN_PROGRESS,
                all_waves_complete=False,
                hub_synced=False,
                feedback=prompt_err,
                tunnel_status=tunnel_status,
                issue_number=next_task.issue_number,
                issue_url=next_task.issue_url,
            )

        pr_num, pr_url = self._publish_task_pr_if_local(
            target_repo_dir, active_spec, next_task, spec_path, ci_mode
        )
        declared_ver = get_repo_declared_version(target_repo_dir)
        updated_spec = await self.store.update_task_status(
            spec_id=active_spec.spec_id,
            task_id=next_task.id,
            status=TaskState.READY,
            worker_id=worker_id,
            expected_version=declared_ver,
            pr_number=pr_num,
            issue_number=next_task.issue_number,
            issue_url=next_task.issue_url,
        )
        final_spec = updated_spec or active_spec
        hub_synced = self._finalize_completed_spec_spokes(final_spec, spec_path)

        return self._build_ready_step_outcome(
            final_spec=final_spec,
            next_task=next_task,
            hub_synced=hub_synced,
            output=output,
            tunnel_status=tunnel_status,
            pr_num=pr_num,
            pr_url=pr_url,
        )

    async def run_pipeline(
        self,
        spec_path: Path,
        manifest_path: Path | None = None,
        ci_mode: bool = False,
        auto_verify: bool = True,
        worker_id: str = "local-orchestrator",
        selected_agent: DetectedAgent | None = None,
        max_iterations: int = 10,
        closure_only: bool = False,
    ) -> PipelineStepOutcome:
        """Executa a máquina de estados (`init` -> `plan` -> `agent` -> `verify`).

        Args:
            spec_path: Caminho da especificação em `<modulo>/specs/SPEC-XXX.md`.
            manifest_path: Caminho opcional do `manifest.yaml`.
            ci_mode: Indica se está rodando em modo CI/Cloud desatendido.
            auto_verify: Se True, roda a etapa `verify` e avança o estado para `READY`.
            worker_id: Identificador do executor atual.
            selected_agent: Agente de IA opcional selecionado para a tarefa.
            max_iterations: Número máximo de iterações do loop contínuo de resolução.
            closure_only: Se True, NÃO executa o agente — exige que todas as
                ondas estejam concluídas e dispara apenas o fechamento
                transacional (Gate 5). Se houver tarefas desbloqueadas, retorna
                um outcome indicando que a spec não está pronta para fechar.

        Returns:
            `PipelineStepOutcome` descrevendo o resultado da rodada.
        """
        applied_env = apply_config_to_environment(
            config=self.config,
            config_path=self.config_path,
            ci_mode=ci_mode,
            port_checker=self.tunnel_manager.port_checker,
        )
        if isinstance(self.store, StateStore):
            self.store.redis_url = applied_env["HARNESS_REDIS_URL"]
            self.store.reconnect_hook = lambda: self._reconnect_tunnel(ci_mode=ci_mode)

        tunnel_status = self.tunnel_manager.ensure_tunnel(
            config=self.config, ci_mode=ci_mode
        )

        resolved_manifest = self.resolve_manifest_path(manifest_path)
        if self.spec_hub_dir is None and resolved_manifest is not None:
            self.spec_hub_dir = resolved_manifest.parent
        is_ws_root = (
            self.spec_hub_dir is not None
            and self.spec_hub_dir.resolve().parent == self.project_root.resolve()
        ) or self.project_root.name == "paralax-ia"
        ws_root = self.project_root if is_ws_root else self.project_root.parent
        if resolved_manifest is not None and not ci_mode:
            preflight_spec_workspace(
                spec_path=spec_path,
                manifest_path=resolved_manifest,
                workspace_root=ws_root,
            )

        ensure_spec_has_prompts(
            spec_path=spec_path,
            workspace_root=ws_root,
            manifest_path=resolved_manifest,
        )

        parsed_spec = parse_spec_with_waves(
            spec_path, manifest_path=resolved_manifest, author=worker_id
        )

        draft_outcome = self._evaluate_gate2_draft_status(
            parsed_spec, spec_path, ci_mode, tunnel_status
        )
        if draft_outcome is not None:
            return draft_outcome

        async with self.store:
            existing = await self.store.get_spec(parsed_spec.spec_id)
            return await self._run_store_phase(
                parsed_spec=parsed_spec,
                existing=existing,
                spec_path=spec_path,
                ws_root=ws_root,
                resolved_manifest=resolved_manifest,
                ci_mode=ci_mode,
                auto_verify=auto_verify,
                worker_id=worker_id,
                selected_agent=selected_agent,
                max_iterations=max_iterations,
                tunnel_status=tunnel_status,
                closure_only=closure_only,
            )

    def _closure_blocked_outcome(
        self,
        active_spec: SpecRun,
        next_task: SubTask,
        tunnel_status: TunnelStatus | None,
    ) -> PipelineStepOutcome:
        """Monta o outcome de bloqueio do fechamento (`closure_only` + tarefa pendente).

        Args:
            active_spec: Especificação ativa no barramento.
            next_task: Próxima subtarefa desbloqueada que impede o fechamento.
            tunnel_status: Status do túnel SSH.

        Returns:
            `PipelineStepOutcome` indicando que o fechamento não foi executado.
        """
        return PipelineStepOutcome(
            spec_id=active_spec.spec_id,
            active_task_id=None,
            active_repo=None,
            wave=0,
            task_status=active_spec.status,
            all_waves_complete=False,
            hub_synced=False,
            feedback=(
                "Fechamento não executado: ainda há subtarefas desbloqueadas "
                f"pendentes ({next_task.id} em {next_task.repo}). Execute "
                "`harness spec run` para concluí-las antes de fechar."
            ),
            tunnel_status=tunnel_status,
        )

    async def _run_store_phase(
        self,
        parsed_spec: SpecRun,
        existing: SpecRun | None,
        spec_path: Path,
        ws_root: Path,
        resolved_manifest: Path | None,
        ci_mode: bool,
        auto_verify: bool,
        worker_id: str,
        selected_agent: DetectedAgent | None,
        max_iterations: int,
        tunnel_status: TunnelStatus | None,
        closure_only: bool,
    ) -> PipelineStepOutcome:
        """Executa a fase de store do pipeline: fanout, persistência e ação seguinte.

        Args:
            parsed_spec: Especificação parseada da rodada atual.
            existing: Especificação já persistida (ou None na primeira execução).
            spec_path: Caminho do arquivo da especificação.
            ws_root: Raiz do workspace resolvida.
            resolved_manifest: Caminho do `manifest.yaml` resolvido.
            ci_mode: Indica execução em CI/Cloud desatendido.
            auto_verify: Se True, avança para `READY` após `verify`.
            worker_id: Identificador do executor.
            selected_agent: Agente de IA opcional selecionado.
            max_iterations: Limite de iterações do loop de resolução.
            tunnel_status: Status do túnel SSH.
            closure_only: Se True, não executa o agente (apenas fechamento).

        Returns:
            `PipelineStepOutcome` da tarefa ativa, do fechamento ou do bloqueio.
        """
        prompts_updated = False
        if existing is not None:
            active_spec = existing
            if parsed_spec.prompts and parsed_spec.prompts != existing.prompts:
                active_spec.prompts = list(parsed_spec.prompts)
                prompts_updated = True
        else:
            active_spec = parsed_spec

        await self._fanout_and_persist_spec_state(
            spec_path=spec_path,
            ws_root=ws_root,
            active_spec=active_spec,
            existing_is_none=existing is None,
            resolved_manifest=resolved_manifest,
            ci_mode=ci_mode,
            prompts_updated=prompts_updated,
        )

        next_task = active_spec.get_next_unblocked_task()
        if next_task is not None and closure_only:
            return self._closure_blocked_outcome(active_spec, next_task, tunnel_status)
        if next_task is None:
            return await self._handle_no_unblocked_task(
                active_spec=active_spec,
                spec_path=spec_path,
                ci_mode=ci_mode,
                tunnel_status=tunnel_status,
                selected_agent=selected_agent,
            )

        return await self._execute_active_task_step(
            active_spec=active_spec,
            next_task=next_task,
            spec_path=spec_path,
            ci_mode=ci_mode,
            auto_verify=auto_verify,
            worker_id=worker_id,
            selected_agent=selected_agent,
            max_iterations=max_iterations,
            tunnel_status=tunnel_status,
        )

    async def _handle_no_unblocked_task(
        self,
        active_spec: SpecRun,
        spec_path: Path,
        ci_mode: bool,
        tunnel_status: TunnelStatus | None,
        selected_agent: DetectedAgent | None,
    ) -> PipelineStepOutcome:
        """Trata o cenário em que não há subtarefas desbloqueadas para execução.

        Args:
            active_spec: Especificação ativa no barramento.
            spec_path: Caminho do arquivo da especificação central.
            ci_mode: Indica se a execução ocorre em ambiente CI.
            tunnel_status: Status do túnel SSH para o Redis.
            selected_agent: Agente de IA opcional selecionado.

        Returns:
            PipelineStepOutcome correspondente ao encerramento ou deadlock identificado.
        """
        if active_spec.is_complete:
            if active_spec.status != TaskState.APPROVED:
                return await self.execute_closure_gate(
                    spec=active_spec,
                    spec_path=spec_path,
                    ci_mode=ci_mode,
                    tunnel_status=tunnel_status,
                    selected_agent=selected_agent,
                )

            hub_synced = self._sync_spec_hub_if_complete(active_spec)
            return PipelineStepOutcome(
                spec_id=active_spec.spec_id,
                active_task_id=None,
                active_repo=None,
                wave=0,
                task_status=active_spec.status,
                all_waves_complete=True,
                hub_synced=hub_synced,
                feedback="Todas as ondas já estão concluídas e aprovadas.",
                tunnel_status=tunnel_status,
            )

        pending_blocked = [
            f"{t.id} ({t.repo})"
            for t in active_spec.tasks.values()
            if t.status not in (TaskState.READY, TaskState.APPROVED)
        ]
        pending_desc = ", ".join(pending_blocked)
        return PipelineStepOutcome(
            spec_id=active_spec.spec_id,
            active_task_id=None,
            active_repo=None,
            wave=0,
            task_status=active_spec.status,
            all_waves_complete=False,
            hub_synced=False,
            feedback=(
                "Nenhuma subtarefa desbloqueada encontrada para execução, "
                f"porém a especificação possui tarefas pendentes: {pending_desc}."
            ),
            tunnel_status=tunnel_status,
        )

    def _sync_spec_hub_if_complete(self, spec: SpecRun) -> bool:
        """Sincroniza contratos e status `MERGED` no `<project>-spec-hub`.

        Args:
            spec: Especificação cujas ondas foram finalizadas.

        Returns:
            True se o `<project>-spec-hub` foi atualizado com sucesso.
        """
        if not spec.is_complete and spec.status != TaskState.APPROVED:
            return False
        if self.spec_hub_dir is None or not self.spec_hub_dir.is_dir():
            return False
        inspector = DomainInspector()
        ws_root = (
            self.project_root
            if self.spec_hub_dir.resolve().parent == self.project_root.resolve()
            else self.project_root.parent
        )
        inspector.sync_all(
            spec_hub_dir=self.spec_hub_dir,
            workspace_root=ws_root,
        )
        inspector.update_spec_status(
            spec_hub_dir=self.spec_hub_dir,
            spec_id=spec.spec_id,
            new_status="MERGED",
        )
        mark_repo_spec_status(
            repo_dir=self.spec_hub_dir,
            spec_id=spec.spec_id,
            new_status="MERGED",
        )
        return True

    def _collect_closure_tasks_metadata(
        self,
        spec: SpecRun,
    ) -> tuple[list[dict[str, Any]], list[tuple[str, int, str]]]:
        """Coleta metadados únicos de tarefas e lista de PRs para o Gate 5.

        Args:
            spec: Especificação ativa.

        Returns:
            Tupla `(tasks_info, collector_tasks)`.
        """
        seen_prs: set[tuple[str, int | None]] = set()
        tasks_info: list[dict[str, Any]] = []
        collector_tasks: list[tuple[str, int, str]] = []

        for task in spec.tasks.values():
            key = (task.repo, task.pr_number)
            if key in seen_prs:
                continue
            seen_prs.add(key)
            tasks_info.append(
                {
                    "task_id": task.id,
                    "repo": task.repo,
                    "pr_number": task.pr_number,
                    "issue_number": task.issue_number,
                    "branch": task.branch,
                    "wave": task.wave,
                    "status": (
                        task.status.value
                        if hasattr(task.status, "value")
                        else str(task.status)
                    ),
                }
            )
            if task.pr_number is not None:
                collector_tasks.append((task.repo, task.pr_number, task.id))

        return tasks_info, collector_tasks

    def _print_judge_failure_report(self, eval_res: JudgeEvaluation) -> str:
        """Exibe no console as violações e recomendações quando o Judge reprova.

        Args:
            eval_res: Resultado da avaliação do LLM-as-a-Judge.

        Returns:
            Mensagem de falha formatada.
        """
        if eval_res.violations:
            console.print("\n  [bold red]Violações Identificadas:[/bold red]")
            for v in eval_res.violations:
                console.print(f"    - [red]•[/red] {v}")
        if eval_res.recommendations:
            console.print("\n  [bold yellow]Recomendações de Correção:[/bold yellow]")
            for r in eval_res.recommendations:
                console.print(f"    - [yellow]•[/yellow] {r}")

        fail_msg = (
            f"Gate 5 Reprovado: O LLM-as-a-Judge avaliou a conformidade em "
            f"{eval_res.compliance_score}% (mínimo exigido: 90%). "
            "Corrija as violações apontadas e execute `harness spec run` novamente."
        )
        console.print(f"\n[bold red]❌ {fail_msg}[/bold red]\n")
        return fail_msg

    def _print_closure_deliverables(
        self,
        spec: SpecRun,
        tasks_info: list[dict[str, Any]],
    ) -> None:
        """Imprime a lista de prompts e PRs prontos para fechamento no Gate 5.

        Args:
            spec: Especificação ativa.
            tasks_info: Lista de dicionários de tarefas.
        """
        if spec.prompts:
            prompts_list = ", ".join(
                f"[bold yellow]{p}[/bold yellow]" for p in spec.prompts
            )
            console.print(
                "  • [bold cyan]Prompts para promoção no Langfuse:[/bold cyan] "
                f"{prompts_list}"
            )

        console.print(
            "\n  [bold]Entregas dos Repositórios Prontas para Merge "
            "Transacional:[/bold]"
        )
        for task_item in tasks_info:
            pr_label = (
                f"PR #{task_item['pr_number']}"
                if task_item.get("pr_number")
                else "Sem PR registrado"
            )
            issue_label = (
                f"Issue #{task_item['issue_number']}"
                if task_item.get("issue_number")
                else "Sem Issue"
            )
            console.print(
                f"    - [green]✓[/green] [bold]{task_item['repo']}[/bold] "
                f"(Onda {task_item['wave']}) ➔ {pr_label} | {issue_label} | "
                f"branch: `{task_item['branch']}`"
            )

    def _confirm_closure_gate_execution(
        self,
        spec: SpecRun,
        tasks_info: list[dict[str, Any]],
        ci_mode: bool,
    ) -> bool:
        """Solicita ou resolve a confirmação para o fechamento transacional do Gate 5.

        Args:
            spec: Especificação ativa.
            tasks_info: Lista de dicionários de tarefas.
            ci_mode: Indica modo CI/Cloud.

        Returns:
            True se confirmado.
        """
        if ci_mode:
            return True
        if self.confirm_close_callback is not None:
            return self.confirm_close_callback(spec, tasks_info)
        prompt_question = (
            "\n[bold yellow]Deseja realizar o fechamento transacional agora "
            "(merge de PRs, promoção de prompts no Langfuse para 'production' "
            "e sincronização do spec-hub)? [y/N]: [/bold yellow]"
        )
        confirm_input = console.input(prompt_question)
        return confirm_input.strip().lower() in ("y", "yes", "s", "sim")

    async def execute_closure_gate(
        self,
        spec: SpecRun,
        spec_path: Path,
        ci_mode: bool = False,
        tunnel_status: TunnelStatus | None = None,
        selected_agent: DetectedAgent | None = None,
    ) -> PipelineStepOutcome:
        """Executa a validação do Passo 5 (Cross-Repo Gate) e fechamento transacional.

        Args:
            spec: Especificação ativa contendo todas as tarefas concluídas.
            spec_path: Caminho do arquivo da especificação central.
            ci_mode: Se True, opera em modo headless / CI sem prompt interativo.
            tunnel_status: Estado do túnel SSH durante a execução.
            selected_agent: Agente de IA opcional selecionado para execução.

        Returns:
            PipelineStepOutcome com o resultado da avaliação e ações executadas.
        """
        tasks_info, collector_tasks = self._collect_closure_tasks_metadata(spec)

        console.print("\n[bold magenta]" + ("═" * 60) + "[/bold magenta]")
        console.print(
            f"[bold magenta]🛡️  Passo 5: Cross-Repo Harness Gate — "
            f"Avaliação Final ({spec.spec_id})[/bold magenta]"
        )
        console.print("[bold magenta]" + ("═" * 60) + "[/bold magenta]\n")

        gate_artifacts_dir = self.project_root / ".harness" / "gate_artifacts"
        gate_artifacts_dir.mkdir(parents=True, exist_ok=True)
        diffs_file = gate_artifacts_dir / f"{spec.spec_id}_all_diffs.patch"

        console.print(
            "[bold cyan]📦 Coletando diffs consolidados dos "
            "Pull Requests...[/bold cyan]"
        )
        collect_diffs(
            tasks=collector_tasks,
            spec_file=spec_path,
            diffs_out=diffs_file,
        )

        judge_model_to_use = (
            selected_agent.default_model
            if selected_agent is not None and selected_agent.default_model
            else None
        )
        model_hint = f" ({judge_model_to_use})" if judge_model_to_use else ""
        console.print(
            f"[bold cyan]🔍 Executando avaliação de conformidade "
            f"LLM-as-a-Judge com DeepEval{model_hint}...[/bold cyan]"
        )
        eval_res = (
            self.judge_evaluator(spec_path, diffs_file, spec.spec_id)
            if self.judge_evaluator is not None
            else evaluate_spec_diff(
                spec_path=spec_path,
                diffs_path=diffs_file,
                spec_id=spec.spec_id,
                model=judge_model_to_use or "",
            )
        )

        judge_score = (
            eval_res.compliance_score / 100.0
            if eval_res.compliance_score is not None
            else None
        )
        judge_status = eval_res.status
        judge_reason = eval_res.summary

        score_label = (
            f"{eval_res.compliance_score}%"
            if eval_res.compliance_score is not None
            else "skip (sem evidência de código)"
        )
        console.print(
            f"  • [bold cyan]Score de Conformidade (LLM-as-a-Judge):[/bold cyan] "
            f"[bold green]{score_label}[/bold green] ({judge_status})"
        )
        console.print(f"  • [bold cyan]Relatório do Judge:[/bold cyan] {judge_reason}")

        if judge_status != "APPROVED":
            fail_msg = self._print_judge_failure_report(eval_res)
            return PipelineStepOutcome(
                spec_id=spec.spec_id,
                active_task_id=None,
                active_repo=None,
                wave=0,
                task_status=spec.status,
                all_waves_complete=False,
                hub_synced=False,
                feedback=fail_msg,
                tunnel_status=tunnel_status,
                gate_waiting="Gate 5: Conformidade Insuficiente no LLM Judge",
                is_awaiting_closure=True,
                judge_score=judge_score,
            )

        self._print_closure_deliverables(spec, tasks_info)

        if not self._confirm_closure_gate_execution(spec, tasks_info, ci_mode):
            msg = (
                f"Passo 5 pendente: O operador optou por não fechar a "
                f"especificação {spec.spec_id} agora. A especificação e seus "
                "PRs permanecem abertos e validados no State Tracker. "
                "Execute `harness spec run` novamente quando desejar efetuar "
                "o fechamento transacional."
            )
            console.print(f"\n[bold yellow]⏸️  {msg}[/bold yellow]\n")
            return PipelineStepOutcome(
                spec_id=spec.spec_id,
                active_task_id=None,
                active_repo=None,
                wave=0,
                task_status=spec.status,
                all_waves_complete=False,
                hub_synced=False,
                feedback=msg,
                tunnel_status=tunnel_status,
                gate_waiting="Gate 5: Confirmação de Fechamento Transacional",
                is_awaiting_closure=True,
                judge_score=judge_score,
            )

        console.print(
            "\n[bold blue]🚀 Executando Fechamento Transacional "
            "(Merge de PRs, Promoção de Prompts e Sync-Hub)...[/bold blue]"
        )
        gh_client = self.github_client or GateGitHubCLIClient()
        closure = TransactionalGateClosure(
            github_client=gh_client,
            hub_pr_number=spec.hub_pr_number,
            spec_hub_dir=self.spec_hub_dir,
        )
        closure_res = closure.execute(
            spec_id=spec.spec_id,
            judge_status=judge_status,
            judge_score=judge_score,
            judge_reason=judge_reason,
            contract_result=ContractValidationResult(valid=True),
            tasks_info=tasks_info,
            prompts=spec.prompts,
        )

        spec.status = TaskState.APPROVED
        for task in spec.tasks.values():
            task.status = TaskState.APPROVED

        async with self.store:
            if not ci_mode:
                self.tunnel_manager.ensure_tunnel(config=self.config, ci_mode=ci_mode)
            await self.store.save_spec(spec)

        hub_synced = self._sync_spec_hub_if_complete(spec)
        self._auto_merge_hub_slice_branches(spec)

        for pr_repo, pr_num in closure_res.merged_prs:
            console.print(
                f"  • [bold green]✓ PR #{pr_num} mergeado com sucesso "
                f"em {pr_repo}[/bold green]"
            )
        for promoted_p in closure_res.prompts_promoted:
            console.print(
                "  • [bold green]✓ Prompt promovido para 'production' "
                f"no Langfuse: {promoted_p}[/bold green]"
            )

        feedback_msg = (
            f"Especificação {spec.spec_id} encerrada com 100% de conformidade. "
            f"{len(closure_res.merged_prs)} PRs mergeados, "
            f"{len(closure_res.prompts_promoted)} prompts promovidos para "
            "produção e spec-hub sincronizado."
        )

        return PipelineStepOutcome(
            spec_id=spec.spec_id,
            active_task_id=None,
            active_repo=None,
            wave=0,
            task_status=TaskState.APPROVED,
            all_waves_complete=True,
            hub_synced=hub_synced,
            feedback=feedback_msg,
            tunnel_status=tunnel_status,
            judge_score=judge_score,
            prompts_promoted=closure_res.prompts_promoted,
        )

    def _auto_merge_hub_slice_branches(self, spec: SpecRun) -> None:
        """Auto-merge seguro das branches de fatias no fechamento (SPEC-004 B2).

        Invocado no fechamento transacional (Gate 5), fecha branches de
        fatias pendentes do hub com validação de diff; aborto é reportado,
        nunca fatal.

        Args:
            spec: Especificação encerrada (status APPROVED).
        """
        if self.spec_hub_dir is None or not self.spec_hub_dir.is_dir():
            return
        outcome: MergeOutcome = merge_completed_hub_branches(
            spec.spec_id, self.spec_hub_dir
        )
        for branch in outcome.merged:
            console.print(
                f"  • [bold green]✓ Auto-merge da branch de fatias "
                f"{branch} em main (hub)[/bold green]"
            )
        for warning in outcome.warnings:
            console.print(f"[bold yellow]⚠️ Auto-merge do hub: {warning}[/bold yellow]")
        if outcome.aborted_reason:
            console.print(
                f"[bold yellow]⚠️ Auto-merge do hub abortado: "
                f"{outcome.aborted_reason}[/bold yellow]"
            )

    def _invoke_refine_prompt_runner(
        self,
        runner_fn: Callable[..., tuple[int, str]],
        selected_agent: DetectedAgent,
        spec_path: Path,
        spec_id: str,
        refine_prompt_text: str,
        continue_session: bool,
    ) -> tuple[int, str]:
        """Invoca o callback de execução do prompt de refinamento da spec.

        Args:
            runner_fn: Função executora do prompt.
            selected_agent: Agente selecionado.
            spec_path: Caminho do arquivo da spec.
            spec_id: Identificador da spec.
            refine_prompt_text: Texto do prompt de refinamento.
            continue_session: Indica se deve retomar sessão anterior.

        Returns:
            Tupla `(exit_code, agent_output)`.
        """
        runner_kwargs: dict[str, Any] = {
            "agent": selected_agent,
            "working_dir": spec_path.parent,
            "prompt_text": refine_prompt_text,
            "task_label": f"refinamento da spec {spec_id}",
        }
        try:
            sig = inspect.signature(runner_fn)
            if "continue_session" in sig.parameters:
                runner_kwargs["continue_session"] = continue_session
        except (ValueError, TypeError):
            pass
        return runner_fn(**runner_kwargs)

    async def refine_spec(
        self,
        spec_path: Path,
        user_prompt: str,
        manifest_path: Path | None = None,
        selected_agent: DetectedAgent | None = None,
        ci_mode: bool = False,
        prompt_runner: Callable[..., tuple[int, str]] | None = None,
        continue_session: bool = True,
    ) -> SpecRefineOutcome:
        """Refina uma especificação técnica in-flight preservando tarefas concluídas.

        Args:
            spec_path: Caminho do arquivo da especificação Markdown.
            user_prompt: Instrução do que deve ser alterado ou refinado.
            manifest_path: Caminho opcional do `manifest.yaml`.
            selected_agent: Agente de IA a ser utilizado para reescrever a spec.
            ci_mode: Se True, opera em modo headless sem túnel SSH.
            prompt_runner: Callback opcional para execução do agente (mock em testes).
            continue_session: Retoma a sessão anterior se suportado pelo agente.

        Returns:
            Instância de `SpecRefineOutcome` com status e resumo da operação.
        """
        if not spec_path.is_file():
            return SpecRefineOutcome(
                spec_id="",
                spec_path=spec_path,
                success=False,
                feedback=f"Arquivo de especificação {spec_path} não encontrado.",
            )

        resolved_manifest = self.resolve_manifest_path(manifest_path)
        if self.spec_hub_dir is None and resolved_manifest is not None:
            self.spec_hub_dir = resolved_manifest.parent
        if not ci_mode:
            self.tunnel_manager.ensure_tunnel(config=self.config, ci_mode=ci_mode)

        parsed_spec = parse_spec_with_waves(
            file_path=spec_path,
            manifest_path=resolved_manifest,
        )

        async with self.store:
            existing_spec = await self.store.get_spec(parsed_spec.spec_id)
            active_spec = existing_spec or parsed_spec
            frozen_tasks, pending_tasks = get_frozen_and_pending_tasks(
                active_spec.tasks
            )

        spec_content = spec_path.read_text(encoding="utf-8")
        refine_prompt_text = build_spec_refine_prompt(
            spec_path=spec_path,
            spec_content=spec_content,
            frozen_tasks=frozen_tasks,
            pending_tasks=pending_tasks,
            user_instruction=user_prompt,
        )

        runner_fn = prompt_runner or (
            AgentRunner().run_prompt if selected_agent is not None else None
        )
        if runner_fn is not None and selected_agent is not None:
            agent_code, agent_output = self._invoke_refine_prompt_runner(
                runner_fn=runner_fn,
                selected_agent=selected_agent,
                spec_path=spec_path,
                spec_id=parsed_spec.spec_id,
                refine_prompt_text=refine_prompt_text,
                continue_session=continue_session,
            )
            if agent_code != 0:
                return SpecRefineOutcome(
                    spec_id=parsed_spec.spec_id,
                    spec_path=spec_path,
                    frozen_tasks=[t.id for t in frozen_tasks],
                    pending_tasks=[t.id for t in pending_tasks],
                    success=False,
                    feedback=(
                        f"Falha ao executar agente para refinar spec: {agent_output}"
                    ),
                )

        updated_parsed = parse_spec_with_waves(
            file_path=spec_path,
            manifest_path=resolved_manifest,
        )
        merged_spec = merge_refined_spec(
            existing_spec=active_spec,
            new_parsed=updated_parsed,
        )

        async with self.store:
            if not ci_mode:
                self.tunnel_manager.ensure_tunnel(config=self.config, ci_mode=ci_mode)
            await self.store.save_spec(merged_spec)

        updated_frozen, updated_pending = get_frozen_and_pending_tasks(
            merged_spec.tasks
        )
        return SpecRefineOutcome(
            spec_id=merged_spec.spec_id,
            spec_path=spec_path,
            frozen_tasks=[t.id for t in updated_frozen],
            pending_tasks=[t.id for t in updated_pending],
            success=True,
            feedback="Especificação refinada e sincronizada no State Tracker.",
        )
