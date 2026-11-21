"""Cliente de comunicação assíncrona com o Redis central e protocolos de persistência."""

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self, runtime_checkable

import redis.asyncio as aioredis
from pydantic_settings import BaseSettings, SettingsConfigDict

from harness_state.models import SpecRun, TaskState


def parse_spec_reference(raw_spec_id: str) -> tuple[str, str]:
    """Divide uma referência de spec em `(ecosistema, spec_id)` (SPEC-005 C1).

    Referências namespaced usam o formato `{ecosistema}/{SPEC-XXX}` (ex:
    `harness/SPEC-005`); sem prefixo, o comportamento é o legado
    (ecosistema vazio, chave Redis não namespaced).

    Args:
        raw_spec_id: Referência de spec como recebida nas CLIs.

    Returns:
        Tupla `(ecosistema, spec_id)` — ecosistema vazio quando legado.
    """
    if "/" in raw_spec_id:
        ecosystem, _, spec_id = raw_spec_id.partition("/")
        return ecosystem, spec_id
    return "", raw_spec_id


def redis_spec_key(ecosystem: str, spec_id: str) -> str:
    """Constrói a chave Redis da spec conforme o namespace (SPEC-005 C1).

    Args:
        ecosystem: Namespace do ecossistema (vazio = legado).
        spec_id: Identificador da especificação.

    Returns:
        `spec:{ecosistema}:{spec_id}` quando namespaced; `spec:{spec_id}`
        quando legado.
    """
    if ecosystem:
        return f"spec:{ecosystem}:{spec_id}"
    return f"spec:{spec_id}"


def derive_hub_ecosystem(hub_dir: Path) -> str:
    """Deriva o namespace do ecossistema a partir do nome do hub (SPEC-005 C1).

    Remove o sufixo `-spec-hub` do nome do diretório do hub:
    `harness-spec-hub` → `harness`; `paralax-spec-hub` → `paralax`.

    Args:
        hub_dir: Diretório raiz do spec-hub local.

    Returns:
        Identificador do ecossistema para namespace no Redis.
    """
    name = hub_dir.name
    if name.endswith("-spec-hub"):
        return name[: -len("-spec-hub")]
    return name


