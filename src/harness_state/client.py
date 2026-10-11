"""Cliente de comunicação assíncrona com o Redis central."""

import json
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
import redis.asyncio as aioredis
from harness_state.models import SpecRun, SubTask, TaskState


class Settings(BaseSettings):
    """Configurações de conexão do Redis."""
    model_config = SettingsConfigDict(env_prefix="HARNESS_")

    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None


class StateStore:
    """Repositório de estado persistido no Redis central do Proxmox."""

    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or Settings()
        self._client: Optional[aioredis.Redis] = None

    def get_client(self) -> aioredis.Redis:
        """Retorna uma conexão ativa com o Redis."""
        if self._client is None:
            self._client = aioredis.Redis(
                host=self.settings.redis_host,
                port=self.settings.redis_port,
                db=self.settings.redis_db,
                password=self.settings.redis_password,
                decode_responses=True,
            )
        return self._client

    async def save_spec(self, spec: SpecRun) -> None:
        """Salva ou atualiza uma especificação no Redis."""
        client = self.get_client()
        key = f"spec:{spec.spec_id}"
        await client.set(key, spec.model_dump_json())

    async def get_spec(self, spec_id: str) -> Optional[SpecRun]:
        """Obtém uma especificação pelo ID."""
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
        worker_id: Optional[str] = None,
        pr_number: Optional[int] = None,
    ) -> Optional[SpecRun]:
        """Atualiza atômica o estado de uma sub-tarefa."""
        spec = await self.get_spec(spec_id)
        if not spec or task_id not in spec.tasks:
            return None

        task = spec.tasks[task_id]
        task.status = status
        if worker_id:
            task.last_worker = worker_id
        if pr_number:
            task.pr_number = pr_number

        all_ready = all(t.status in (TaskState.READY, TaskState.APPROVED) for t in spec.tasks.values())
        if all_ready and len(spec.tasks) > 0:
            spec.status = TaskState.READY

        await self.save_spec(spec)
        return spec
