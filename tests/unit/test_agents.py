"""Testes unitários para detecção e execução de agentes de IA locais (TDD)."""

import json
import subprocess
from pathlib import Path

from harness_state.agents import (
    AgentDetector,
    AgentRunner,
    AgentSelector,
    AiderOutputParser,
    AntigravityOutputParser,
    DefaultAgentOutputParser,
    DetectedAgent,
    get_agent_output_parser,
    normalize_opencode_model,
)
from harness_state.models import SubTask


class MappingResolver:
    """Fake path resolver that looks binary names up in a fixed mapping."""

    def __init__(self, mapping: dict[str, str]) -> None:
        """Initializes the resolver.

        Args:
            mapping: Binary name to resolved path.
        """
        self.mapping = mapping

    def __call__(self, name: str, path: str | None = None) -> str | None:
        """Resolves a binary name.

        Args:
            name: Binary name.
            path: Ignored search path.

        Returns:
            The mapped path or None when unknown.
        """
        return self.mapping.get(name)


class CapturingSubprocess:
    """Fake subprocess runner that records commands, kwargs and envs."""

    def __init__(self, stdout: str, stderr: str | None = None) -> None:
        """Initializes the fake runner.

        Args:
            stdout: Standard output returned for every call.
            stderr: Standard error returned for every call.
        """
        self.stdout = stdout
        self.stderr = stderr
        self.cmds: list[list[str]] = []
        self.kwargs: list[dict] = []
        self.envs: list[dict[str, str]] = []

    def __call__(
        self,
        cmd: list[str],
        env: dict[str, str] | None = None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """Records the call and returns a successful process.

        Args:
            cmd: Command line.
            env: Optional environment, recorded only when non-empty.
            **kwargs: Extra keyword arguments, recorded.

        Returns:
            A completed process with returncode 0.
        """
        self.cmds.append(cmd)
        self.kwargs.append(kwargs)
        if env:
            self.envs.append(env)
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=self.stdout, stderr=self.stderr
        )


