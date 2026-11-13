"""Testes do bloco canônico de diretrizes Superpowers (SPEC-PROMPT-01 / SDD)."""

from pathlib import Path

from harness_state import installer
from harness_state.guidelines import SUPERPOWERS_GUIDELINES_BLOCK
from harness_state.installer import install_agent_guidelines

SECTION_MARKERS = (
    "1. **Invocação Obrigatória de Skills:**",
    "2. **Ciclo de Desenvolvimento Federado:**",
    "3. **Análise de Bugs (RCA Mandatória):**",
    "4. **Local da Spec (SSOT):**",
    "5. **Infraestrutura Gerenciada (Acesso Remoto Restrito):**",
)


def test_block_delimitado_por_tags_de_managed_block() -> None:
    """Business Rule: o bloco é sempre envolvido pelas marcadores START/END.

    As tags `SUPERPOWERS-HARNESS:START/END` permitem ao instalador
    substituir a seção de forma idempotente em AGENTS.md e CLAUDE.md.
    """
    assert SUPERPOWERS_GUIDELINES_BLOCK.startswith("<!-- SUPERPOWERS-HARNESS:START -->")
    assert SUPERPOWERS_GUIDELINES_BLOCK.endswith("<!-- SUPERPOWERS-HARNESS:END -->")


def test_cada_secao_canonica_aparece_exatamente_uma_vez() -> None:
    """Business Rule: as 5 seções normativas existem uma única vez no bloco.

    Regressão contra a patologia de blocos duplicados anexados por
    migrações anteriores (itens 3/4 repetidos 4x no texto corrompido).
    """
    for marker in SECTION_MARKERS:
        assert SUPERPOWERS_GUIDELINES_BLOCK.count(marker) == 1, marker


def test_block_proibe_mascaramento_de_erros() -> None:
    """Business Rule: as diretrizes vedam try/except e || true como mascaramento.

    A norma de RCA obrigatória precisa estar presente no texto injetado —
    é a regra que governa o comportamento dos agentes no repositório-alvo.
    """
    assert "Proibição de Mascaramento" in SUPERPOWERS_GUIDELINES_BLOCK
    assert "except: pass" in SUPERPOWERS_GUIDELINES_BLOCK
    assert "|| true" in SUPERPOWERS_GUIDELINES_BLOCK


def test_block_exige_rca_com_ishikawa_e_5_porques() -> None:
    """Business Rule: diagnóstico de falha exige Ishikawa e 5 Porquês antes do código."""
    assert "Diagrama de Ishikawa" in SUPERPOWERS_GUIDELINES_BLOCK
    assert "5 Porquês" in SUPERPOWERS_GUIDELINES_BLOCK


def test_block_redirecta_spec_para_ssot_federado() -> None:
    """Business Rule: design docs vão no hub federado, não em docs/superpowers.

    Onde o fluxo upstream sugeriria `docs/superpowers/specs/`, a diretriz
    exige `<project>-spec-hub/specs/SPEC-XXX.md` com numeração
    `SPEC-XXX-<slug>.md`.
    """
    assert "docs/superpowers/specs/" in SUPERPOWERS_GUIDELINES_BLOCK
    assert "<project>-spec-hub/specs/SPEC-XXX.md" in SUPERPOWERS_GUIDELINES_BLOCK
    assert "`SPEC-XXX-<slug>.md`" in SUPERPOWERS_GUIDELINES_BLOCK


def test_installer_reusa_a_mesma_constante_canonica() -> None:
    """Business Rule: installer e guidelines compartilham UMA única fonte da verdade.

    Duplicar o texto do bloco em dois módulos cria drift silencioso entre o
    que é instalável e o que é canônico; o re-export preserva a identidade.
    """
    assert installer.SUPERPOWERS_GUIDELINES_BLOCK is SUPERPOWERS_GUIDELINES_BLOCK


def test_install_agent_guidelines_cria_arquivos_idempotentemente(
    tmp_path: Path,
) -> None:
    """Business Rule: injeção em AGENTS.md/CLAUDE.md não duplica o bloco.

    A segunda execução não deve alterar os arquivos (upsert entre as tags
    START/END), preservando conteúdo pré-existente fora da seção gerenciada.
    """
    (tmp_path / "AGENTS.md").write_text("# Guia\n\ncorpo existente\n", encoding="utf-8")

    updated = install_agent_guidelines(tmp_path)
    assert "AGENTS.md" in updated
    assert "CLAUDE.md" in updated

    agents_text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert agents_text.startswith("# Guia")
    assert "corpo existente" in agents_text
    assert agents_text.count("<!-- SUPERPOWERS-HARNESS:START -->") == 1

    second = install_agent_guidelines(tmp_path)
    assert second == []
    again = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert again == agents_text
