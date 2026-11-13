"""Definições de agentes de IA para o ecossistema Harness (Onda 1).

Este módulo contém apenas as **definições** (dataclasses, config).
A **execução** (AgentRunner, AgentExecutor, AgentRuntime) permanece no flywheel.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


OPENCODE_PROVIDER = "opencode"
DEFAULT_OPENCODE_MODEL = f"{OPENCODE_PROVIDER}/glm-5.3-flash-free"


def normalize_opencode_model(model: str) -> str:
    """Qualifica o modelo no formato `provider/model` exigido pelo opencode.

    O `opencode run --model` rejeita nomes sem provedor com
    `Invalid model reference`. Nomes sem `/` são assumidos como do provedor
    `opencode`.

    Args:
        model: Identificador do modelo, com ou sem provedor.

    Returns:
        Identificador no formato `provider/model`.
    """
    if "/" in model:
        return model
    return f"{OPENCODE_PROVIDER}/{model}"


@dataclass(slots=True)
class DetectedAgent:
    """Representação de um agente de IA detectado no ambiente local.

    Attributes:
        id: Identificador canônico do agente (ex: 'antigravity', 'claude').
        name: Nome legível para exibição humana (ex: 'Google Antigravity').
        binary_path: Caminho do executável no sistema de arquivos.
        description: Breve descrição das capacidades ou escopo do agente.
        default_model: Modelo padrão opcional (ex: 'ollama-local/qwen2.5-coder:14b').
    """

    id: str
    name: str
    binary_path: str
    description: str
    default_model: str | None = None


@dataclass(slots=True)
class AgentConfig:
    """Configuração estática de um agente para uso pelo execution engine.

    Attributes:
        id: Identificador único do agente.
        name: Nome legível.
        default_model: Modelo padrão a ser usado.
        supported_modes: Modos de execução suportados (ex: 'stream-json', 'cli').
        env_vars: Variáveis de ambiente padrão necessárias.
        capabilities: Lista de capacidades do agente (ex: 'stream-json', 'transcript', 'tools').
    """

    id: str
    name: str
    default_model: str | None = None
    supported_modes: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    capabilities: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgentRunnerConfig:
    """Configuração de runtime para o AgentExecutor do flywheel.

    Atributos imutáveis passados para o AgentExecutor no momento da execução.
    """

    agent_id: str
    binary_path: str
    default_model: str | None = None
    continue_session: bool = True
    env_vars: dict[str, str] = field(default_factory=dict)
    working_dir: Path | None = None
    subprocess_runner: Any = None
    proc_path: Path | None = None
    ollama_key_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializa para dicionário (útil para logging/debug)."""
        return {
            "agent_id": self.agent_id,
            "binary_path": self.binary_path,
            "default_model": self.default_model,
            "continue_session": self.continue_session,
            "env_vars": self.env_vars,
            "working_dir": str(self.working_dir) if self.working_dir else None,
        }


# Catálogo estático de configurações de agentes conhecidos
KNOWN_AGENTS: dict[str, AgentConfig] = {
    "antigravity": AgentConfig(
        id="antigravity",
        name="Google Antigravity CLI",
        default_model="gemini-3.8-flash-high",
        supported_modes=["stream-json", "agentapi", "language_server"],
        env_vars={
            "ANTIGRAVITY_LS_ADDRESS": "",
            "ANTIGRAVITY_CSRF_TOKEN": "",
            "ANTIGRAVITY_MODEL": "gemini-3.8-flash-high",
        },
        capabilities=["stream-json", "transcript", "tools", "continue"],
    ),
    "claude": AgentConfig(
        id="claude",
        name="Claude Code",
        default_model="claude-3.5-sonnet",
        supported_modes=["cli"],
        env_vars={},
        capabilities=["continue"],
    ),
    "opencode": AgentConfig(
        id="opencode",
        name="OpenCode",
        default_model="glm-5.3-flash-free",
        supported_modes=["stream-json", "cli"],
        env_vars={
            "OPENCODE_MODEL": "glm-5.3-flash-free",
            "OPENCODE_API_KEY": "",
        },
        capabilities=["stream-json", "continue"],
    ),
    "aider": AgentConfig(
        id="aider",
        name="Aider",
        default_model="openai/agentic-qwen:7b",
        supported_modes=["cli"],
        env_vars={
            "OPENAI_API_BASE": "http://127.0.0.1:11434/v1",
            "OPENAI_API_KEY": "ollama",
            "OLLAMA_API_BASE": "http://127.0.0.1:11434",
        },
        capabilities=["continue"],
    ),
    "harness-agent": AgentConfig(
        id="harness-agent",
        name="Harness Spoke Agent",
        default_model=None,
        supported_modes=["bash"],
        env_vars={},
        capabilities=["script"],
    ),
}


def get_known_agent_config(agent_id: str) -> AgentConfig | None:
    """Retorna a configuração conhecida para um agent_id, se existir."""
    return KNOWN_AGENTS.get(agent_id.lower())