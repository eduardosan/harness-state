"""Promoção atômica de prompts Langfuse (draft → production) — SPEC-PROMPT-01.

Helper compartilhado pelos fluxos de fechamento de spec (Gate 5) e de bug
(Passo 15), garantindo simetria e atomicidade: ou todos os prompts são
promovidos, ou o fluxo de fechamento NÃO prossegue (`blocked=True`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from rich.console import Console

LOGGER = logging.getLogger(__name__)

console = Console()


@dataclass
class PromptPromotionOutcome:
    """Resultado da promoção atômica de prompts no Langfuse.

    Attributes:
        promoted: Nomes efetivamente promovidos antes de eventual bloqueio.
        errors: Mensagens de falha ou de pendência (Langfuse não configurado).
        blocked: Se True, o fluxo de fechamento deve ser abortado — a
            progressão é atômica (falha em um prompt impede a continuação).
    """

    promoted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    blocked: bool = False


def promote_prompts_to_production(
    prompt_names: list[str],
) -> PromptPromotionOutcome:
    """Promove prompts do Langfuse para a label 'production' de forma atômica.

    Deve ser executado exclusivamente após a aprovação formal do fechamento
    (Gate 5 da spec / Passo 15 do bug). A progressão é atômica: a primeira
    falha de promoção interrompe o processo (`blocked=True`) e o chamador
    deve abortar o fechamento. Prompts já promovidos antes da falha permanecem
    válidos (a label 'production' já foi aplicada no Langfuse).

    Langfuse não configurado NÃO bloqueia: os prompts ficam pendentes de
    promoção manual e a pendência é registrada em `errors`.

    Args:
        prompt_names: Nomes dos prompts a promover.

    Returns:
        `PromptPromotionOutcome` com promovidos, erros e o flag de bloqueio.
    """
    if not prompt_names:
        return PromptPromotionOutcome()

    from harness_state.prompt_manager import LangfusePromptManager

    prompt_mgr = LangfusePromptManager()
    if not prompt_mgr.is_configured:
        pending = ", ".join(prompt_names)
        console.print(
            "  • [bold yellow]Aviso:[/bold yellow] Langfuse não configurado "
            "no ambiente. Prompts pendentes de promoção manual: "
            f"{pending}"
        )
        return PromptPromotionOutcome(
            errors=[
                (
                    "Langfuse não configurado; prompts pendentes de promoção "
                    f"manual: {pending}"
                )
            ],
        )

    promoted: list[str] = []
    for prompt_name in prompt_names:
        try:
            prompt_mgr.promote_to_production(prompt_name)
        except Exception as p_err:
            LOGGER.exception("Promoção atômica de prompt interrompida")
            console.print(
                f"  • [bold red]Erro ao promover prompt '{prompt_name}': "
                f"{p_err}[/bold red]"
            )
            console.print(
                "  • [bold red]Progressão atômica interrompida:[/bold red] "
                "resolva a falha de promoção e execute o fechamento novamente."
            )
            return PromptPromotionOutcome(
                promoted=promoted,
                errors=[
                    f"Erro ao promover prompt '{prompt_name}' no Langfuse: {p_err}"
                ],
                blocked=True,
            )
        promoted.append(prompt_name)
        console.print(
            f"  • [bold green]✓[/bold green] Prompt promovido para "
            f"'production' no Langfuse: [bold cyan]{prompt_name}[/bold cyan]"
        )
    return PromptPromotionOutcome(promoted=promoted)
