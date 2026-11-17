"""Testes unitários para o executor Pydantic AI Coder no harness-state."""

from pathlib import Path

import pytest

from harness_state.models import SubTask
from harness_state.runtimes.pydantic_coder import (
    PydanticCoderConfig,
    PydanticCoderRunner,
    resolve_pydantic_coder_settings,
)


def test_pydantic_coder_config_resolucao_ambiente() -> None:
    """Business Rule: PydanticCoderConfig deve ler variáveis de ambiente canônicas sem fallback para localhost."""
    custom_env = {
        "OPENAI_API_BASE": "http://runner.infra:11434/v1",
        "OPENAI_API_KEY": "secret-test-key",
        "LLM_DEFAULT_MODEL": "ollama:agentic-qwen:7b",
    }
    settings = resolve_pydantic_coder_settings(environ=custom_env)
    assert settings.base_url == "http://runner.infra:11434/v1"
    assert settings.api_key == "secret-test-key"
    assert settings.model_name == "ollama:agentic-qwen:7b"


@pytest.mark.asyncio
async def test_pydantic_coder_runner_executa_tarefa_mock(tmp_path: Path) -> None:
    """Business Rule: PydanticCoderRunner deve orquestrar a tarefa no spoke e retornar tupla (exit_code, output)."""
    cfg = PydanticCoderConfig(
        model_name="ollama:test",
        base_url="http://mock:11434/v1",
        api_key="mock",
        local_workspace_root=tmp_path,
    )
    runner = PydanticCoderRunner(config=cfg)
    task = SubTask(id="task-1", repo="repo", wave=1, branch="agent/task-1")
    spec_path = tmp_path / "SPEC-010.md"
    spec_path.write_text("# Spec", encoding="utf-8")

    exit_code, output = await runner.run_task(
        task=task,
        spec_path=spec_path,
        spoke_dir=tmp_path,
        feedback="",
    )
    assert isinstance(exit_code, int)
    assert isinstance(output, str)
    assert exit_code == 0


def test_pydantic_coder_prompts_construcao() -> None:
    """Business Rule: PydanticCoderRunner deve construir os prompts do coder e do subagente RCA."""
    runner = PydanticCoderRunner()
    system_prompt = runner.build_system_prompt(feedback="Erro de TDD anterior")
    assert "You are an autonomous senior software engineer" in system_prompt
    assert "Erro de TDD anterior" in system_prompt

    rca_prompt = runner.build_rca_prompt(diagnostic_context="AssertionError: Expected 200 got 500")
    assert "Root Cause Analysis (RCA)" in rca_prompt
    assert "AssertionError: Expected 200 got 500" in rca_prompt
