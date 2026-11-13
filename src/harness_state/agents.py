"""Definições de agentes de IA para o ecossistema Harness (Onda 1).

Este módulo contém apenas as **definições** (dataclasses, funções de detecção/seleção).
A **execução** (AgentRunner, AgentExecutor, AgentRuntime) permanece no flywheel.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harness_state.models import SubTask

OPENCODE_PROVIDER = "opencode"
DEFAULT_OPENCODE_MODEL = f"{OPENCODE_PROVIDER}/glm-5.3-flash-free"


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
    """Retorna a configuração conhecida para um agent_id, se existir.

    Args:
        agent_id: Identificador canônico do agente (case-insensitive).

    Returns:
        AgentConfig correspondente, ou None quando desconhecido.
    """
    return KNOWN_AGENTS.get(agent_id.lower())



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


class AgentDetector:
    """Detector e resolvedor de executáveis de agentes de IA locais."""

    def __init__(
        self,
        additional_paths: list[str] | None = None,
        path_resolver: Callable[..., str | None] | None = None,
        snap_base_dir: Path | None = None,
        environ: dict[str, str] | None = None,
        opencode_config_path: Path | None = None,
    ) -> None:
        """Inicializa o detector com caminhos conhecidos do ecossistema.

        Args:
            additional_paths: Lista opcional de diretórios extras a pesquisar.
            path_resolver: Função opcional para resolução de binários (mock em testes).
            snap_base_dir: Diretório base opcional do snap para testes.
            environ: Dicionário opcional de variáveis de ambiente.
            opencode_config_path: Caminho opcional do opencode.json para testes.
        """
        self.additional_paths = additional_paths or [
            os.path.expanduser("~/.gemini/antigravity-ide/bin"),
            os.path.expanduser("~/.gemini/antigravity/bin"),
            os.path.expanduser("~/.config/Antigravity/bin"),
            os.path.expanduser("~/.local/bin"),
            os.path.expanduser("~/.opencode/bin"),
            "/snap/bin",
            "/usr/local/bin",
            "/usr/bin",
        ]
        self.path_resolver = path_resolver or shutil.which
        self.snap_base_dir = snap_base_dir
        self.environ = environ if environ is not None else os.environ
        self.opencode_config_path = opencode_config_path

    def resolve_binary(self, binary_name: str) -> str | None:
        """Resolve o caminho de um binário no PATH ou nos diretórios adicionais.

        Args:
            binary_name: Nome do comando executável.

        Returns:
            Caminho absoluto do binário se encontrado, senão None.
        """
        path_env = os.environ.get("PATH", "")
        all_dirs = self.additional_paths + path_env.split(os.pathsep)
        search_path = os.pathsep.join(all_dirs)
        return self.path_resolver(binary_name, path=search_path)

    def _detect_antigravity_from_snap(self) -> DetectedAgent | None:
        """Localiza executável do Antigravity em diretórios Snap.

        Returns:
            Instância de DetectedAgent se localizado no snap, senão None.
        """
        snap_dir = self.snap_base_dir or Path("/snap/antigravity")
        if not snap_dir.is_dir():
            return None
        candidates = sorted(
            snap_dir.glob("*/opt/antigravity/resources/bin/language_server"),
            reverse=True,
        )
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return DetectedAgent(
                    id="antigravity",
                    name="Google Antigravity CLI",
                    binary_path=str(candidate),
                    description="Google Antigravity Agent CLI (agentapi)",
                )
        return None

    def detect_antigravity(self) -> DetectedAgent | None:
        """Detecta a CLI oficial do Google Antigravity (agy).

        Returns:
            Instância de DetectedAgent se a CLI do Antigravity for localizada.
        """
        for candidate in ["agy", "antigravity-cli"]:
            found = self.resolve_binary(candidate)
            if found is not None:
                default_model = self.environ.get(
                    "ANTIGRAVITY_MODEL", "gemini-3.8-flash-high"
                )
                return DetectedAgent(
                    id="antigravity",
                    name="Google Antigravity CLI",
                    binary_path=found,
                    description=(
                        "Google Antigravity CLI oficial "
                        f"(agy - modelo: {default_model})"
                    ),
                    default_model=default_model,
                )

        env_exe = self.environ.get("ANTIGRAVITY_EXE")
        if env_exe and os.path.isfile(env_exe) and os.access(env_exe, os.X_OK):
            return DetectedAgent(
                id="antigravity",
                name="Google Antigravity CLI",
                binary_path=env_exe,
                description="Google Antigravity CLI configurado via ANTIGRAVITY_EXE",
            )

        agentapi = self.resolve_binary("agentapi")
        if agentapi is not None:
            return DetectedAgent(
                id="antigravity",
                name="Google Antigravity CLI",
                binary_path=agentapi,
                description="Google Antigravity Agent CLI (agentapi)",
            )

        legacy_env = self.environ.get("ANTIGRAVITY_AGENTAPI_EXE")
        if legacy_env and os.path.isfile(legacy_env) and os.access(legacy_env, os.X_OK):
            return DetectedAgent(
                id="antigravity",
                name="Google Antigravity CLI",
                binary_path=legacy_env,
                description="Google Antigravity Agent CLI (language_server)",
            )

        return self._detect_antigravity_from_snap()

    def detect_claude(self) -> DetectedAgent | None:
        """Detecta o Claude Code CLI.

        Returns:
            Instância de DetectedAgent se o Claude for localizado.
        """
        found = self.resolve_binary("claude")
        if found is not None:
            return DetectedAgent(
                id="claude",
                name="Claude Code",
                binary_path=found,
                description="Anthropic Claude Code CLI",
            )
        return None

    def detect_opencode(self) -> DetectedAgent | None:
        """Detecta o OpenCode CLI.

        Returns:
            Instância de DetectedAgent se o OpenCode for localizado.
        """
        found = self.resolve_binary("opencode")
        if found is not None:
            default_model = normalize_opencode_model(
                self.environ.get("OPENCODE_MODEL", DEFAULT_OPENCODE_MODEL)
            )
            return DetectedAgent(
                id="opencode",
                name="OpenCode",
                binary_path=found,
                description="OpenCode Interpreter CLI",
                default_model=default_model,
            )
        return None

    def _read_json_config(self, path: Path) -> dict[str, Any]:
        """Lê e analisa com segurança um arquivo JSON de configuração.

        Args:
            path: Caminho do arquivo JSON.

        Returns:
            Dicionário com o conteúdo analisado ou dicionário vazio se inválido.
        """
        try:
            raw_text = path.read_text(encoding="utf-8")
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except (OSError, json.JSONDecodeError):
            return {}
        return {}

    def _extract_ollama_agent_from_providers(
        self,
        found_binary: str,
        providers: dict[str, Any],
    ) -> DetectedAgent | None:
        """Extrai o agente OpenCode-Ollama do mapa de provedores do opencode.json.

        Args:
            found_binary: Caminho resolvido do executável `opencode`.
            providers: Dicionário de provedores configurado no JSON.

        Returns:
            Instância de `DetectedAgent` se encontrar provedor Ollama com modelos.
        """
        for prov_key, prov_val in providers.items():
            if "ollama" not in prov_key.lower() or not isinstance(prov_val, dict):
                continue
            models = prov_val.get("models", {})
            if not models:
                continue
            first_model = next(iter(models.keys()))
            full_model_id = f"{prov_key}/{first_model}"
            prov_name = prov_val.get("name", "Ollama Remoto")
            return DetectedAgent(
                id="opencode-ollama",
                name=f"OpenCode ({prov_name})",
                binary_path=found_binary,
                description=f"OpenCode com modelo {first_model} via {prov_name}",
                default_model=full_model_id,
            )
        return None

    def detect_opencode_ollama(self) -> DetectedAgent | None:
        """Detecta o OpenCode configurado com provedor Ollama remoto/local.

        Returns:
            Instância de DetectedAgent se o OpenCode e a config Ollama existirem.
        """
        found = self.resolve_binary("opencode")
        if found is None:
            return None

        candidates = (
            [self.opencode_config_path]
            if self.opencode_config_path is not None
            else [
                Path(os.path.expanduser("~/.opencode/opencode.json")),
                Path(os.path.expanduser("~/.config/opencode/opencode.json")),
                Path(os.path.expanduser("~/.config/opencode.json")),
            ]
        )

        for cfg_path in candidates:
            if not cfg_path.is_file():
                continue
            data = self._read_json_config(cfg_path)
            providers = data.get("provider", {}) if data else {}
            agent = self._extract_ollama_agent_from_providers(found, providers)
            if agent is not None:
                return agent

        return None

    def detect_aider(self) -> DetectedAgent | None:
        """Detecta o Aider AI Pair Programmer.

        Returns:
            Instância de DetectedAgent se o Aider for localizado.
        """
        found = self.resolve_binary("aider")
        if found is not None:
            return DetectedAgent(
                id="aider",
                name="Aider",
                binary_path=found,
                description="Aider AI Pair Programmer",
            )
        return None

    def detect_aider_ollama(self) -> DetectedAgent | None:
        """Detecta o Aider configurado com o servidor Ollama remoto.

        Returns:
            Instância de DetectedAgent com modelo agentic-qwen:7b via Ollama.
        """
        found = self.resolve_binary("aider")
        if found is None:
            return None

        return DetectedAgent(
            id="aider-ollama",
            name="Aider (Ollama Remoto)",
            binary_path=found,
            description="Aider com modelo agentic-qwen:7b via Ollama Remoto",
            default_model="openai/agentic-qwen:7b",
        )

    def detect_harness_spoke_agent(
        self, project_root: Path | None = None
    ) -> DetectedAgent | None:
        """Detecta o script padrão do módulo (`scripts/agent.sh`).

        Args:
            project_root: Raiz opcional do módulo alvo.

        Returns:
            Instância de DetectedAgent se o script existir.
        """
        if project_root is None:
            return None
        script = project_root / "scripts/agent.sh"
        if script.is_file():
            return DetectedAgent(
                id="harness-agent",
                name="Harness Spoke Agent",
                binary_path=str(script),
                description="Script padrão do módulo (scripts/agent.sh com Ollama)",
            )
        return None

    def detect_all(self, project_root: Path | None = None) -> list[DetectedAgent]:
        """Detecta todos os agentes de IA disponíveis no ambiente local.

        Args:
            project_root: Raiz opcional do repositório/módulo alvo.

        Returns:
            Lista ordenada com todos os agentes detectados.
        """
        detected: list[DetectedAgent] = []

        antigravity_agent = self.detect_antigravity()
        if antigravity_agent is not None:
            detected.append(antigravity_agent)

        aider_ollama_agent = self.detect_aider_ollama()
        if aider_ollama_agent is not None:
            detected.append(aider_ollama_agent)

        opencode_ollama_agent = self.detect_opencode_ollama()
        if opencode_ollama_agent is not None:
            detected.append(opencode_ollama_agent)

        claude_agent = self.detect_claude()
        if claude_agent is not None:
            detected.append(claude_agent)

        opencode_agent = self.detect_opencode()
        if opencode_agent is not None:
            detected.append(opencode_agent)

        aider_agent = self.detect_aider()
        if aider_agent is not None and (
            aider_ollama_agent is None
            or aider_agent.binary_path != aider_ollama_agent.binary_path
        ):
            detected.append(aider_agent)

        spoke_agent = self.detect_harness_spoke_agent(project_root)
        if spoke_agent is not None:
            detected.append(spoke_agent)

        return detected


class AgentSelector:
    """Seletor de agente de IA para execução de tarefas (interativo ou CI)."""

    def _select_by_requested_id(
        self,
        agents: list[DetectedAgent],
        requested_agent_id: str,
    ) -> DetectedAgent:
        """Seleciona o agente que corresponde ao ID ou nome solicitado.

        Args:
            agents: Lista de agentes detectados.
            requested_agent_id: Identificador solicitado pelo usuário.

        Returns:
            Instância de `DetectedAgent` correspondente.

        Raises:
            ValueError: Caso nenhum agente corresponda ao ID solicitado.
        """
        req_lower = requested_agent_id.strip().lower()
        for agent in agents:
            if agent.id.lower() == req_lower:
                return agent
        for agent in agents:
            if req_lower in agent.name.lower():
                return agent
        available_names = ", ".join(a.id for a in agents)
        raise ValueError(
            f"Agente '{requested_agent_id}' não encontrado. "
            f"Disponíveis: {available_names}"
        )

    def _select_for_ci_mode(self, agents: list[DetectedAgent]) -> DetectedAgent:
        """Seleciona o agente prioritário para execução em ambiente CI/Cloud.

        Args:
            agents: Lista de agentes detectados.

        Returns:
            Agente selecionado segundo a ordem `harness-agent > opencode > aider`.
        """
        for preferred_id in ("harness-agent", "opencode", "aider"):
            for agent in agents:
                if agent.id == preferred_id:
                    return agent
        return agents[0]

    def select(
        self,
        agents: list[DetectedAgent],
        requested_agent_id: str | None = None,
        ci_mode: bool = False,
        prompt_fn: Callable[[str], str] | None = None,
    ) -> DetectedAgent | None:
        """Seleciona o agente baseado em preferência, CI ou prompt interativo.

        Args:
            agents: Lista de agentes disponíveis detectados.
            requested_agent_id: Nome ou ID explicitamente solicitado pelo usuário.
            ci_mode: Indica se a execução está em ambiente CI/Cloud.
            prompt_fn: Função opcional para captura de input interativo.

        Returns:
            DetectedAgent selecionado ou None se nenhum disponível.

        Raises:
            ValueError: Se o agente solicitado explicitamente não for encontrado.
        """
        if not agents:
            return None

        if requested_agent_id:
            return self._select_by_requested_id(agents, requested_agent_id)

        if ci_mode:
            return self._select_for_ci_mode(agents)

        active_prompt_fn = prompt_fn or input
        lines = ["\n[bold cyan]Agentes de IA detectados localmente:[/bold cyan]"]
        for idx, agent in enumerate(agents, start=1):
            agent_label = f"  {idx}) {agent.name} ({agent.binary_path})"
            lines.append(f"{agent_label} - {agent.description}")
        lines.append(f"Selecione o agente de IA [1-{len(agents)}] (Padrão: 1): ")
        choice_str = active_prompt_fn("\n".join(lines)).strip()
        if not choice_str:
            return agents[0]

        try:
            choice_idx = int(choice_str) - 1
            if 0 <= choice_idx < len(agents):
                return agents[choice_idx]
        except ValueError:
            pass

        return agents[0]


class BaseAgentOutputParser:
    """Classe base desacoplada para processamento de saída de agentes de IA."""

    def __init__(self, agent_name: str) -> None:
        """Inicializa o parser com o nome legível do agente.

        Args:
            agent_name: Nome do agente de IA para exibição de mensagens.
        """
        self.agent_name = agent_name

    def format_stream_line(
        self,
        raw_line: str,
        collected_responses: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Formata uma linha crua do stream do agente para exibição no terminal.

        Args:
            raw_line: Linha crua lida do stdout do processo.
            collected_responses: Lista acumuladora de respostas finais.

        Returns:
            Tupla contendo (texto_formatado_ou_None, metadado_ou_None).
        """
        line_str = raw_line.strip()
        if not line_str:
            return None, None
        return raw_line, None

    def read_transcript_events(
        self,
        metadata: str | None = None,
        start_line_idx: int = 0,
        transcript_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """Lê eventos adicionais assíncronos (ex: thinking/tools em transcript).

        Args:
            metadata: Metadado da sessão (ex: conversation_id do Antigravity).
            start_line_idx: Índice da linha inicial lida.
            transcript_path: Caminho direto opcional para o transcript.

        Returns:
            Tupla contendo (novo_indice, lista_de_mensagens_formatadas).
        """
        return start_line_idx, []


class AntigravityOutputParser(BaseAgentOutputParser):
    """Parser desacoplado para eventos stream-json e transcript do Antigravity."""

    def _format_step_update_event(
        self,
        data: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        """Formata um evento `step_update` do stream-json do Antigravity.

        Args:
            data: Dicionário do evento decodificado.

        Returns:
            Tupla `(texto_formatado_ou_None, None)`.
        """
        raw_update = data.get("step_update")
        step_data = raw_update if isinstance(raw_update, dict) else data
        text_delta = step_data.get("text_delta")
        if text_delta:
            return text_delta, None
        step_idx = step_data.get("step_index")
        step_state = step_data.get("step_state")
        if step_idx is not None and step_state:
            return (
                f"  ⏳ [{self.agent_name} Passo {step_idx}] Estado: {step_state}\n",
                None,
            )
        return None, None

    def _format_result_event(
        self,
        data: dict[str, Any],
        collected_responses: list[str] | None,
    ) -> tuple[str | None, str | None]:
        """Formata um evento `result` do stream-json do Antigravity.

        Args:
            data: Dicionário do evento decodificado.
            collected_responses: Lista acumuladora de respostas finais.

        Returns:
            Tupla `(texto_formatado_ou_None, None)`.
        """
        raw_res = data.get("result")
        res = raw_res if isinstance(raw_res, dict) else data
        status = res.get("status", "SUCCESS")
        response = res.get("response") or res.get("summary") or ""
        if response and collected_responses is not None:
            collected_responses.append(response)
        summary_suffix = f": {response}" if response else ""
        return (
            (
                f"\n  ✅ [{self.agent_name}] Concluído com status: "
                f"{status}{summary_suffix}\n"
            ),
            None,
        )

    def format_stream_line(
        self,
        raw_line: str,
        collected_responses: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Formata eventos JSON emitidos pelo Antigravity CLI.

        Args:
            raw_line: Linha crua lida do stdout do processo.
            collected_responses: Lista acumuladora de respostas finais.

        Returns:
            Tupla contendo `(texto_formatado_ou_None, conversation_id_ou_None)`.
        """
        line_str = raw_line.strip()
        if not line_str:
            return None, None

        if not line_str.startswith("{"):
            return raw_line, None

        try:
            data = json.loads(line_str)
        except (json.JSONDecodeError, ValueError):
            return raw_line, None

        event = data.get("event")
        if event == "init":
            conv_id = str(data.get("conversation_id") or data.get("session_id") or "")
            short_id = conv_id[:8]
            return f"  🚀 [{self.agent_name}] Sessão iniciada ({short_id})\n", conv_id

        if event == "step_update":
            return self._format_step_update_event(data)

        if event == "result":
            return self._format_result_event(data, collected_responses)

        return None, None

    def read_transcript_events(
        self,
        metadata: str | None = None,
        start_line_idx: int = 0,
        transcript_path: Path | None = None,
    ) -> tuple[int, list[str]]:
        """Lê passos adicionais persistidos no transcript.jsonl do Antigravity.

        Args:
            metadata: Conversation ID da sessão.
            start_line_idx: Índice da linha inicial lida.
            transcript_path: Caminho direto opcional para o arquivo transcript.

        Returns:
            Tupla contendo `(proximo_indice, lista_de_mensagens)`.
        """
        if transcript_path is not None:
            return self.read_transcript_file(transcript_path, start_line_idx)
        if not metadata:
            return start_line_idx, []

        candidate_paths = [
            (
                Path.home()
                / ".gemini"
                / "antigravity-cli"
                / "brain"
                / metadata
                / ".system_generated"
                / "logs"
                / "transcript.jsonl"
            ),
            (
                Path.home()
                / ".gemini"
                / "antigravity"
                / "brain"
                / metadata
                / ".system_generated"
                / "logs"
                / "transcript.jsonl"
            ),
        ]
        for candidate in candidate_paths:
            if candidate.is_file():
                return self.read_transcript_file(candidate, start_line_idx)
        return self.read_transcript_file(candidate_paths[0], start_line_idx)

    def read_transcript_file(
        self,
        transcript_path: Path,
        start_line_idx: int,
    ) -> tuple[int, list[str]]:
        """Lê e formata passos a partir do caminho do arquivo transcript.jsonl.

        Args:
            transcript_path: Caminho do arquivo de transcript.
            start_line_idx: Índice da linha inicial.

        Returns:
            Tupla contendo `(novo_indice, lista_de_mensagens_formatadas)`.
        """
        if not transcript_path.is_file():
            return start_line_idx, []

        output_messages: list[str] = []
        current_idx = 0
        try:
            with transcript_path.open("r", encoding="utf-8") as f:
                for line in f:
                    current_idx += 1
                    if current_idx <= start_line_idx:
                        continue
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    parsed = json.loads(line_clean)
                    formatted = self.format_transcript_step(parsed)
                    if formatted:
                        output_messages.extend(formatted)
        except (OSError, json.JSONDecodeError):
            return start_line_idx, []

        return current_idx, output_messages

    def _format_tool_call_line(self, idx: int, tool: dict[str, Any]) -> str:
        """Formata uma chamada de ferramenta do passo do transcript.

        Args:
            idx: Índice numérico do passo no transcript.
            tool: Dicionário com metadados da chamada de ferramenta.

        Returns:
            Linha formatada para exibição no terminal.
        """
        t_name = tool.get("name", "ferramenta")
        t_args = tool.get("args")
        args_dict = t_args if isinstance(t_args, dict) else {}
        raw_action = (
            tool.get("toolSummary")
            or tool.get("toolAction")
            or args_dict.get("toolAction")
            or args_dict.get("toolSummary")
            or ""
        )
        clean_action = str(raw_action).strip("\"'")
        action_suffix = f" ({clean_action})" if clean_action else ""
        return (
            f"🔧 [{self.agent_name} Ferramenta - Passo {idx}]: "
            f"{t_name}{action_suffix}\n"
        )

    def format_transcript_step(self, step_data: dict[str, Any]) -> list[str]:
        """Formata pensamento e chamadas de ferramenta de um passo do transcript.

        Args:
            step_data: Dicionário contendo os dados do passo do transcript.

        Returns:
            Lista de linhas formatadas para exibição.
        """
        messages: list[str] = []
        idx = step_data.get("step_index", 0)
        thinking = step_data.get("thinking")
        if thinking and str(thinking).strip():
            clean_lines = [
                f"  {line.strip()}"
                for line in str(thinking).strip().splitlines()
                if line.strip()
            ]
            thinking_body = "\n".join(clean_lines)
            messages.append(
                f"\n💭 [{self.agent_name} Pensamento - Passo {idx}]:\n{thinking_body}\n"
            )

        for tool in step_data.get("tool_calls", []):
            messages.append(self._format_tool_call_line(idx, tool))

        if (
            step_data.get("source") == "MODEL"
            and step_data.get("type") == "GENERIC"
            and step_data.get("content")
        ):
            for c_line in str(step_data["content"]).splitlines():
                if "exited with code" in c_line:
                    messages.append(f"  ⚡ {c_line.strip()}\n")

        return messages


class AiderOutputParser(BaseAgentOutputParser):
    """Parser desacoplado especializado na formatação da saída do Aider."""

    def format_stream_line(
        self,
        raw_line: str,
        collected_responses: list[str] | None = None,
    ) -> tuple[str | None, str | None]:
        """Formata uma linha emitida pelo Aider para exibição limpa no terminal.

        Args:
            raw_line: Linha crua lida do stdout do processo.
            collected_responses: Lista acumuladora de respostas finais.

        Returns:
            Tupla contendo `(texto_formatado_ou_None, None)`.
        """
        line_clean = raw_line.strip()
        if not line_clean:
            return None, None

        if "Applied edit to" in line_clean:
            return f"  📝 [{self.agent_name}]: {line_clean}\n", None

        if line_clean.startswith("Commit ") or (
            "commit" in line_clean.lower() and len(line_clean) < 120
        ):
            return f"  💾 [{self.agent_name}]: {line_clean}\n", None

        if line_clean.startswith("Tokens:"):
            return f"  ⚡ [{self.agent_name}]: {line_clean}\n", None

        if collected_responses is not None:
            collected_responses.append(raw_line)
        return raw_line, None


class DefaultAgentOutputParser(BaseAgentOutputParser):
    """Parser padrão para outros agentes de IA (Claude, OpenCode, scripts)."""


def get_agent_output_parser(agent: DetectedAgent) -> BaseAgentOutputParser:
    """Retorna o parser de saída especializado para o agente em execução.

    Args:
        agent: Instância do agente detectado.

    Returns:
        Instância desacoplada de BaseAgentOutputParser.
    """
    if agent.id == "antigravity":
        return AntigravityOutputParser(agent_name=agent.name)
    if agent.id in ("aider", "aider-ollama"):
        return AiderOutputParser(agent_name=agent.name)
    return DefaultAgentOutputParser(agent_name=agent.name)

class AgentRunner:
    """Executor que aciona o agente de IA escolhido para implementar a tarefa."""

    def __init__(
        self,
        subprocess_runner: Callable[..., subprocess.CompletedProcess] | None = None,
        proc_path: Path | None = None,
        environ: dict[str, str] | None = None,
        ollama_key_path: Path | None = None,
    ) -> None:
        """Inicializa o runner com função opcional de subprocess e procfs.

        Args:
            subprocess_runner: Função compatível com `subprocess.run`.
            proc_path: Caminho opcional do procfs para inspeção (mock em testes).
            environ: Dicionário opcional de variáveis de ambiente.
            ollama_key_path: Caminho opcional do arquivo de chave Ollama.
        """
        self.subprocess_runner = subprocess_runner or subprocess.run
        self.proc_path = proc_path or Path("/proc")
        self.environ = environ if environ is not None else os.environ
        self.ollama_key_path = ollama_key_path

    def _extract_csrf_token_from_args(self, args: list[bytes]) -> str | None:
        """Extrai o token CSRF da lista de argumentos do processo.

        Args:
            args: Argumentos do processo em bytes separados por null byte.

        Returns:
            Token CSRF decodificado ou None.
        """
        for idx, arg in enumerate(args):
            if arg == b"--csrf_token" and idx + 1 < len(args):
                return args[idx + 1].decode("utf-8", errors="ignore").strip()
            if arg.startswith(b"--csrf_token="):
                return arg.split(b"=", 1)[1].decode("utf-8", errors="ignore").strip()
        return None

    def _find_language_server_process(self) -> tuple[str | None, str | None]:
        """Localiza o PID e token CSRF do processo language_server ativo.

        Returns:
            Tupla contendo (pid, csrf_token) ou (None, None).
        """
        if not self.proc_path.is_dir():
            return None, None

        for entry in self.proc_path.iterdir():
            if not entry.name.isdigit():
                continue
            cmdline_file = entry / "cmdline"
            try:
                raw_bytes = cmdline_file.read_bytes()
            except (OSError, PermissionError):
                continue

            if b"language_server" in raw_bytes and b"--csrf_token" in raw_bytes:
                parts = raw_bytes.split(b"\0")
                token = self._extract_csrf_token_from_args(parts)
                if token:
                    return entry.name, token

        return None, None

    def _find_listening_ports_for_pid(self, pid: str) -> list[str]:
        """Identifica portas TCP locais em escuta associadas ao PID.

        Args:
            pid: Identificador numérico do processo.

        Returns:
            Lista de portas TCP locais encontradas.
        """
        try:
            res = self.subprocess_runner(
                ["ss", "-tlpn"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return []

        ports = []
        pattern = re.compile(rf"LISTEN\s+\d+\s+\d+\s+127\.0\.0\.1:(\d+).*pid={pid},")
        for line in (res.stdout or "").splitlines():
            match = pattern.search(line)
            if match:
                ports.append(match.group(1))
        return ports

    def _validate_language_server_port(
        self,
        ports: list[str],
        token: str,
        agent_binary_path: str,
    ) -> str | None:
        """Valida qual porta em escuta responde adequadamente ao comando gRPC.

        Args:
            ports: Lista de portas TCP candidatas.
            token: Token CSRF do Language Server.
            agent_binary_path: Caminho do binário para executar o probe.

        Returns:
            Porta validada ou a primeira porta disponível como fallback.
        """
        if not agent_binary_path or not os.path.isfile(agent_binary_path):
            return ports[0] if ports else None

        probe_cmd = [agent_binary_path]
        if agent_binary_path.endswith("language_server"):
            probe_cmd.append("agentapi")
        probe_cmd.extend(["get-conversation-metadata", "healthcheck-probe"])

        for port in ports:
            test_env = os.environ.copy()
            test_env["ANTIGRAVITY_LS_ADDRESS"] = f"127.0.0.1:{port}"
            test_env["ANTIGRAVITY_CSRF_TOKEN"] = token
            try:
                res = self.subprocess_runner(
                    probe_cmd,
                    env=test_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                output = (res.stdout or "") + (res.stderr or "")
                if "connection error:" not in output:
                    return port
            except OSError:
                continue

        return ports[0] if ports else None

    def discover_antigravity_environment(
        self,
        agent_binary_path: str = "",
    ) -> dict[str, str]:
        """Descobre as variáveis de ambiente necessárias para o Antigravity.

        Verifica se ANTIGRAVITY_LS_ADDRESS e ANTIGRAVITY_CSRF_TOKEN já constam
        em os.environ. Caso contrário, localiza o processo ativo do Language Server
        em /proc, extrai o token CSRF e detecta a porta de escuta ativa via ss.

        Args:
            agent_binary_path: Caminho opcional do executável para teste de validação.

        Returns:
            Dicionário com ANTIGRAVITY_LS_ADDRESS e ANTIGRAVITY_CSRF_TOKEN se
            localizados, senão dicionário vazio.
        """
        env_address = self.environ.get("ANTIGRAVITY_LS_ADDRESS")
        env_token = self.environ.get("ANTIGRAVITY_CSRF_TOKEN")
        if env_address and env_token:
            return {
                "ANTIGRAVITY_LS_ADDRESS": env_address,
                "ANTIGRAVITY_CSRF_TOKEN": env_token,
            }

        target_pid, discovered_token = self._find_language_server_process()
        if not target_pid or not discovered_token:
            return {}

        ports = self._find_listening_ports_for_pid(target_pid)
        if not ports:
            return {}

        selected_port = self._validate_language_server_port(
            ports=ports,
            token=discovered_token,
            agent_binary_path=agent_binary_path,
        )
        if not selected_port:
            selected_port = ports[0]

        return {
            "ANTIGRAVITY_LS_ADDRESS": f"127.0.0.1:{selected_port}",
            "ANTIGRAVITY_CSRF_TOKEN": discovered_token,
        }

    def _resolve_ollama_settings(self) -> tuple[str, str]:
        """Resolve o endpoint base e token do servidor Ollama remoto.

        Returns:
            Tupla contendo `(base_url, api_key)`.
        """
        base_url = (
            self.environ.get("OPENAI_API_BASE")
            or self.environ.get("OLLAMA_API_BASE")
            or self.environ.get("HARNESS_LLM_EXTERNAL_BASE_URL")
            or self.environ.get("LLM_BASE_URL")
            or "http://127.0.0.1:11434/v1"
        )
        api_key = ""
        if self.ollama_key_path and self.ollama_key_path.is_file():
            try:
                api_key = self.ollama_key_path.read_text(encoding="utf-8").strip()
            except OSError:
                api_key = ""

        if not api_key:
            api_key = (
                self.environ.get("OPENAI_API_KEY")
                or self.environ.get("OLLAMA_API_KEY")
                or ""
            )

        if not api_key:
            secrets_candidate = Path(os.path.expanduser("~/.secrets/ollama_key"))
            if secrets_candidate.is_file():
                try:
                    api_key = secrets_candidate.read_text(encoding="utf-8").strip()
                except OSError:
                    api_key = ""

        if not api_key:
            api_key = "ollama"

        return base_url, api_key

    def build_prompt(
        self,
        task: SubTask,
        spec_path: Path,
        feedback: str = "",
    ) -> str:
        """Constrói o prompt estruturado com a spec e eventuais feedbacks do sensor.

        Args:
            task: Subtarefa sendo executada.
            spec_path: Caminho da especificação SDD.
            feedback: Mensagem de erro/violação da rodada anterior de verificação.

        Returns:
            Texto formatado do prompt para o agente.
        """
        spec_content = ""
        if spec_path.is_file():
            try:
                spec_content = spec_path.read_text(encoding="utf-8")
            except OSError:
                spec_content = f"Spec: {spec_path}"

        prompt_parts = [
            f"# Task: {task.id} (Wave {task.wave}) in Repository: {task.repo}",
            f"Working branch: {task.branch}",
            "",
            "## SDD Specification:",
            spec_content,
            "",
            "## Mandatory Engineering Guidelines:",
            (
                "1. Test-Driven Development (TDD): Implement functionality "
                "following strict TDD (write unit tests first, verify they fail, "
                "then implement)."
            ),
            (
                "2. Test Docstrings: Every test function must have a Google-style "
                "docstring starting with 'Business Rule:' describing the rule "
                "under test."
            ),
            (
                "3. Code Style & Imports: Strictly comply with PEP 8 and Google "
                "Style Docstrings. Order all imports with isort."
            ),
            (
                "4. Architecture Constraints: NEVER define nested functions "
                "(except decorators), NEVER nest try-except blocks, NEVER use "
                "leading underscores on non-class members, NEVER catch import "
                "errors with try-except. Keep cognitive complexity <= 15 "
                "(enforced by complexipy) and apply any complexipy refactoring "
                "suggestions (guard clauses, continue guards, module/class helpers)."
            ),
            (
                "5. Verification Gate: Run verification sensors ('just verify') "
                "and ensure all tests and linter sensors pass."
            ),
        ]

        if feedback.strip():
            prompt_parts.extend(
                [
                    "",
                    "## [ATTENTION - PRESCRIPTIVE SENSOR FEEDBACK TO FIX]:",
                    feedback.strip(),
                    "Fix all reported sensor violations above before finishing.",
                ]
            )

        return "\n".join(prompt_parts)

    def run(
        self,
        agent: DetectedAgent,
        target_repo_dir: Path,
        task: SubTask,
        spec_path: Path,
        feedback: str = "",
        continue_session: bool = True,
    ) -> tuple[int, str]:
        """Executa o agente no diretório alvo com o prompt preparado.

        Args:
            agent: Agente selecionado para execução.
            target_repo_dir: Diretório raiz do módulo/repositório alvo.
            task: Subtarefa sendo executada.
            spec_path: Caminho da especificação.
            feedback: Mensagem opcional de feedback da última execução de sensores.
            continue_session: Retoma a sessão anterior se suportado pelo agente.

        Returns:
            Tupla contendo `(exit_code, output)`.
        """
        prompt_text = self.build_prompt(
            task=task, spec_path=spec_path, feedback=feedback
        )
        return self.run_prompt(
            agent=agent,
            working_dir=target_repo_dir,
            prompt_text=prompt_text,
            task_label=f"tarefa {task.id}",
            continue_session=continue_session,
        )

    def _is_agy_cli_binary(self, agent: DetectedAgent) -> bool:
        """Verifica se o binário do agente Antigravity é a CLI oficial `agy`.

        Args:
            agent: Agente detectado.

        Returns:
            True se for `agy`.
        """
        if agent.id != "antigravity":
            return False
        bin_name = Path(agent.binary_path).name
        return (
            bin_name == "agy" or agent.binary_path.endswith("/agy") or "agy" in bin_name
        )

    def _build_antigravity_command(
        self,
        agent: DetectedAgent,
        prompt_text: str,
        task_label: str,
        continue_session: bool,
        is_agy_cli: bool,
    ) -> tuple[list[str], str | None]:
        """Monta o comando e payload stdin para execução do Antigravity.

        Args:
            agent: Agente Antigravity.
            prompt_text: Texto do prompt.
            task_label: Rótulo descritivo da tarefa.
            continue_session: Indica se deve retomar sessão anterior.
            is_agy_cli: True se o binário for `agy`.

        Returns:
            Tupla `(cmd, stdin_payload)`.
        """
        if is_agy_cli:
            cmd = [
                agent.binary_path,
                "--input-format",
                "stream-json",
                "--output-format",
                "stream-json",
                "--dangerously-skip-permissions",
            ]
            if agent.default_model:
                cmd.extend(["--model", agent.default_model])
            if continue_session:
                cmd.append("--continue")
            payload = (
                json.dumps({"event": "user", "message": {"content": prompt_text}})
                + "\n"
            )
            return cmd, payload

        if agent.binary_path.endswith("language_server"):
            return (
                [
                    agent.binary_path,
                    "agentapi",
                    "new-conversation",
                    f"--title=Harness SDD {task_label}",
                    prompt_text,
                ],
                None,
            )

        if agent.binary_path.endswith("agentapi"):
            return (
                [
                    agent.binary_path,
                    "new-conversation",
                    f"--title=Harness SDD {task_label}",
                    prompt_text,
                ],
                None,
            )

        cmd = [
            agent.binary_path,
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--dangerously-skip-permissions",
        ]
        payload = (
            json.dumps({"event": "user", "message": {"content": prompt_text}}) + "\n"
        )
        return cmd, payload

    def _build_aider_command(
        self,
        agent: DetectedAgent,
        prompt_file: Path,
        continue_session: bool,
        run_env: dict[str, str],
    ) -> list[str]:
        """Monta o comando e variáveis de ambiente para execução do Aider.

        Args:
            agent: Agente Aider detectado.
            prompt_file: Caminho do arquivo de prompt.
            continue_session: Indica se deve retomar histórico.
            run_env: Dicionário mutável de variáveis de ambiente.

        Returns:
            Lista de argumentos do comando Aider.
        """
        model_name = agent.default_model or "openai/agentic-qwen:7b"
        if not model_name.startswith(("openai/", "ollama/")):
            model_name = f"openai/{model_name}"
        base_url, api_key = self._resolve_ollama_settings()
        cmd = [
            agent.binary_path,
            "--model",
            model_name,
            "--openai-api-base",
            base_url,
            "--openai-api-key",
            api_key,
            "--yes-always",
            "--message-file",
            str(prompt_file),
            "--no-pretty",
            "--no-show-model-warnings",
        ]
        if continue_session:
            cmd.append("--restore-chat-history")
        run_env["OPENAI_API_BASE"] = base_url
        run_env["OPENAI_API_KEY"] = api_key
        run_env["OLLAMA_API_BASE"] = base_url.rstrip("/v1")
        return cmd

    def _build_agent_command_and_stdin(
        self,
        agent: DetectedAgent,
        prompt_file: Path,
        prompt_text: str,
        task_label: str,
        continue_session: bool,
        is_agy_cli: bool,
        run_env: dict[str, str],
    ) -> tuple[list[str], str | None]:
        """Monta a linha de comando, variáveis extras e stdin para o agente.

        Args:
            agent: Agente selecionado.
            prompt_file: Caminho do arquivo de prompt persistido.
            prompt_text: Conteúdo completo do prompt.
            task_label: Rótulo descritivo da tarefa.
            continue_session: Indica se deve continuar a sessão anterior.
            is_agy_cli: True se for `agy`.
            run_env: Dicionário mutável de variáveis de ambiente.

        Returns:
            Tupla `(cmd, stdin_payload)`.
        """
        if agent.id == "harness-agent":
            return ["bash", agent.binary_path, "--task-file", str(prompt_file)], None

        if agent.id == "claude":
            summary = (
                f"Execute instructions for {task_label} according to "
                f"{prompt_file.name}. Read .harness/current_task_prompt.md."
            )
            cmd = [agent.binary_path, "-p", summary]
            if continue_session:
                cmd.append("--continue")
            return cmd, None

        if agent.id in ("opencode", "opencode-ollama"):
            model_name = normalize_opencode_model(
                agent.default_model
                or self.environ.get("OPENCODE_MODEL", DEFAULT_OPENCODE_MODEL)
            )
            cmd = [agent.binary_path, "run", "--model", model_name]
            if continue_session:
                cmd.append("--continue")
            cmd.extend(["--auto", prompt_text])
            opencode_key = self.environ.get("OPENCODE_API_KEY")
            if opencode_key:
                run_env["OPENCODE_API_KEY"] = opencode_key
            return cmd, None

        if agent.id in ("aider", "aider-ollama"):
            return (
                self._build_aider_command(
                    agent, prompt_file, continue_session, run_env
                ),
                None,
            )

        if agent.id == "antigravity":
            return self._build_antigravity_command(
                agent, prompt_text, task_label, continue_session, is_agy_cli
            )

        return [agent.binary_path, str(prompt_file)], None

    def _is_rate_limit_output(self, output: str) -> bool:
        """Verifica se a saída do processo indica erro de Rate Limit (429).

        Args:
            output: Saída textual combinada do agente.

        Returns:
            True se contiver assinatura de rate limit ou exaustão de cota.
        """
        markers = (
            "429",
            "RESOURCE_EXHAUSTED",
            "Too Many Requests",
            "credits balance is too low",
            "Resource has been exhausted",
        )
        return any(marker in output for marker in markers)

    def _stream_popen_execution(
        self,
        agent: DetectedAgent,
        cmd: list[str],
        working_dir: Path,
        run_env: dict[str, str],
        stdin_payload: str | None,
    ) -> tuple[int, str]:
        """Executa o processo do agente via `subprocess.Popen` com streaming ao vivo.

        Args:
            agent: Agente selecionado.
            cmd: Lista de argumentos do comando.
            working_dir: Diretório de trabalho.
            run_env: Variáveis de ambiente.
            stdin_payload: Payload opcional para escrita no stdin.

        Returns:
            Tupla `(returncode, final_output)`.
        """
        proc = subprocess.Popen(
            cmd,
            cwd=str(working_dir),
            env=run_env,
            stdin=(
                subprocess.PIPE if stdin_payload is not None else subprocess.DEVNULL
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        if stdin_payload is not None and proc.stdin is not None:
            proc.stdin.write(stdin_payload)
            proc.stdin.close()

        parser = get_agent_output_parser(agent)
        output_lines: list[str] = []
        collected_responses: list[str] = []
        session_meta: str | None = None
        last_transcript_line = 0

        if proc.stdout is not None:
            for line in proc.stdout:
                output_lines.append(line)
                display_line, new_meta = parser.format_stream_line(
                    raw_line=line,
                    collected_responses=collected_responses,
                )
                session_meta = session_meta or new_meta
                if display_line:
                    sys.stdout.write(display_line)
                    sys.stdout.flush()

                last_transcript_line, new_events = parser.read_transcript_events(
                    metadata=session_meta,
                    start_line_idx=last_transcript_line,
                )
                for event_msg in new_events:
                    sys.stdout.write(event_msg)
                    sys.stdout.flush()

        proc.wait()
        _, tail_events = parser.read_transcript_events(
            metadata=session_meta,
            start_line_idx=last_transcript_line,
        )
        for event_msg in tail_events:
            sys.stdout.write(event_msg)
            sys.stdout.flush()

        final_output = (
            "".join(collected_responses).strip()
            if collected_responses
            else "".join(output_lines).strip()
        )
        return proc.returncode, final_output

    def _execute_single_attempt(
        self,
        agent: DetectedAgent,
        cmd: list[str],
        working_dir: Path,
        run_env: dict[str, str],
        stdin_payload: str | None,
    ) -> tuple[int, str]:
        """Executa uma única tentativa do comando do agente (runner ou Popen).

        Args:
            agent: Agente selecionado.
            cmd: Lista de argumentos do comando.
            working_dir: Diretório de trabalho.
            run_env: Variáveis de ambiente.
            stdin_payload: Payload opcional para stdin.

        Returns:
            Tupla `(returncode, output)`.
        """
        if self.subprocess_runner != subprocess.run:
            run_kwargs: dict[str, Any] = {
                "cwd": str(working_dir),
                "env": run_env,
                "capture_output": True,
                "text": True,
                "check": False,
            }
            if stdin_payload is not None:
                run_kwargs["input"] = stdin_payload
            res = self.subprocess_runner(cmd, **run_kwargs)
            output = (res.stdout or "") + ("\n" + res.stderr if res.stderr else "")
            return res.returncode, output.strip()

        return self._stream_popen_execution(
            agent, cmd, working_dir, run_env, stdin_payload
        )

    def run_prompt(
        self,
        agent: DetectedAgent,
        working_dir: Path,
        prompt_text: str,
        task_label: str = "tarefa",
        continue_session: bool = True,
    ) -> tuple[int, str]:
        """Executa um prompt arbitrário utilizando o agente de IA configurado.

        Args:
            agent: Agente selecionado para execução.
            working_dir: Diretório de trabalho onde o agente será acionado.
            prompt_text: Conteúdo textual completo do prompt.
            task_label: Rótulo descritivo para mensagens de log no terminal.
            continue_session: Retoma a sessão anterior se suportado pelo agente.

        Returns:
            Tupla contendo `(exit_code, output)`.
        """
        harness_dir = (working_dir / ".harness").resolve()
        harness_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = (harness_dir / "current_task_prompt.md").resolve()
        prompt_file.write_text(prompt_text, encoding="utf-8")

        run_env = self.environ.copy()
        is_agy_cli = self._is_agy_cli_binary(agent)
        if agent.id == "antigravity" and not is_agy_cli:
            env_vars = self.discover_antigravity_environment(
                agent_binary_path=agent.binary_path
            )
            has_address = env_vars.get("ANTIGRAVITY_LS_ADDRESS") or self.environ.get(
                "ANTIGRAVITY_LS_ADDRESS"
            )
            if not has_address:
                return (
                    1,
                    (
                        "Google Antigravity Language Server não está em execução. "
                        "Certifique-se de que o Google Antigravity esteja aberto ou "
                        "selecione outro agente (ex: --agent claude, --agent opencode "
                        "ou --agent harness-agent)."
                    ),
                )
            run_env.update(env_vars)

        cmd, stdin_payload = self._build_agent_command_and_stdin(
            agent=agent,
            prompt_file=prompt_file,
            prompt_text=prompt_text,
            task_label=task_label,
            continue_session=continue_session,
            is_agy_cli=is_agy_cli,
            run_env=run_env,
        )

        max_retries = 3
        backoff_delay = 5.0

        for attempt in range(1, max_retries + 1):
            sys.stdout.write(f"  ⏳ Processando {task_label} com {agent.name}...\n")
            sys.stdout.flush()

            try:
                returncode, final_output = self._execute_single_attempt(
                    agent, cmd, working_dir, run_env, stdin_payload
                )
            except OSError as exc:
                return 1, f"Falha ao executar o agente {agent.name}: {exc}"

            if (
                returncode != 0
                and self._is_rate_limit_output(final_output)
                and attempt < max_retries
            ):
                wait_sec = backoff_delay * (2 ** (attempt - 1))
                sys.stdout.write(
                    f"\n  ⏳ [Rate Limit / 429 Detectado]: recurso "
                    f"esgotado ou limite atingido. Aguardando "
                    f"{wait_sec:.1f}s antes da tentativa "
                    f"{attempt + 1}/{max_retries}...\n"
                )
                sys.stdout.flush()
                time.sleep(wait_sec)
                continue

            return returncode, final_output

        return 1, "Falha na execução após tentativas de retry"

    def _read_new_transcript_events(
        self,
        transcript_path: Path,
        start_line_idx: int,
        agent_name: str,
    ) -> tuple[int, list[str]]:
        """Compatibilidade: delega a leitura ao AntigravityOutputParser.

        Args:
            transcript_path: Caminho para o transcript.jsonl da sessão.
            start_line_idx: Índice da linha inicial a ser lida.
            agent_name: Nome legível do agente para prefixo dos logs.

        Returns:
            Tupla com (proximo_indice_de_linha, lista_de_mensagens_formatadas).
        """
        parser = AntigravityOutputParser(agent_name=agent_name)
        return parser.read_transcript_file(transcript_path, start_line_idx)

    def _format_transcript_step(
        self,
        step_data: dict[str, Any],
        agent_name: str,
    ) -> list[str]:
        """Compatibilidade retroativa: delega ao AntigravityOutputParser.

        Args:
            step_data: Dicionário contendo os dados do passo do transcript.
            agent_name: Nome do agente para exibição.

        Returns:
            Lista de linhas formatadas com pensamento e ferramentas.
        """
        parser = AntigravityOutputParser(agent_name=agent_name)
        return parser.format_transcript_step(step_data)

    def _format_agent_stream_output(
        self,
        agent: DetectedAgent,
        raw_line: str,
        collected_responses: list[str],
    ) -> tuple[str | None, str | None]:
        """Compatibilidade retroativa: delega ao parser desacoplado do agente.

        Args:
            agent: Instância do agente em execução.
            raw_line: Linha crua lida do stdout do processo.
            collected_responses: Lista acumuladora de respostas finais.

        Returns:
            Tupla com (texto_formatado_ou_None, conversation_id_ou_None).
        """
        parser = get_agent_output_parser(agent)
        return parser.format_stream_line(raw_line, collected_responses)
