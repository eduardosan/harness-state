"""Catálogos de definição do ecossistema Harness (Onda 1).

Este módulo contém as **definições** de projetos, agentes e especificações:
`ProjectCatalog` carrega e consulta o `manifest.yaml` do spec-hub, `AgentCatalog`
semeia-se com os agentes conhecidos de `harness_state.agents` e `SpecCatalog`
indexa especificações por produto/status.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from harness_state.agents import KNOWN_AGENTS


class ProjectRole(str, Enum):
    """Papel do repositório no ecossistema."""

    HUB = "hub"
    PLATFORM = "platform"
    SERVICE = "service"
    INFRA = "infra"
    SDK = "sdk"
    AI_AGENT = "ai-agent"


class ProjectLanguage(str, Enum):
    """Linguagem principal do projeto."""

    PYTHON = "python"
    YAML = "yaml"
    GO = "go"
    TYPESCRIPT = "typescript"
    RUBY = "ruby"
    DOCKERFILE = "dockerfile"


@dataclass(slots=True)
class ProjectDefinition:
    """Definição declarativa de um projeto no ecossistema Harness.

    Attributes:
        name: Nome curto do projeto (ex: 'harness-state').
        repo: Slug completo do repositório (ex: 'eduardosan/harness-state').
        role: Papel no ecossistema (hub, platform, service, infra, sdk, ai-agent).
        language: Linguagem principal.
        depends_on: Lista de nomes de projetos dos quais este depende.
        path: Caminho local opcional (resolvido em runtime).
        description: Descrição curta do projeto.
    """

    name: str
    repo: str
    role: ProjectRole
    language: ProjectLanguage
    depends_on: list[str] = field(default_factory=list)
    path: Path | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serializa a definição para dicionário (útil para YAML/JSON).

        Returns:
            Dicionário com todos os campos; enums como valor string e
            `path` como string ou None.
        """
        return {
            "name": self.name,
            "repo": self.repo,
            "role": self.role.value,
            "language": self.language.value,
            "depends_on": self.depends_on,
            "path": str(self.path) if self.path else None,
            "description": self.description,
        }


def parse_project_role(role_str: str) -> ProjectRole:
    """Converte a string de papel do manifest em `ProjectRole` com fallback.

    Args:
        role_str: Papel declarado no manifest (case-insensitive).

    Returns:
        `ProjectRole` correspondente ou `ProjectRole.SERVICE` quando desconhecido.
    """
    try:
        return ProjectRole(role_str.lower())
    except ValueError:
        return ProjectRole.SERVICE


def parse_project_language(language_str: str) -> ProjectLanguage:
    """Converte a string de linguagem do manifest em `ProjectLanguage` com fallback.

    Args:
        language_str: Linguagem declarada no manifest (case-insensitive).

    Returns:
        `ProjectLanguage` correspondente ou `ProjectLanguage.YAML` quando
        desconhecida.
    """
    try:
        return ProjectLanguage(language_str.lower())
    except ValueError:
        return ProjectLanguage.YAML


def build_project_definition(entry: dict[str, Any]) -> ProjectDefinition | None:
    """Constrói uma `ProjectDefinition` a partir de uma entrada do manifest.

    Args:
        entry: Dicionário bruto lido do `manifest.yaml` (chave `repositories`).

    Returns:
        `ProjectDefinition` quando `name` e `repo` estão presentes, None caso
        contrário (entradas incompletas são descartadas silenciosamente por
        serem dados órfãos de manifest, não erro de catálogo).
    """
    name = entry.get("name", "")
    repo = entry.get("repo", "")
    if not name or not repo:
        return None

    deps = entry.get("depends_on", [])
    return ProjectDefinition(
        name=name,
        repo=repo,
        role=parse_project_role(str(entry.get("role", "service"))),
        language=parse_project_language(str(entry.get("language", "yaml"))),
        depends_on=deps if isinstance(deps, list) else [],
        description=str(entry.get("description", "")),
    )