class ProcSubprocess:
    """Fake subprocess runner emulating socket listing output of a server."""

    def __call__(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Returns fake socket listing output or an empty JSON payload.

        Args:
            cmd: Command line.
            **kwargs: Ignored keyword arguments.

        Returns:
            A completed process with returncode 0.
        """
        if cmd[0] == "ss":
            stdout_text = (
                "LISTEN 0 4096 127.0.0.1:37061 0.0.0.0:* "
                'users:(("language_server",pid=12345,fd=23))\n'
            )
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout=stdout_text, stderr=""
            )
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="{}", stderr=""
        )


def test_agent_detector_finds_antigravity_explicitly(tmp_path: Path) -> None:
    """Business Rule: O detector busca intencionalmente a CLI do Antigravity."""
    fake_cli_bin = tmp_path / "agentapi"
    fake_cli_bin.write_text("#!/bin/sh\necho agentapi\n", encoding="utf-8")
    fake_cli_bin.chmod(0o755)

    fake_resolver = MappingResolver(
        {"agentapi": str(fake_cli_bin), "agy": str(fake_cli_bin)}
    )

    detector = AgentDetector(
        additional_paths=[str(tmp_path)],
        path_resolver=fake_resolver,
        environ={},
    )

    detected = detector.detect_antigravity()
    assert detected is not None
    assert detected.id == "antigravity"
    assert "CLI" in detected.name
    assert detected.binary_path == str(fake_cli_bin)


def test_agent_detector_finds_all_available_local_agents(tmp_path: Path) -> None:
    """Business Rule: O detector lista todos os agentes suportados no sistema."""
    spoke_dir = tmp_path / "my-spoke"
    spoke_dir.mkdir()
    scripts_dir = spoke_dir / "scripts"
    scripts_dir.mkdir()
    agent_script = scripts_dir / "agent.sh"
    agent_script.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    agent_script.chmod(0o755)

    fake_resolver = MappingResolver(
        {
            "agentapi": "/home/user/.gemini/antigravity/bin/agentapi",
            "claude": "/usr/local/bin/claude",
            "opencode": "/home/user/.opencode/bin/opencode",
            "aider": "/usr/local/bin/aider",
        }
    )

    detector = AgentDetector(path_resolver=fake_resolver)
    agents = detector.detect_all(project_root=spoke_dir)

    agent_ids = [a.id for a in agents]
    assert "antigravity" in agent_ids
    assert "claude" in agent_ids
    assert "opencode" in agent_ids
    assert "aider-ollama" in agent_ids
    assert "harness-agent" in agent_ids


def test_agent_selector_in_ci_mode_chooses_default_without_prompt() -> None:
    """Business Rule: O modo Cloud/CI escolhe o agente sem interrupção humana."""
    agents = [
        DetectedAgent(
            id="claude",
            name="Claude Code",
            binary_path="/bin/claude",
            description="Claude CLI",
        ),
        DetectedAgent(
            id="harness-agent",
            name="Harness Script",
            binary_path="scripts/agent.sh",
            description="Spoke script",
        ),
    ]

    selector = AgentSelector()
    chosen = selector.select(agents=agents, ci_mode=True)

    assert chosen is not None
    assert chosen.id == "harness-agent"


def test_agent_selector_respects_explicit_requested_agent() -> None:
    """Business Rule: O seletor respeita o agente explicitamente passado via CLI."""
    agents = [
        DetectedAgent(
            id="antigravity",
            name="Google Antigravity",
            binary_path="/snap/bin/antigravity",
            description="AGY",
        ),
        DetectedAgent(
            id="claude",
            name="Claude Code",
            binary_path="/bin/claude",
            description="Claude CLI",
        ),
    ]

    selector = AgentSelector()
    chosen = selector.select(
        agents=agents,
        requested_agent_id="antigravity",
        ci_mode=False,
    )

    assert chosen is not None
    assert chosen.id == "antigravity"


def test_agent_selector_interactive_prompts_user_choice() -> None:
    """Business Rule: O modo local interativo permite a escolha do usuário."""
    agents = [
        DetectedAgent(
            id="antigravity",
            name="Google Antigravity",
            binary_path="/snap/bin/antigravity",
            description="AGY",
        ),
        DetectedAgent(
            id="opencode",
            name="OpenCode",
            binary_path="/bin/opencode",
            description="OpenCode CLI",
        ),
    ]

    # Simula o usuário digitando '2' (opencode)
    selector = AgentSelector()
    chosen = selector.select(
        agents=agents,
        ci_mode=False,
        prompt_fn=lambda msg: "2",
    )

    assert chosen is not None
    assert chosen.id == "opencode"


def test_agent_runner_builds_prompt_and_executes_task(tmp_path: Path) -> None:
    """Business Rule: O AgentRunner gera prompt estruturado e aciona o executável."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    harness_dir = repo_dir / ".harness"
    harness_dir.mkdir()

    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# SPEC-004: Pipeline\nRegras de negócio.", encoding="utf-8")

    task = SubTask(
        id="task-1",
        repo="paralax-ia/crm",
        branch="feat/spec-004",
        wave=1,
    )

    mock_subprocess = CapturingSubprocess(stdout="Code written", stderr="")
    executed_cmds = mock_subprocess.cmds

    agent = DetectedAgent(
        id="claude",
        name="Claude Code",
        binary_path="/bin/claude",
        description="Claude CLI",
    )

    runner = AgentRunner(subprocess_runner=mock_subprocess)
    code, output = runner.run(
        agent=agent,
        target_repo_dir=repo_dir,
        task=task,
        spec_path=spec_file,
        feedback="lint error in models.py",
    )

    assert code == 0
    assert output == "Code written"
    assert len(executed_cmds) == 1
    assert executed_cmds[0][0] == "/bin/claude"
    # Prompt deve conter referência à spec e ao feedback anterior
    prompt_file = repo_dir / ".harness/current_task_prompt.md"
    assert prompt_file.is_file()
    content = prompt_file.read_text(encoding="utf-8")
    assert "SPEC-004" in content
    assert "lint error in models.py" in content


def test_agent_detector_default_shutil_which_runs_without_error() -> None:
    """Business Rule: O AgentDetector padrão utiliza shutil.which sem erro de tipo."""
    detector = AgentDetector()
    agents = detector.detect_all()
    assert isinstance(agents, list)


def test_agent_detector_finds_snap_language_server(tmp_path: Path) -> None:
    """Business Rule: Detecta o executável language_server do snap como fallback CLI."""
    snap_antigravity_dir = (
        tmp_path
        / "snap"
        / "antigravity"
        / "51"
        / "opt"
        / "antigravity"
        / "resources"
        / "bin"
    )
    snap_antigravity_dir.mkdir(parents=True)
    fake_server = snap_antigravity_dir / "language_server"
    fake_server.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_server.chmod(0o755)

    fake_resolver = MappingResolver({})

    detector = AgentDetector(
        additional_paths=[],
        path_resolver=fake_resolver,
        snap_base_dir=tmp_path / "snap" / "antigravity",
        environ={},
    )
    detected = detector.detect_antigravity()
    assert detected is not None
    assert detected.id == "antigravity"
    assert detected.binary_path == str(fake_server)


def test_agent_runner_discovers_antigravity_env_from_proc(tmp_path: Path) -> None:
    """Business Rule: Auto-descobre endereço e token inspecionando processo."""
    proc_dir = tmp_path / "proc"
    proc_dir.mkdir()
    pid_dir = proc_dir / "12345"
    pid_dir.mkdir()
    cmdline_file = pid_dir / "cmdline"
    cmdline_bytes = b"/bin/language_server\0--csrf_token\0my-secret-token-123\0"
    cmdline_file.write_bytes(cmdline_bytes)

    fake_subprocess = ProcSubprocess()

    runner = AgentRunner(
        subprocess_runner=fake_subprocess,
        proc_path=proc_dir,
        environ={},
    )
    env_vars = runner.discover_antigravity_environment()

    assert env_vars.get("ANTIGRAVITY_LS_ADDRESS") == "127.0.0.1:37061"
    assert env_vars.get("ANTIGRAVITY_CSRF_TOKEN") == "my-secret-token-123"


def test_agent_runner_returns_error_when_antigravity_not_running(
    tmp_path: Path,
) -> None:
    """Business Rule: Erro descritivo quando o Antigravity não estiver ativo."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# Spec", encoding="utf-8")
    task = SubTask(id="task-1", repo="repo", branch="main", wave=1)

    runner = AgentRunner(
        subprocess_runner=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0),
        proc_path=tmp_path / "empty_proc",
        environ={},
    )
    agent = DetectedAgent(
        id="antigravity",
        name="Google Antigravity CLI",
        binary_path="/snap/bin/agentapi",
        description="AGY",
    )
    code, output = runner.run(
        agent=agent, target_repo_dir=repo_dir, task=task, spec_path=spec_file
    )
    assert code == 1
    assert "Language Server não está em execução" in output


def test_agent_runner_executes_official_agy_cli_with_skip_permissions(
    tmp_path: Path,
) -> None:
    """Business Rule: A CLI agy executa em stream-json com permissões puladas."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# Spec de Vendas", encoding="utf-8")
    task = SubTask(id="task-1", repo="repo", branch="main", wave=1)

    fake_subprocess = CapturingSubprocess(stdout="DONE")
    captured_cmds = fake_subprocess.cmds
    captured_kwargs = fake_subprocess.kwargs

    runner = AgentRunner(
        subprocess_runner=fake_subprocess,
        proc_path=tmp_path / "empty_proc",
        environ={},
    )
    agent = DetectedAgent(
        id="antigravity",
        name="Google Antigravity CLI",
        binary_path="/home/user/.local/bin/agy",
        description="Google Antigravity CLI oficial (agy)",
    )
    code, output = runner.run(
        agent=agent, target_repo_dir=repo_dir, task=task, spec_path=spec_file
    )

    assert code == 0
    assert output == "DONE"
    assert len(captured_cmds) == 1
    assert captured_cmds[0][0] == "/home/user/.local/bin/agy"
    assert "--input-format" in captured_cmds[0]
    assert "--output-format" in captured_cmds[0]
    assert "--dangerously-skip-permissions" in captured_cmds[0]
    assert "input" in captured_kwargs[0]
    assert '"event": "user"' in captured_kwargs[0]["input"]


