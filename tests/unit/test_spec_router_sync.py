"""Regras de sincronia entre o roteador de specs do pacote e o artefato de pipeline."""

from pathlib import Path

import harness_state.spec_router as package_router

CATALOG_ARTIFACT = (
    Path(package_router.__file__).resolve().parent
    / "catalog"
    / "pipeline"
    / "sensors"
    / "spec_router.py"
)


def test_especificacoes_de_roteamento_do_pacote_igualam_o_artefato_instalavel() -> None:
    """Business Rule: o roteador embutido no pacote nunca diverge do artefato
    instalável em `.harness/sensors/spec_router.py`.

    Os sensores rodam em dois contextos (biblioteca do núcleo e pipeline do
    spoke); divergência silenciosa entre as cópias deixaria o Roteador
    Estático de Especificações com semânticas diferentes no gate e no alvo.
    """
    catalog_source = CATALOG_ARTIFACT.read_text(encoding="utf-8")

    assert catalog_source == Path(package_router.__file__).read_text(encoding="utf-8")
