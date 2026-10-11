"""Cliente de comunicação assíncrona com o Redis central e protocolos de persistência."""

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

import redis.asyncio as aioredis
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness_state.models import SpecRun, TaskState


class Settings(BaseSettings):
    """Configurações de conexão do Redis para o barramento central."""

    model_config = SettingsConfigDict(env_prefix="HARNESS_")

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None


@runtime_checkable
class StateStoreProtocol(Protocol):
    """Protocolo formal para clientes de persistência do ciclo de vida das especificações."""

    async def save_spec(self, spec: SpecRun) -> None:
        """Salva ou atualiza uma especificação no repositório.

        Args:
            spec: Instância da especificação a ser persistida.
        """
        ...

    async def get_spec(self, spec_id: str) -> SpecRun | None:
        """Recupera uma especificação a partir do seu identificador.

        Args:
            spec_id: Identificador da especificação.

        Returns:
            Instância de SpecRun encontrada ou None se inexistente.
        """
        ...

    async def update_task_status(
        self,
        spec_id: str,
        task_id: str,
        status: TaskState,
        worker_id: str | None = None,
        pr_number: int | None = None,
    ) -> SpecRun | None:
        """Atualiza o estado de uma subtarefa pertencente a uma especificação.

        Args:
            spec_id: Identificador da especificação.
            task_id: Identificador da subtarefa.
            status: Novo estado atribuído.
            worker_id: Identificador opcional do worker.
            pr_number: Número opcional do Pull Request.

        Returns:
            SpecRun atualizada ou None se a especificação ou subtarefa não for encontrada.
        """
        ...

    async def aclose(self) -> None:
        """Encerra com segurança as conexões ativas com o repositório de persistência."""
        ...

    async def __aenter__(self) -> Self:
        """Entrada do gerenciador de contexto assíncrono."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Saída do gerenciador de contexto assíncrono."""
        ...


class InMemoryStateStore:
    """Implementação em memória de StateStore para testes unitários isolados e desenvolvimento local."""

    def __init__(self) -> None:
        """Inicializa o repositório em memória vazio."""
        self._specs: dict[str, SpecRun] = {}

    async def save_spec(self, spec: SpecRun) -> None:
        """Salva a especificação no dicionário em memória.

        Args:
            spec: Instância da especificação a ser armazenada.
        """
        self._specs[spec.spec_id] = spec.model_copy(deep=True)

    async def get_spec(self, spec_id: str) -> SpecRun | None:
        """Recupera a especificação em memória.

        Args:
            spec_id: Identificador da especificação.

        Returns:
            Cópia da especificação ou None se inexistente.
        """
        spec = self._specs.get(spec_id)
        if spec is None:
            return None
        return spec.model_copy(deep=True)

    async def update_task_status(
        self,
        spec_id: str,
        task_id: str,
        status: TaskState,
        worker_id: str | None = None,
        pr_number: int | None = None,
    ) -> SpecRun | None:
        """Atualiza a subtarefa no modelo em memória e persiste a alteração.

        Args:
            spec_id: Identificador da especificação.
            task_id: Identificador da subtarefa.
            status: Novo estado da subtarefa.
            worker_id: Identificador opcional do worker.
            pr_number: Número opcional do Pull Request.

        Returns:
            SpecRun atualizada ou None caso não exista.
        """
        spec = self._specs.get(spec_id)
        if spec is None or task_id not in spec:
            return None

        spec.update_task_status(task_id, status, worker_id=worker_id, pr_number=pr_number)
        return spec.model_copy(deep=True)

    async def aclose(self) -> None:
        """Operação no-op para descarte do armazenamento em memória."""

    async def __aenter__(self) -> Self:
        """Entrada no contexto assíncrono.

        Returns:
            A própria instância do InMemoryStateStore.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Encerra o contexto chamando aclose().

        Args:
            exc_type: Tipo da exceção levantada, se houver.
            exc_val: Valor da exceção levantada.
            exc_tb: Traceback da exceção levantada.
        """
        await self.aclose()


class StateStore:
    """Repositório de estado persistido no Redis central do Proxmox."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Inicializa o repositório de estado com as configurações fornecidas.

        Args:
            settings: Instância de Settings opcional com parâmetros de rede do Redis.
        """
        self.settings: Settings = settings or Settings()
        self._client: aioredis.Redis | None = None

    def get_client(self) -> aioredis.Redis:
        """Retorna uma conexão ativa com o Redis, inicializando-a se necessário.

        Returns:
            Instância de conexão ativa com o Redis.
        """
        if self._client is None:
            self._client = aioredis.Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                db=self.settings.redis_db,
                password=self.settings.redis_password,
                decode_responses=True,
            )
        return self._client

    async def aclose(self) -> None:
        """Encerra a conexão ativa com o Redis com segurança."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Self:
        """Entrada no contexto assíncrono.

        Returns:
            A própria instância do StateStore.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Saída do contexto assíncrono, garantindo o fechamento das conexões.

        Args:
            exc_type: Tipo da exceção levantada, se houver.
            exc_val: Instância da exceção levantada.
            exc_tb: Traceback da exceção.
        """
        await self.aclose()

    async def save_spec(self, spec: SpecRun) -> None:
        """Salva ou atualiza uma especificação no Redis central.

        Args:
            spec: Instância da especificação a ser persistida.
        """
        client = self.get_client()
        key = f"spec:{spec.spec_id}"
        await client.set(key, spec.model_dump_json())

    async def get_spec(self, spec_id: str) -> SpecRun | None:
        """Obtém uma especificação pelo seu identificador único.

        Args:
            spec_id: Identificador da especificação (ex: SPEC-042).

        Returns:
            SpecRun correspondente ou None se não encontrada.
        """
        client = self.get_client()
        key = f"spec:{spec_id}"
        data = await client.get(key)
        if not data:
            return None
        return SpecRun.model_validate_json(data)

    async def update_task_status(
        self,
        spec_id: str,
        task_id: str,
        status: TaskState,
        worker_id: str | None = None,
        pr_number: int | None = None,
    ) -> SpecRun | None:
        """Atualiza atomicamente o estado de uma subtarefa e recalcula o status global da spec.

        Args:
            spec_id: Identificador da especificação.
            task_id: Identificador da subtarefa.
            status: Novo estado atribuído.
            worker_id: Identificador opcional do worker responsável.
            pr_number: Número opcional do Pull Request.

        Returns:
            SpecRun atualizada ou None se não encontrada.
        """
        spec = await self.get_spec(spec_id)
        if spec is None or task_id not in spec:
            return None

        spec.update_task_status(task_id, status, worker_id=worker_id, pr_number=pr_number)
        await self.save_spec(spec)
        return spec