def test_agent_runner_format_agent_stream_output() -> None:
    """Business Rule: Formata eventos de streaming NDJSON do Antigravity."""
    runner = AgentRunner()
    agent = DetectedAgent(
        id="antigravity",
        name="Google Antigravity CLI",
        binary_path="/bin/agy",
        description="AGY",
    )
    collected: list[str] = []

    init_line = '{"event": "init", "conversation_id": "12345678-abcd"}\n'
    out_init, conv_id = runner._format_agent_stream_output(agent, init_line, collected)
    assert out_init is not None
    assert "Sessão iniciada (12345678)" in out_init
    assert conv_id == "12345678-abcd"

    step_line = (
        '{"event": "step_update", "step_update": {"step_index": 2, '
        '"text_delta": "thinking token..."}}\n'
    )
    out_step, _ = runner._format_agent_stream_output(agent, step_line, collected)
    assert out_step == "thinking token..."

    result_line = (
        '{"event": "result", "result": {"status": "SUCCESS", "response": "OK"}}\n'
    )
    out_result, _ = runner._format_agent_stream_output(agent, result_line, collected)
    assert out_result is not None
    assert "Concluído com status: SUCCESS" in out_result
    assert collected == ["OK"]


def test_agent_runner_formats_transcript_thinking_and_tools(tmp_path: Path) -> None:
    """Business Rule: Extrai e formata pensamento e ferramentas do transcript."""
    runner = AgentRunner()
    transcript_file = tmp_path / "transcript.jsonl"
    step1 = {
        "step_index": 1,
        "source": "MODEL",
        "type": "PLANNER_RESPONSE",
        "thinking": "Analisando arquitetura do projeto\ne dependências.",
        "tool_calls": [
            {
                "name": "view_file",
                "args": {
                    "toolAction": "Lendo pyproject.toml",
                },
            }
        ],
    }
    step2 = {
        "step_index": 2,
        "source": "MODEL",
        "type": "GENERIC",
        "content": "The command exited with code 0.",
    }
    transcript_file.write_text(
        json.dumps(step1) + "\n" + json.dumps(step2) + "\n",
        encoding="utf-8",
    )

    next_idx, events = runner._read_new_transcript_events(
        transcript_path=transcript_file,
        start_line_idx=0,
        agent_name="Google Antigravity CLI",
    )

    assert next_idx == 2
    full_output = "".join(events)
    assert "💭 [Google Antigravity CLI Pensamento - Passo 1]:" in full_output
    assert "Analisando arquitetura do projeto" in full_output
    assert "🔧 [Google Antigravity CLI Ferramenta - Passo 1]: view_file" in full_output
    assert "Lendo pyproject.toml" in full_output
    assert "⚡ The command exited with code 0." in full_output