def topological_sort_projects(
    projects: dict[str, ProjectDefinition],
) -> list[ProjectDefinition]:
    """Ordena projetos topologicamente (dependências antes de dependentes).

    Implementa o algoritmo de Kahn sobre o grafo de `depends_on`, iterando os
    prontos na ordem de inserção do catálogo (determinístico).

    Args:
        projects: Mapa `nome -> ProjectDefinition` do catálogo.

    Returns:
        Lista de projetos em ordem topológica; arestas que apontam para nomes
        fora do mapa são ignoradas.

    Raises:
        ValueError: Se um ciclo de dependência impedir a ordenação completa.
    """
    indegree = {
        name: sum(1 for dep in project.depends_on if dep in projects)
        for name, project in projects.items()
    }
    dependents: dict[str, list[str]] = {name: [] for name in projects}
    for name, project in projects.items():
        for dep in project.depends_on:
            if dep in projects:
                dependents[dep].append(name)

    ready = [name for name, degree in indegree.items() if degree == 0]
    ordered: list[ProjectDefinition] = []
    while ready:
        current = ready.pop(0)
        ordered.append(projects[current])
        for dependent in dependents[current]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)

    if len(ordered) != len(projects):
        remaining = sorted(set(projects) - {p.name for p in ordered})
        raise ValueError(f"Ciclo de dependência detectado envolvendo {remaining[0]}")

    return ordered


class ProjectCatalog:
    """Catálogo de definições de projetos do ecossistema.

    Carrega o `manifest.yaml` do spec-hub e expõe consultas tipadas.
    """

    def __init__(self, manifest_path: Path) -> None:
        """Inicializa o catálogo lendo o manifest informado.

        Args:
            manifest_path: Caminho do `manifest.yaml` do spec-hub.
        """
        self.manifest_path = manifest_path.resolve()
        self._projects: dict[str, ProjectDefinition] = {}
        self._load()

    def _load(self) -> None:
        """Lê o manifest (se existir) e popula as definições de projetos."""
        import yaml

        if not self.manifest_path.is_file():
            return

        data = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        repos_data = data.get("repositories", [])
        if not isinstance(repos_data, list):
            return

        for entry in repos_data:
            if not isinstance(entry, dict):
                continue
            project = build_project_definition(entry)
            if project is not None:
                self._projects[project.name] = project

    def get(self, name: str) -> ProjectDefinition | None:
        """Retorna o projeto pelo nome curto.

        Args:
            name: Nome curto do projeto.

        Returns:
            `ProjectDefinition` ou None quando ausente.
        """
        return self._projects.get(name)

    def get_by_repo(self, repo: str) -> ProjectDefinition | None:
        """Retorna o projeto pelo slug completo do repositório.

        Args:
            repo: Slug completo (ex: 'eduardosan/harness-state').

        Returns:
            `ProjectDefinition` ou None quando ausente.
        """
        for p in self._projects.values():
            if p.repo == repo:
                return p
        return None

    def all(self) -> list[ProjectDefinition]:
        """Retorna todas as definições na ordem de inserção.

        Returns:
            Lista de `ProjectDefinition`.
        """
        return list(self._projects.values())

    def get_dependencies(self, name: str) -> list[ProjectDefinition]:
        """Retorna as dependências diretas de um projeto.

        Args:
            name: Nome curto do projeto.

        Returns:
            Lista de `ProjectDefinition` apontadas por `depends_on` (nomes
            fora do catálogo são ignorados); vazia quando o projeto não existe.
        """
        project = self.get(name)
        if not project:
            return []
        return [
            self._projects[dep] for dep in project.depends_on if dep in self._projects
        ]

    def get_dependents(self, name: str) -> list[ProjectDefinition]:
        """Retorna os projetos que dependem diretamente deste.

        Args:
            name: Nome curto do projeto.

        Returns:
            Lista de `ProjectDefinition` cujo `depends_on` contém `name`.
        """
        dependents = []
        for p in self._projects.values():
            if name in p.depends_on:
                dependents.append(p)
        return dependents

    def topological_order(self) -> list[ProjectDefinition]:
        """Retorna os projetos em ordem topológica (dependências primeiro).

        Returns:
            Lista de `ProjectDefinition` ordenada por Kahn.

        Raises:
            ValueError: Se houver ciclo de dependência no grafo.
        """
        return topological_sort_projects(self._projects)


