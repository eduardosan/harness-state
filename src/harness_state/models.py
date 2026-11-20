"""Módulos de dados e esquemas para State Tracking na plataforma SDD."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


@dataclass(slots=True)
class CICDViolation:
    """Representa uma violação de integridade em arquivo de CI/CD."""

    file_path: Path
    line_number: int
    col_number: int
    code: str
    message: str

    def format_output(self) -> str:
        """Formata a violação no padrão consumível por format_feedback.sh.

        Returns:
            String no formato 'arquivo:linha:coluna: CODIGO mensagem'.
        """
        return (
            f"{self.file_path}:{self.line_number}:{self.col_number}: "
            f"{self.code} {self.message}"
        )


class TaskState(StrEnum):
    """Estado do ciclo de vida de uma sub-tarefa em um repositório alvo."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    APPROVED = "APPROVED"
    FAILED = "FAILED"

    @property
    def is_terminal(self) -> bool:
        """Indica se o estado representa conclusão ou término definitivo."""
        return self in (TaskState.APPROVED, TaskState.FAILED)

    @property
    def is_active(self) -> bool:
        """Indica se o estado ainda está ativo em processamento."""
        return self in (TaskState.PENDING, TaskState.IN_PROGRESS)


class SubTask(BaseModel):
    """Sub-tarefa decomposta para um repositório específico.

    Attributes:
        id: Identificador da subtarefa (ex: 'task-1').
        repo: Repositório alvo (slug completo).
        branch: Branch de trabalho da subtarefa.
        status: Estado corrente no barramento.
        pr_number: PR aberto para a subtarefa, quando existe.
        issue_number: Issue de tracking da subtarefa no hub, quando existe.
        issue_url: URL da issue de tracking.
        expected_version: Versão esperada do núcleo após o release.
        sub_spec_path: Caminho da sub-spec gerada no spoke.
        last_worker: Identificador do último executor.
        wave: Onda topológica (1 = raiz).
        depends_on: IDs de subtarefas que precisam concluir antes.
        updated_at: Timestamp UTC da última transição.
    """

    id: str
    repo: str
    branch: str
    status: TaskState = TaskState.PENDING
    pr_number: int | None = None
    issue_number: int | None = None
    issue_url: str | None = None
    expected_version: str | None = None
    sub_spec_path: str | None = None
    last_worker: str | None = None
    wave: int = 1
    depends_on: list[str] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RevisionType(StrEnum):
    """Tipo de revisão aplicada à especificação técnica."""

    MINOR_EVOLUTION = "MINOR_EVOLUTION"
    MAJOR_BREAKING = "MAJOR_BREAKING"
    PATCH_CORRECTION = "PATCH_CORRECTION"


class SpecRevision(BaseModel):
    """Registro imutável de uma revisão aplicada a uma spec existente."""

    revision_id: str
    spec_id: str
    version: str
    revision_type: RevisionType
    author: str
    instruction: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    frozen_task_ids: list[str] = Field(default_factory=list)
    new_task_ids: list[str] = Field(default_factory=list)
    modified_contracts: list[str] = Field(default_factory=list)


class SpecMatch(BaseModel):
    """Resultado da correspondência de uma spec existente durante o comando plan."""

    spec_id: str
    title: str
    file_path: str
    similarity_score: float
    matched_capability: str = ""
    relevance_summary: str = ""
    recommended_action: str = "evolve"


class CapabilitySyncResult(BaseModel):
    """Resultado da sincronização do mapa de capacidades pós-aprovação."""

    capability_id: str
    updated: bool
    added_terms: list[str] = Field(default_factory=list)
    added_contracts: list[str] = Field(default_factory=list)
    added_specs: list[str] = Field(default_factory=list)
    sync_agent: str = ""
    diff_summary: str = ""


class SpecEvolutionPlan(BaseModel):
    """Plano de evolução gerado a partir do diff semântico de uma spec."""

    spec_id: str
    current_version: str
    target_version: str
    frozen_tasks: list[SubTask]
    tasks_to_execute: list[SubTask]
    affected_repositories: list[str]
    has_breaking_changes: bool = False


