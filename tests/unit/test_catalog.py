"""Testes dos catálogos de definição (projetos, agentes, specs) — Onda 1."""

from pathlib import Path

import pytest

from harness_state.agents import AgentConfig
from harness_state.catalog import (
    AgentCatalog,
    ProjectCatalog,
    ProjectDefinition,
    ProjectLanguage,
    ProjectRole,
    SpecCatalog,
    SpecDefinition,
    topological_sort_projects,
)

MANIFEST_YAML = """
repositories:
  - name: spec-hub
    repo: eduardosan/harness-spec-hub
    role: hub
    language: yaml
    description: Hub de especificações
  - name: harness-state
    repo: eduardosan/harness-state
    role: platform
    language: python
    depends_on:
      - spec-hub
  - name: mystery
    repo: eduardosan/mystery
    role: invalid-role
    language: unknown-lang
  - name: orphan-entry
    depends_on: []
"""


def build_catalog(tmp_path: Path) -> ProjectCatalog:
    """Escreve o manifest de exemplo e carrega o catálogo.

    Args:
        tmp_path: Diretório temporário do teste.

    Returns:
        `ProjectCatalog` populado pelo manifest de teste.
    """
    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(MANIFEST_YAML, encoding="utf-8")
    return ProjectCatalog(manifest)


def build_project_map() -> dict[str, ProjectDefinition]:
    """Constrói um projeto isolado com dependência não catalogada.

    Returns:
        Mapa `nome -> ProjectDefinition` para o teste de arestas órfãs.
    """
    return {
        "solo": ProjectDefinition(
            name="solo",
            repo="eduardosan/solo",
            role=ProjectRole.SERVICE,
            language=ProjectLanguage.PYTHON,
            depends_on=["nao-catalogado"],
        )
    }


def test_catalog_loads_manifest_entries(tmp_path: Path) -> None:
    """Business Rule: entradas válidas do manifest viram definições tipadas.

    `name`/`repo` constroem o projeto; consulta por nome e por slug completo
    retornam a mesma definição.
    """
    catalog = build_catalog(tmp_path)
    state = catalog.get("harness-state")
    assert state is not None
    assert state.repo == "eduardosan/harness-state"
    assert state.role is ProjectRole.PLATFORM
    assert state.language is ProjectLanguage.PYTHON
    assert catalog.get_by_repo("eduardosan/harness-spec-hub") is not None


def test_catalog_skips_incomplete_entries(tmp_path: Path) -> None:
    """Business Rule: entradas sem name ou repo são descartadas do catálogo."""
    catalog = build_catalog(tmp_path)
    assert catalog.get("orphan-entry") is None
    assert len(catalog.all()) == 3


def test_catalog_falls_back_on_unknown_role_and_language(tmp_path: Path) -> None:
    """Business Rule: papel e linguagem desconhecidos degradam para defaults.

    Manifests antigos não devem quebrar o carregamento: role -> SERVICE,
    language -> YAML.
    """
    mystery = build_catalog(tmp_path).get("mystery")
    assert mystery is not None
    assert mystery.role is ProjectRole.SERVICE
    assert mystery.language is ProjectLanguage.YAML


def test_catalog_missing_manifest_is_empty(tmp_path: Path) -> None:
    """Business Rule: manifest inexistente produz catálogo vazio, sem exceção."""
    catalog = ProjectCatalog(tmp_path / "nao-existe.yaml")
    assert catalog.all() == []


def test_dependencies_and_dependents(tmp_path: Path) -> None:
    """Business Rule: o grafo de dependências é navegável nos dois sentidos."""
    catalog = build_catalog(tmp_path)
    deps = catalog.get_dependencies("harness-state")
    assert [d.name for d in deps] == ["spec-hub"]
    dependents = catalog.get_dependents("spec-hub")
    assert [d.name for d in dependents] == ["harness-state"]


def test_dependencies_of_unknown_project_is_empty(tmp_path: Path) -> None:
    """Business Rule: projeto inexistente retorna listas vazias (sem KeyError)."""
    catalog = build_catalog(tmp_path)
    assert catalog.get_dependencies("fantasma") == []
    assert catalog.get_dependencies("mystery") == []


