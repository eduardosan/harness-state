"""Módulos de dados e esquemas para State Tracking na plataforma SDD."""

from collections.abc import Iterator
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


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
    """Sub-tarefa decomposta para um repositório específico."""

    id: str
    repo: str
    branch: str
    status: TaskState = TaskState.PENDING
    pr_number: int | None = None
    sub_spec_path: str | None = None
    last_worker: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SpecRun(BaseModel):
    """Estado global de uma especificação no barramento central."""

    spec_id: str
    title: str
    author: str
    status: TaskState = TaskState.IN_PROGRESS
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tasks: dict[str, SubTask] = Field(default_factory=dict)
    correlation_uuid: str | None = None

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
        return all(task.status in (TaskState.READY, TaskState.APPROVED) for task in self.tasks.values())

    @property
    def pending_tasks(self) -> list[SubTask]:
        """Retorna a lista de subtarefas ainda pendentes de execução."""
        return [task for task in self.tasks.values() if task.status == TaskState.PENDING]

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
    ) -> SubTask | None:
        """Atualiza os dados de uma subtarefa e recalcula o status global da spec.

        Args:
            task_id: Identificador único da subtarefa.
            status: Novo estado atribuído à subtarefa.
            worker_id: Identificador opcional do worker responsável.
            pr_number: Número opcional do Pull Request associado.

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

        if self.is_complete:
            self.status = TaskState.READY

        return task
