"""Testes da promoção atômica de prompts Langfuse (draft → production).

Business Rule central (definida pelo operador): a progressão é atômica —
ou todos os prompts são promovidos, ou o fluxo de fechamento NÃO prossegue.
"""

from unittest.mock import MagicMock, patch

from harness_state.prompt_manager import PromptManagementError
from harness_state.prompt_promotion import promote_prompts_to_production


def test_promote_prompts_calls_manager_for_each_name() -> None:
    """Business Rule: helper promove cada prompt informado via LangfusePromptManager."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True

    with patch(
        "harness_state.prompt_manager.LangfusePromptManager", return_value=mock_mgr
    ):
        outcome = promote_prompts_to_production(
            ["paralax/support", "paralax/pipeline_classifier"]
        )

    assert outcome.promoted == ["paralax/support", "paralax/pipeline_classifier"]
    assert outcome.errors == []
    assert outcome.blocked is False
    assert mock_mgr.promote_to_production.call_count == 2


def test_promote_prompts_unconfigured_records_pending_without_blocking() -> None:
    """Business Rule: Langfuse não configurado registra pendência manual, sem bloquear.

    Sem ambiente Langfuse não houve falha de promoção — os prompts ficam
    pendentes de promoção manual (SPEC-PROMPT-01) e o fechamento prossegue.
    """
    mock_mgr = MagicMock()
    mock_mgr.is_configured = False

    with patch(
        "harness_state.prompt_manager.LangfusePromptManager", return_value=mock_mgr
    ):
        outcome = promote_prompts_to_production(["paralax/support"])

    assert outcome.promoted == []
    assert outcome.blocked is False
    assert len(outcome.errors) == 1
    assert "não configurado" in outcome.errors[0]
    assert "paralax/support" in outcome.errors[0]
    mock_mgr.promote_to_production.assert_not_called()


def test_promote_prompts_is_atomic_on_first_error() -> None:
    """Business Rule: promoção é atômica — 1ª falha aborta sem tentar os demais."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.promote_to_production.side_effect = [
        PromptManagementError("boom"),
        True,
    ]

    with patch(
        "harness_state.prompt_manager.LangfusePromptManager", return_value=mock_mgr
    ):
        outcome = promote_prompts_to_production(
            ["paralax/broken", "paralax/ok"]
        )

    assert outcome.blocked is True
    assert len(outcome.errors) == 1
    assert "paralax/broken" in outcome.errors[0]
    assert mock_mgr.promote_to_production.call_count == 1


def test_promote_prompts_atomic_when_later_prompt_fails() -> None:
    """Business Rule: falha tardia também bloqueia, preservando as já promovidas."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.promote_to_production.side_effect = [
        True,
        PromptManagementError("boom"),
    ]

    with patch(
        "harness_state.prompt_manager.LangfusePromptManager", return_value=mock_mgr
    ):
        outcome = promote_prompts_to_production(
            ["paralax/ok", "paralax/broken", "paralax/never_tried"]
        )

    assert outcome.blocked is True
    assert outcome.promoted == ["paralax/ok"]
    assert mock_mgr.promote_to_production.call_count == 2


def test_promote_prompts_empty_list_is_noop() -> None:
    """Business Rule: lista vazia não instancia o gerenciador nem promove nada."""
    with patch(
        "harness_state.prompt_manager.LangfusePromptManager"
    ) as mock_cls:
        outcome = promote_prompts_to_production([])

    assert outcome.promoted == []
    assert outcome.errors == []
    assert outcome.blocked is False
    mock_cls.assert_not_called()