def test_agent_detector_detects_opencode_ollama_from_config(tmp_path: Path) -> None:
    """Business Rule: Detecta o provedor Ollama remoto configurado no OpenCode."""
    opencode_cfg = tmp_path / "opencode.json"
    cfg_content = """{
      "provider": {
        "ollama-local": {
          "name": "Ollama Externo",
          "models": {
            "qwen2.5-coder:14b": {"name": "Qwen 2.5 Coder 14B"}
          }
        }
      }
    }"""
    opencode_cfg.write_text(cfg_content, encoding="utf-8")

    fake_resolver = MappingResolver({"opencode": "/home/user/.opencode/bin/opencode"})

    detector = AgentDetector(
        path_resolver=fake_resolver,
        opencode_config_path=opencode_cfg,
    )

    ollama_agent = detector.detect_opencode_ollama()
    assert ollama_agent is not None
    assert ollama_agent.id == "opencode-ollama"
    assert "Ollama Externo" in ollama_agent.name
    assert ollama_agent.default_model == "ollama-local/qwen2.5-coder:14b"

    all_agents = detector.detect_all()
    agent_ids = [a.id for a in all_agents]
    assert "opencode-ollama" in agent_ids
    assert "opencode" in agent_ids


def test_agent_runner_executes_opencode_with_model(tmp_path: Path) -> None:
    """Business Rule: O runner executa opencode com o modelo especificado e auto."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# Spec", encoding="utf-8")
    task = SubTask(id="task-1", repo="repo", branch="main", wave=1)

    fake_subprocess = CapturingSubprocess(stdout="OK")
    captured_cmds = fake_subprocess.cmds

    runner = AgentRunner(subprocess_runner=fake_subprocess)
    agent = DetectedAgent(
        id="opencode-ollama",
        name="OpenCode Ollama",
        binary_path="/bin/opencode",
        description="OpenCode CLI",
        default_model="ollama-local/qwen2.5-coder:14b",
    )
    code, output = runner.run(
        agent=agent, target_repo_dir=repo_dir, task=task, spec_path=spec_file
    )

    assert code == 0
    assert output == "OK"
    assert len(captured_cmds) == 1
    assert captured_cmds[0][0] == "/bin/opencode"
    assert captured_cmds[0][1] == "run"
    assert "--model" in captured_cmds[0]
    model_idx = captured_cmds[0].index("--model")
    assert captured_cmds[0][model_idx + 1] == "ollama-local/qwen2.5-coder:14b"
    assert "--auto" in captured_cmds[0]


def test_agent_detector_detects_aider_ollama(tmp_path: Path) -> None:
    """Business Rule: Detecta o Aider configurado com modelo agentic-qwen:7b."""
    fake_bin = tmp_path / "bin" / "aider"
    fake_bin.parent.mkdir(parents=True)
    fake_bin.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    fake_resolver = MappingResolver({"aider": str(fake_bin)})

    detector = AgentDetector(
        additional_paths=[str(fake_bin.parent)],
        path_resolver=fake_resolver,
        environ={},
    )
    detected = detector.detect_aider_ollama()
    assert detected is not None
    assert detected.id == "aider-ollama"
    assert "Ollama Remoto" in detected.name
    assert detected.default_model == "openai/agentic-qwen:7b"
    assert detected.binary_path == str(fake_bin)


def test_agent_detector_detect_all_orders_aider_ollama_second(
    tmp_path: Path,
) -> None:
    """Business Rule: Aider Ollama é posicionado como segunda opção na seleção."""
    fake_agy = tmp_path / "bin" / "agy"
    fake_agy.parent.mkdir(parents=True)
    fake_agy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_agy.chmod(0o755)

    fake_aider = tmp_path / "bin" / "aider"
    fake_aider.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_aider.chmod(0o755)

    fake_resolver = MappingResolver(
        {
            "agy": str(fake_agy),
            "agentapi": str(fake_agy),
            "aider": str(fake_aider),
        }
    )

    detector = AgentDetector(
        additional_paths=[str(fake_agy.parent)],
        path_resolver=fake_resolver,
        environ={},
    )
    agents = detector.detect_all()
    assert len(agents) >= 2
    assert agents[0].id == "antigravity"
    assert agents[1].id == "aider-ollama"


def test_antigravity_output_parser_format_and_transcript(tmp_path: Path) -> None:
    """Business Rule: AntigravityOutputParser processa stream e transcript."""
    parser = AntigravityOutputParser(agent_name="Google Antigravity CLI")

    init_line = json.dumps({"event": "init", "session_id": "sess-42"})
    init_msg, _ = parser.format_stream_line(init_line)
    assert "Sessão iniciada (sess-42)" in (init_msg or "")

    step_line = json.dumps(
        {"event": "step_update", "step_index": 3, "step_state": "ACTIVE"}
    )
    step_msg, _ = parser.format_stream_line(step_line)
    assert "Passo 3" in (step_msg or "")

    result_line = json.dumps(
        {"event": "result", "status": "COMPLETED", "summary": "Tudo certo"}
    )
    res_msg, _ = parser.format_stream_line(result_line)
    assert "COMPLETED: Tudo certo" in (res_msg or "")

    transcript_file = tmp_path / "transcript.jsonl"
    step1 = {
        "step_index": 1,
        "thinking": "Raciocínio interno",
        "tool_calls": [{"toolSummary": "Verificar arquivos"}],
    }
    transcript_file.write_text(json.dumps(step1) + "\n", encoding="utf-8")

    next_idx, events = parser.read_transcript_events(
        transcript_path=transcript_file,
        start_line_idx=0,
    )
    assert next_idx == 1
    output = "".join(events)
    assert "Pensamento - Passo 1" in output
    assert "Raciocínio interno" in output
    assert "Verificar arquivos" in output


def test_aider_output_parser_formats_edits_and_commits() -> None:
    """Business Rule: AiderOutputParser formata edições, commits e tokens."""
    parser = AiderOutputParser(agent_name="Aider (Ollama Remoto)")

    edit_msg, _ = parser.format_stream_line("Applied edit to src/models.py")
    assert edit_msg is not None
    assert "Applied edit to src/models.py" in edit_msg

    commit_msg, _ = parser.format_stream_line("Commit 1a2b3c4: feat: add models")
    assert commit_msg is not None
    assert "Commit 1a2b3c4" in commit_msg

    token_msg, _ = parser.format_stream_line("Tokens: 1.2k sent, 350 received.")
    assert token_msg is not None
    assert "Tokens: 1.2k sent" in token_msg

    plain_msg, _ = parser.format_stream_line("Normal reasoning output")
    assert plain_msg is not None
    assert "Normal reasoning output" in plain_msg

    empty_msg, _ = parser.format_stream_line("   ")
    assert empty_msg is None


def test_agent_runner_executes_aider_with_ollama_flags(tmp_path: Path) -> None:
    """Business Rule: AgentRunner injeta flags e ambiente para Aider com Ollama."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# Spec", encoding="utf-8")
    task = SubTask(id="task-1", repo="repo", branch="main", wave=1)

    key_file = tmp_path / "ollama_key"
    key_file.write_text("secret-test-token\n", encoding="utf-8")

    fake_subprocess = CapturingSubprocess(stdout="OK")
    captured_cmds = fake_subprocess.cmds
    captured_envs = fake_subprocess.envs

    runner = AgentRunner(
        subprocess_runner=fake_subprocess,
        ollama_key_path=key_file,
    )
    agent = DetectedAgent(
        id="aider-ollama",
        name="Aider (Ollama Remoto)",
        binary_path="/bin/aider",
        description="Aider CLI",
        default_model="openai/agentic-qwen:7b",
    )

    code, output = runner.run(
        agent=agent,
        target_repo_dir=repo_dir,
        task=task,
        spec_path=spec_file,
    )

    assert code == 0
    assert output == "OK"
    assert len(captured_cmds) == 1
    cmd = captured_cmds[0]
    assert cmd[0] == "/bin/aider"
    assert "--model" in cmd
    model_idx = cmd.index("--model")
    assert cmd[model_idx + 1] == "openai/agentic-qwen:7b"
    assert "--openai-api-base" in cmd
    base_idx = cmd.index("--openai-api-base")
    assert cmd[base_idx + 1] == "http://127.0.0.1:11434/v1"
    assert "--openai-api-key" in cmd
    key_idx = cmd.index("--openai-api-key")
    assert cmd[key_idx + 1] == "secret-test-token"
    assert "--yes-always" in cmd
    assert "--no-pretty" in cmd

    assert len(captured_envs) == 1
    assert captured_envs[0]["OPENAI_API_KEY"] == "secret-test-token"
    assert captured_envs[0]["OPENAI_API_BASE"] == "http://127.0.0.1:11434/v1"