class SpecRun(BaseModel):
    """Estado global de uma especificação no barramento central."""

    spec_id: str
    title: str
    author: str
    status: TaskState = TaskState.IN_PROGRESS
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tasks: dict[str, SubTask] = Field(default_factory=dict)
    correlation_uuid: str | None = None
    product: list[str] = Field(default_factory=list)
    capability: str = ""
    scope: str = "platform"
    origin_module: str = ""
    declared_status: str = "APPROVED"
    prompts: list[str] = Field(default_factory=list)
    hub_pr_number: int | None = None
    hub_pr_url: str | None = None
    spec_version: str = "1.0.0"
    author_agent: str = "antigravity"
    author_model: str = ""
    revisions: list[SpecRevision] = Field(default_factory=list)
    capability_synced: bool = False

    def __len__(self) -> int:
        """Retorna o número total de subtarefas na especificação."""
        return len(self.tasks)

    def __getitem__(self, task_id: str) -> SubTask:
        """Permite acesso direto à subtarefa via colchetes pelo seu identificador.

        Args:
            task_id: Identificador único da subtarefa.

        Returns:
            SubTask correspondente.

        Raises:
            KeyError: Se a tarefa não existir na especificação.
        """
        return self.tasks[task_id]

    def __contains__(self, task_id: str) -> bool:
        """Verifica se uma subtarefa está registrada na especificação.

        Args:
            task_id: Identificador da subtarefa.

        Returns:
            True se a subtarefa estiver presente, False caso contrário.
        """
        return task_id in self.tasks

    def __iter__(self) -> Iterator[SubTask]:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Permite iterar diretamente sobre as subtarefas da especificação.

        Returns:
            Iterador de instâncias de SubTask.
        """
        return iter(self.tasks.values())

    def __repr__(self) -> str:
        """Retorna uma representação descritiva da especificação para depuração."""
        return (
            f"SpecRun(spec_id={self.spec_id!r}, "
            f"status={self.status.value!r}, "
            f"tasks_count={len(self.tasks)})"
        )

    @property
    def is_complete(self) -> bool:
        """Indica se todas as tarefas foram finalizadas com sucesso (READY ou APPROVED)."""
        if not self.tasks:
            return False
        return all(
            task.status in (TaskState.READY, TaskState.APPROVED)
            for task in self.tasks.values()
        )

    @property
    def pending_tasks(self) -> list[SubTask]:
        """Retorna a lista de subtarefas ainda pendentes de execução."""
        return [
            task for task in self.tasks.values() if task.status == TaskState.PENDING
        ]

    def get_next_unblocked_task(self) -> SubTask | None:
        """Retorna a próxima subtarefa cujas dependências de ondas já concluíram.

        Returns:
            SubTask desbloqueada pronta para execução ou None se não houver.
        """
        ordered = sorted(self.tasks.values(), key=lambda t: (t.wave, t.id))
        for task in ordered:
            if task.status not in (TaskState.PENDING, TaskState.IN_PROGRESS):
                continue
            deps_satisfied = all(
                self.tasks[dep_id].status in (TaskState.READY, TaskState.APPROVED)
                for dep_id in task.depends_on
                if dep_id in self.tasks
            )
            if deps_satisfied:
                return task
        return None

    def add_task(self, task: SubTask) -> None:
        """Adiciona ou substitui uma subtarefa na especificação.

        Args:
            task: Instância da subtarefa a ser registrada.
        """
        self.tasks[task.id] = task

    def update_task_status(
        self,
        task_id: str,
        status: TaskState,
        worker_id: str | None = None,
        pr_number: int | None = None,
        expected_version: str | None = None,
        issue_number: int | None = None,
        issue_url: str | None = None,
    ) -> SubTask | None:
        """Atualiza os dados de uma subtarefa e recalcula o status global da spec.

        Args:
            task_id: Identificador único da subtarefa.
            status: Novo estado atribuído à subtarefa.
            worker_id: Identificador opcional do worker responsável.
            pr_number: Número opcional do Pull Request associado.
            expected_version: Versão esperada para release da subtarefa.
            issue_number: Número opcional da issue de rastreamento no GitHub.
            issue_url: URL opcional da issue de rastreamento no GitHub.

        Returns:
            SubTask atualizada ou None se a subtarefa não existir.
        """
        if task_id not in self.tasks:
            return None

        task = self.tasks[task_id]
        task.status = status
        task.updated_at = datetime.now(UTC)
        if worker_id is not None:
            task.last_worker = worker_id
        if pr_number is not None:
            task.pr_number = pr_number
        if expected_version is not None:
            task.expected_version = expected_version
        if issue_number is not None:
            task.issue_number = issue_number
        if issue_url is not None:
            task.issue_url = issue_url

        if self.is_complete:
            self.status = TaskState.READY

        return task

    def apply_evolution(
        self,
        new_version: str,
        revision: SpecRevision,
        new_subtasks: list[SubTask],
    ) -> None:
        """Aplica uma evolução à spec, preservando tarefas concluídas como congeladas.

        Args:
            new_version: Nova versão SemVer da especificação.
            revision: Instância imutável de SpecRevision.
            new_subtasks: Lista de novas subtarefas a serem adicionadas ou atualizadas.
        """
        self.spec_version = new_version
        self.revisions.append(revision)
        for task in new_subtasks:
            self.tasks[task.id] = task
        if self.status in (TaskState.READY, TaskState.APPROVED):
            self.status = TaskState.IN_PROGRESS