class AgentCatalog:
    """Catálogo de definições de agentes de IA.

    Semeia-se com `KNOWN_AGENTS` de `harness_state.agents` e permite registrar
    configurações adicionais em runtime.
    """

    def __init__(self) -> None:
        """Inicializa o catálogo com cópia dos agentes conhecidos."""
        self._agents: dict[str, Any] = KNOWN_AGENTS.copy()

    def get(self, agent_id: str) -> Any | None:
        """Retorna a configuração do agente (case-insensitive).

        Args:
            agent_id: Identificador do agente.

        Returns:
            `AgentConfig` correspondente ou None quando ausente.
        """
        return self._agents.get(agent_id.lower())

    def all(self) -> list[Any]:
        """Retorna todas as configurações registradas.

        Returns:
            Lista de `AgentConfig`.
        """
        return list(self._agents.values())

    def register(self, agent_id: str, config: Any) -> None:
        """Registra (ou substitui) a configuração de um agente.

        Args:
            agent_id: Identificador do agente (normalizado para minúsculas).
            config: Instância de `AgentConfig` associada ao identificador.
        """
        self._agents[agent_id.lower()] = config


@dataclass(slots=True)
class SpecDefinition:
    """Definição de uma especificação no ecossistema.

    Attributes:
        spec_id: Identificador canônico (ex: 'SPEC-009').
        title: Título legível da especificação.
        status: Status de ciclo de vida (ex: 'IN_PROGRESS').
        product: Produtos impactados pela spec.
        capability: Capacidade de negócio endereçada.
        scope: Escopo resumido.
        bounded_context: Contexto delimitado opcional.
        origin_module: Módulo de origem da spec.
        target_repositories: Lista de dicionários com repositórios-alvo.
    """

    spec_id: str
    title: str
    status: str
    product: list[str]
    capability: str
    scope: str
    bounded_context: str = ""
    origin_module: str = ""
    target_repositories: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serializa a definição de spec para dicionário.

        Returns:
            Dicionário com todos os campos da spec.
        """
        return {
            "spec_id": self.spec_id,
            "title": self.title,
            "status": self.status,
            "product": self.product,
            "capability": self.capability,
            "scope": self.scope,
            "bounded_context": self.bounded_context,
            "origin_module": self.origin_module,
            "target_repositories": self.target_repositories,
        }


class SpecCatalog:
    """Catálogo de definições de especificações."""

    def __init__(self) -> None:
        """Inicializa o catálogo de specs vazio."""
        self._specs: dict[str, SpecDefinition] = {}

    def add(self, spec: SpecDefinition) -> None:
        """Indexa uma especificação pelo `spec_id`.

        Args:
            spec: Definição a registrar (substitui a de mesmo id).
        """
        self._specs[spec.spec_id] = spec

    def get(self, spec_id: str) -> SpecDefinition | None:
        """Retorna a spec pelo identificador.

        Args:
            spec_id: Identificador canônico (ex: 'SPEC-009').

        Returns:
            `SpecDefinition` ou None quando ausente.
        """
        return self._specs.get(spec_id)

    def all(self) -> list[SpecDefinition]:
        """Retorna todas as specs registradas.

        Returns:
            Lista de `SpecDefinition` na ordem de inserção.
        """
        return list(self._specs.values())

    def get_by_product(self, product: str) -> list[SpecDefinition]:
        """Filtra specs que impactam um produto.

        Args:
            product: Nome do produto.

        Returns:
            Specs cuja lista `product` contém o nome.
        """
        return [s for s in self._specs.values() if product in s.product]

    def get_by_status(self, status: str) -> list[SpecDefinition]:
        """Filtra specs por status de ciclo de vida.

        Args:
            status: Status exato (ex: 'IN_PROGRESS').

        Returns:
            Specs cujo `status` coincide exatamente.
        """
        return [s for s in self._specs.values() if s.status == status]
