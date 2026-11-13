"""Testes unitários para o gerenciador de ciclo de vida de prompts no Langfuse."""

import json
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from harness_state.prompt_manager import LangfusePromptManager, PromptManagementError


class RecordingUrlopen:
    """Fake `urllib.request.urlopen` that records every request."""

    def __init__(
        self,
        default_response: MagicMock,
        get_response: MagicMock | None = None,
    ) -> None:
        """Initializes the fake.

        Args:
            default_response: Response returned for non-GET requests (or all
                requests when no GET response is configured).
            get_response: Optional response returned for GET requests.
        """
        self.default_response = default_response
        self.get_response = get_response
        self.requests: list[object] = []

    def __call__(self, req: Any, **kwargs: Any) -> MagicMock:
        """Records the request and returns the configured response.

        Args:
            req: The request object.
            **kwargs: Ignored keyword arguments.

        Returns:
            The GET response for GET requests when configured, else the default.
        """
        self.requests.append(req)
        if self.get_response is not None and req.get_method() == "GET":
            return self.get_response
        return self.default_response


def test_langfuse_prompt_manager_not_configured_raises() -> None:
    """Business Rule: Rejeita operações no Langfuse caso credenciais ausentes."""
    manager = LangfusePromptManager(public_key="", secret_key="")
    with pytest.raises(PromptManagementError, match="Langfuse não configurado"):
        manager.fetch_prompt("paralax/support")


def test_fetch_prompt_success() -> None:
    """Business Rule: Baixa prompt e versão mais recente da API REST do Langfuse."""
    manager = LangfusePromptManager(
        public_key="pk-test", secret_key="sk-test", host="http://mock-langfuse"
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(
        {"name": "paralax/support", "prompt": "Instruções do agente", "version": 5}
    ).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        prompt_text, ver = manager.fetch_prompt("paralax/support")
        assert prompt_text == "Instruções do agente"
        assert ver == 5


def test_push_draft_enforces_non_production_label() -> None:
    """Business Rule: Impede publicação direta com label production no draft."""
    manager = LangfusePromptManager(
        public_key="pk-test", secret_key="sk-test", host="http://mock-langfuse"
    )

    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({"version": 6}).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    mock_urlopen = RecordingUrlopen(default_response=mock_resp)
    captured_requests = mock_urlopen.requests

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        # Tenta passar label production deliberadamente
        ver = manager.push_draft("paralax/support", "Novo texto", label="production")
        assert ver == 6

        request_body: Any = cast(Any, captured_requests[0]).data
        sent_payload = json.loads(request_body.decode("utf-8"))
        # Assegura que foi forçado para draft
        assert sent_payload["labels"] == ["draft"]


def test_promote_to_production_success() -> None:
    """Business Rule: Marca prompt com label production apenas pós-aprovação do PR."""
    manager = LangfusePromptManager(
        public_key="pk-test", secret_key="sk-test", host="http://mock-langfuse"
    )

    mock_fetch = MagicMock()
    mock_fetch.read.return_value = json.dumps(
        {"name": "paralax/support", "prompt": "Texto para produção", "version": 6}
    ).encode("utf-8")
    mock_fetch.__enter__.return_value = mock_fetch

    mock_promote = MagicMock()
    mock_promote.status = 201
    mock_promote.__enter__.return_value = mock_promote

    mock_urlopen = RecordingUrlopen(
        default_response=mock_promote, get_response=mock_fetch
    )
    captured = mock_urlopen.requests

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        ok = manager.promote_to_production("paralax/support", version=6)
        assert ok is True

        post_req = captured[1]
        request_body: Any = cast(Any, post_req).data
        sent_payload = json.loads(request_body.decode("utf-8"))
        assert sent_payload["labels"] == ["production"]


def test_update_local_fallback_replaces_multiline_instruction(tmp_path: Path) -> None:
    """Business Rule: Atualiza constante INSTRUCTION preservando docstrings."""
    prompts_file = tmp_path / "prompts.py"
    prompts_file.write_text(
        '"""Módulo de prompts."""\n\n'
        'GLOBAL_CONFIG = "active"\n\n'
        'INSTRUCTION = """<identity>\nPrompt antigo\n</identity>"""\n\n'
        "OTHER_VAR = 123\n",
        encoding="utf-8",
    )

    manager = LangfusePromptManager()
    new_prompt = "<identity>\nPrompt novo atualizado do Langfuse\n</identity>"
    success = manager.update_local_fallback(prompts_file, new_prompt)

    assert success is True
    updated_text = prompts_file.read_text(encoding="utf-8")
    assert 'GLOBAL_CONFIG = "active"' in updated_text
    assert "Prompt novo atualizado do Langfuse" in updated_text
    assert "Prompt antigo" not in updated_text
    assert "OTHER_VAR = 123" in updated_text