class Settings(BaseSettings):
    """Configurações de conexão do Redis para o barramento central."""

    model_config = SettingsConfigDict(env_prefix="HARNESS_", extra="ignore")

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
        pr_url: str | None = None,
        expected_version: str | None = None,
        issue_number: int | None = None,
        issue_url: str | None = None,
    ) -> SpecRun | None:
        """Atualiza o estado de uma subtarefa pertencente a uma especificação.

        Args:
            spec_id: Identificador da especificação.
            task_id: Identificador da subtarefa.
            status: Novo estado atribuído.
            worker_id: Identificador opcional do worker.
            pr_number: Número opcional do Pull Request.
            expected_version: Versão esperada para release da subtarefa.
            issue_number: Número opcional da issue de rastreamento no GitHub.
            issue_url: URL opcional da issue de rastreamento no GitHub.

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
        ecosystem, spec_id = parse_spec_reference(spec.spec_id)
        self._specs[redis_spec_key(ecosystem, spec_id)] = spec.model_copy(deep=True)

    async def get_spec(self, spec_id: str) -> SpecRun | None:
        """Recupera a especificação em memória.

        Args:
            spec_id: Identificador da especificação.

        Returns:
            Cópia da especificação ou None se inexistente.
        """
        ecosystem, parsed_id = parse_spec_reference(spec_id)
        spec = self._specs.get(redis_spec_key(ecosystem, parsed_id))
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
        pr_url: str | None = None,
        expected_version: str | None = None,
        issue_number: int | None = None,
        issue_url: str | None = None,
    ) -> SpecRun | None:
        """Atualiza a subtarefa no modelo em memória e persiste a alteração.

        Args:
            spec_id: Identificador da especificação.
            task_id: Identificador da subtarefa.
            status: Novo estado da subtarefa.
            worker_id: Identificador opcional do worker.
            pr_number: Número opcional do Pull Request.
            expected_version: Versão esperada para release da subtarefa.
            issue_number: Número opcional da issue de rastreamento no GitHub.
            issue_url: URL opcional da issue de rastreamento no GitHub.

        Returns:
            SpecRun atualizada ou None caso não exista.
        """
        ecosystem, parsed_id = parse_spec_reference(spec_id)
        spec = self._specs.get(redis_spec_key(ecosystem, parsed_id))
        if spec is None or task_id not in spec:
            return None

        spec.update_task_status(
            task_id,
            status,
            worker_id=worker_id,
            pr_number=pr_number,
            pr_url=pr_url,
            expected_version=expected_version,
            issue_number=issue_number,
            issue_url=issue_url,
        )
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

    def __init__(
        self,
        settings: Settings | None = None,
        redis_url: str | None = None,
        reconnect_hook: Callable[[], bool | Awaitable[bool]] | None = None,
        client_factory: Callable[[], aioredis.Redis] | None = None,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> None:
        """Inicializa o repositório de estado com as configurações fornecidas.

        Args:
            settings: Instância de Settings opcional com parâmetros de rede do Redis.
            redis_url: URL opcional direta de conexão com o Redis.
            reconnect_hook: Callback para restabelecer túnel SSH caso a conexão caia.
            client_factory: Fábrica opcional de cliente Redis para testes.
            max_retries: Número máximo de tentativas sob falha de conexão.
            retry_delay: Intervalo base em segundos entre retentativas.
        """
        self.settings: Settings = settings or Settings()
        self.redis_url = redis_url
        self.reconnect_hook = reconnect_hook
        self.client_factory = client_factory
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self._client: aioredis.Redis | None = None

    def get_client(self) -> aioredis.Redis:
        """Retorna uma conexão ativa com o Redis, inicializando-a se necessário.

        Returns:
            Instância de conexão ativa com o Redis.
        """
        if self._client is None:
            if self.client_factory is not None:
                self._client = self.client_factory()
            elif self.redis_url:
                self._client = aioredis.from_url(
                    self.redis_url,
                    decode_responses=True,
                )
            else:
                self._client = aioredis.Redis(
                    host=self.settings.redis_host,
                    port=self.settings.redis_port,
                    db=self.settings.redis_db,
                    password=self.settings.redis_password,
                    decode_responses=True,
                )
        return self._client

    async def _handle_connection_failure(self) -> None:
        """Encerra client corrompido e aciona o hook de reconexão do túnel."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

        if self.reconnect_hook is not None:
            hook_res = self.reconnect_hook()
            if inspect.isawaitable(hook_res):
                await hook_res

    async def _run_command(self, cmd_name: str, *args: Any, **kwargs: Any) -> Any:
        """Executa um comando no Redis com reconexão de túnel e retry.

        Args:
            cmd_name: Nome do método a invocar no client Redis (ex: get, set).
            *args: Argumentos posicionais do comando.
            **kwargs: Argumentos nomeados do comando.

        Returns:
            Resposta retornada pelo Redis.

        Raises:
            Exception: Se todas as tentativas falharem.
        """
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            client = self.get_client()
            try:
                cmd_fn = getattr(client, cmd_name)
                return await cmd_fn(*args, **kwargs)
            except (
                aioredis.ConnectionError,
                aioredis.TimeoutError,
                ConnectionError,
                OSError,
            ) as exc:
                last_exc = exc
                await self._handle_connection_failure()
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay * (attempt + 1))

        if last_exc is not None:
            raise last_exc

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
        ecosystem, spec_id = parse_spec_reference(spec.spec_id)
        key = redis_spec_key(ecosystem, spec_id)
        await self._run_command("set", key, spec.model_dump_json())

    async def get_spec(self, spec_id: str) -> SpecRun | None:
        """Obtém uma especificação pelo seu identificador único.

        Args:
            spec_id: Identificador da especificação (ex: SPEC-042).

        Returns:
            SpecRun correspondente ou None se não encontrada.
        """
        ecosystem, parsed_id = parse_spec_reference(spec_id)
        key = redis_spec_key(ecosystem, parsed_id)
        data = await self._run_command("get", key)
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
        pr_url: str | None = None,
        expected_version: str | None = None,
        issue_number: int | None = None,
        issue_url: str | None = None,
    ) -> SpecRun | None:
        """Atualiza atomicamente o estado de uma subtarefa e recalcula o status global da spec.

        Args:
            spec_id: Identificador da especificação.
            task_id: Identificador da subtarefa.
            status: Novo estado atribuído.
            worker_id: Identificador opcional do worker responsável.
            pr_number: Número opcional do Pull Request.
            expected_version: Versão esperada para release da subtarefa.
            issue_number: Número opcional da issue de rastreamento no GitHub.
            issue_url: URL opcional da issue de rastreamento no GitHub.

        Returns:
            SpecRun atualizada ou None se não encontrada.
        """
        spec = await self.get_spec(spec_id)
        if spec is None or task_id not in spec:
            return None

        spec.update_task_status(
            task_id,
            status,
            worker_id=worker_id,
            pr_number=pr_number,
            pr_url=pr_url,
            expected_version=expected_version,
            issue_number=issue_number,
            issue_url=issue_url,
        )
        await self.save_spec(spec)
        return spec