def test_get_agent_output_parser_factory() -> None:
    """Business Rule: Fábrica instancia o parser correto para cada agente."""
    agy_agent = DetectedAgent(
        id="antigravity",
        name="Antigravity",
        binary_path="/bin/agy",
        description="",
    )
    assert isinstance(get_agent_output_parser(agy_agent), AntigravityOutputParser)

    aider_agent = DetectedAgent(
        id="aider-ollama",
        name="Aider Ollama",
        binary_path="/bin/aider",
        description="",
    )
    assert isinstance(get_agent_output_parser(aider_agent), AiderOutputParser)

    claude_agent = DetectedAgent(
        id="claude",
        name="Claude",
        binary_path="/bin/claude",
        description="",
    )
    assert isinstance(get_agent_output_parser(claude_agent), DefaultAgentOutputParser)


def test_normalize_opencode_model_adds_provider_prefix() -> None:
    """Business Rule: `opencode run --model` exige o formato `provider/model`.

    Nomes sem provedor (ex: `glm-5.3`) são rejeitados pelo opencode com
    `Invalid model reference`; devem ser qualificados com o provedor `opencode`.
    """
    assert normalize_opencode_model("glm-5.3") == "opencode/glm-5.3"
    assert normalize_opencode_model("opencode/glm-5.3") == "opencode/glm-5.3"
    assert (
        normalize_opencode_model("ollama-local/qwen2.5-coder:14b")
        == "ollama-local/qwen2.5-coder:14b"
    )


def test_agent_runner_qualifies_default_opencode_model(tmp_path: Path) -> None:
    """Business Rule: O modelo padrão do opencode é qualificado com provider."""
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    spec_file = tmp_path / "SPEC-004.md"
    spec_file.write_text("# Spec", encoding="utf-8")
    task = SubTask(id="task-1", repo="repo", branch="main", wave=1)
    fake_subprocess = CapturingSubprocess(stdout="OK")
    runner = AgentRunner(subprocess_runner=fake_subprocess, environ={})
    agent = DetectedAgent(
        id="opencode",
        name="OpenCode",
        binary_path="/bin/opencode",
        description="OpenCode CLI",
        default_model="glm-5.3-flash-free",
    )
    runner.run(agent=agent, target_repo_dir=repo_dir, task=task, spec_path=spec_file)

    cmd = fake_subprocess.cmds[0]
    assert cmd[cmd.index("--model") + 1] == "opencode/glm-5.3-flash-free"