def test_topological_order_places_dependencies_first(tmp_path: Path) -> None:
    """Business Rule: fan-out só pode escalonar um projeto após suas dependências.

    A ordem topológica do grafo carregado deve listar `spec-hub` antes de
    `harness-state`, independentemente da ordem de inserção.
    """
    order = [p.name for p in build_catalog(tmp_path).topological_order()]
    assert order.index("spec-hub") < order.index("harness-state")
    assert len(order) == 3


def test_topological_sort_raises_on_cycle(tmp_path: Path) -> None:
    """Business Rule: ciclo de dependência é erro de manifest, não ordenação parcial.

    Sem cycle detection o fan-out silenciosamente omitiria projetos do
    ciclo; o contrato exige falhar com ValueError nomeando o envolvidos.
    """
    manifest = tmp_path / "cycle.yaml"
    manifest.write_text(
        """
repositories:
  - name: a
    repo: eduardosan/a
    depends_on: [b]
  - name: b
    repo: eduardosan/b
    depends_on: [a]
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Ciclo de dependência"):
        ProjectCatalog(manifest).topological_order()


def test_topological_sort_function_ignores_edges_to_unknown_names() -> None:
    """Business Rule: arestas para projetos fora do catálogo não travam a ordenação.

    `depends_on` pode citar projetos que ainda não entraram no hub; eles são
    ignorados pelo algoritmo.
    """
    catalog_projects = build_project_map()
    ordered = topological_sort_projects(catalog_projects)
    assert [p.name for p in ordered] == ["solo"]


def test_project_definition_to_dict(tmp_path: Path) -> None:
    """Business Rule: serialização preserva enums como strings e path anulável."""
    project = build_catalog(tmp_path).get("harness-state")
    assert project is not None
    payload = project.to_dict()
    assert payload["role"] == "platform"
    assert payload["language"] == "python"
    assert payload["path"] is None
    assert payload["depends_on"] == ["spec-hub"]


def test_agent_catalog_seeded_with_known_agents() -> None:
    """Business Rule: AgentCatalog nasce com os agentes conhecidos do ecossistema.

    `KNOWN_AGENTS` de harness_state.agents é a semente — `opencode` e
    `harness-agent` devem estar disponíveis por padrão.
    """
    catalog = AgentCatalog()
    assert catalog.get("opencode") is not None
    assert catalog.get("OPENCODE") is not None
    assert catalog.get("harness-agent") is not None
    assert len(catalog.all()) >= 5


def test_agent_catalog_register_stores_config_object() -> None:
    """Business Rule: register associa o CONFIG ao id (regressão do bug que
    armazenava a string do id, fazendo get() retornar lixo).

    Um agente registrado via `register` deve ser recuperado como a mesma
    instância de `AgentConfig` fornecida.
    """
    catalog = AgentCatalog()
    custom = AgentConfig(
        id="custom-agent",
        name="Custom",
        default_model=None,
        supported_modes=["bash"],
        env_vars={},
        capabilities=["script"],
    )
    catalog.register("Custom-Agent", custom)
    assert catalog.get("custom-agent") is custom


def test_spec_catalog_indexes_by_product_and_status() -> None:
    """Business Rule: specs são filtráveis por produto e status exatos.

    O roteador de specs consulta o catálogo por essas duas chaves; `add`
    substitui spec re-publicada com o mesmo `spec_id`.
    """
    catalog = SpecCatalog()
    spec = SpecDefinition(
        spec_id="SPEC-009",
        title="CI/CD gates",
        status="IN_PROGRESS",
        product=["harness"],
        capability="quality-gates",
        scope="Sensors",
    )
    catalog.add(spec)
    catalog.add(spec)
    assert catalog.get("SPEC-009") is spec
    assert len(catalog.all()) == 1
    assert catalog.get_by_product("harness") == [spec]
    assert catalog.get_by_product("other") == []
    assert catalog.get_by_status("IN_PROGRESS") == [spec]
    assert catalog.get_by_status("DONE") == []
    assert spec.to_dict()["spec_id"] == "SPEC-009"
