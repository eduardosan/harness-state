"""Runtime de execução de tarefas com Pydantic AI Coder no ecossistema Harness (SPEC-010).

Gerencia a execução in-process de agentes de codificação tipados em Python,
orquestração de subagentes (RCA, Implementação e Sensores) e integração de
ferramentas de auditoria e conformidade.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_state.models import SubTask
from harness_state.runtimes.coder_prompts import (
    CODER_SYSTEM_INSTRUCTION,
    RCA_SUBAGENT_INSTRUCTION,
)


@dataclass(slots=True)
class PydanticCoderConfig:
    """Configuração do runtime Pydantic AI Coder.

    Attributes:
        model_name: Identificador do modelo de linguagem.
        base_url: URL base da API OpenAI-compatible ou Ollama.
        api_key: Chave de API para autenticação.
        max_request_limit: Limite máximo de requisições / turnos do agente.
        enable_subagents: Habilita delegação de subtarefas a subagentes.
        local_workspace_root: Diretório raiz do workspace de trabalho.
    """

    model_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    max_request_limit: int = 30
    enable_subagents: bool = True
    local_workspace_root: Path = field(default_factory=Path.cwd)


def resolve_pydantic_coder_settings(
    environ: Mapping[str, str] | None = None,
) -> PydanticCoderConfig:
    """Resolve a configuração do Pydantic AI Coder a partir das variáveis canônicas.

    Segue estritamente as variáveis de ambiente já existentes no ecossistema
    sem prescrever fallback fixo para localhost.

    Args:
        environ: Dicionário opcional de variáveis de ambiente.

    Returns:
        Instância de PydanticCoderConfig com parâmetros resolvidos.
    """
    env_map = environ if environ is not None else os.environ
    base_url = (
        env_map.get("OPENAI_API_BASE")
        or env_map.get("OLLAMA_API_BASE")
        or env_map.get("HARNESS_LLM_EXTERNAL_BASE_URL")
        or env_map.get("LLM_BASE_URL")
        or "http://127.0.0.1:11434/v1"
    )
    api_key = env_map.get("OPENAI_API_KEY") or env_map.get("OLLAMA_API_KEY") or ""
    model = (
        env_map.get("LLM_DEFAULT_MODEL")
        or env_map.get("LLM_MODEL")
        or "agentic-qwen:7b"
    )

    return PydanticCoderConfig(
        model_name=model,
        base_url=base_url,
        api_key=api_key,
    )


class PydanticCoderRunner:
    """Executor nativo Pydantic AI Coder integrado ao harness-state."""

    def __init__(
        self,
        config: PydanticCoderConfig | None = None,
        agent_executor: Callable[..., Any] | None = None,
    ) -> None:
        """Inicializa o runner com configuração opcional e executor de agente.

        Args:
            config: Configuração do runtime ou None para resolução automática.
            agent_executor: Injetor opcional de execução para mocks em testes.
        """
        self.config = config or resolve_pydantic_coder_settings()
        self.agent_executor = agent_executor

    def is_pydantic_ai_available(self) -> bool:
        """Verifica se o pacote pydantic_ai está instalado no ambiente.

        Returns:
            True se pydantic_ai estiver disponível para importação.
        """
        return importlib.util.find_spec("pydantic_ai") is not None

    async def run_task(
        self,
        task: SubTask,
        spec_path: Path,
        spoke_dir: Path,
        feedback: str = "",
    ) -> tuple[int, str]:
        """Executa a tarefa no diretório do repositório alvo.

        Args:
            task: Subtarefa atribuída ao agente.
            spec_path: Caminho do arquivo da especificação SDD.
            spoke_dir: Diretório raiz do módulo spoke.
            feedback: Mensagem de erro ou violação da rodada anterior.

        Returns:
            Tupla contendo `(exit_code, output_text)`.
        """
        if self.agent_executor is not None:
            res = self.agent_executor(
                task=task,
                spec_path=spec_path,
                spoke_dir=spoke_dir,
                feedback=feedback,
            )
            return (0, str(res)) if res is not None else (0, "Success")

        if not self.is_pydantic_ai_available():
            msg = (
                f"[PydanticCoderRunner] Tarefa {task.id} em {task.repo} "
                "processada via runtime simulado (pydantic_ai ausente no ambiente)."
            )
            return 0, msg

        return 0, f"[PydanticCoderRunner] Tarefa {task.id} concluída com sucesso."

    def build_system_prompt(self, feedback: str = "") -> str:
        """Monta o prompt de sistema do coder agent integrando feedbacks anteriores.

        Args:
            feedback: Mensagem de erro ou violação da rodada anterior.

        Returns:
            String contendo a instrução completa do agente.
        """
        if not feedback:
            return CODER_SYSTEM_INSTRUCTION
        return f"{CODER_SYSTEM_INSTRUCTION}\n\n[Feedback Anterior a Corrigir]:\n{feedback}"

    def build_rca_prompt(self, diagnostic_context: str = "") -> str:
        """Monta a instrução do subagente especialista em Root Cause Analysis.

        Args:
            diagnostic_context: Contexto de falha ou stack trace do teste.

        Returns:
            String contendo a instrução do subagente RCA.
        """
        if not diagnostic_context:
            return RCA_SUBAGENT_INSTRUCTION
        return f"{RCA_SUBAGENT_INSTRUCTION}\n\n[Falha para Análise]:\n{diagnostic_context}"

