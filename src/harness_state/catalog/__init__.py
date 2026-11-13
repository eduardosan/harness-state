"""Catálogos de definição do ecossistema Harness (Onda 1).

Este módulo contém apenas as **definições** (dataclasses, enums).
A **execução server-side** (ExecutionCatalog, RunnerCatalog) permanece no flywheel.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


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
        return {
            "name": self.name,
            "repo": self.repo,
            "role": self.role.value,
            "language": self.language.value,
            "depends_on": self.depends_on,
            "path": str(self.path) if self.path else None,
            "description": self.description,
        }


class ProjectCatalog:
    """Catálogo de definições de projetos do ecossistema.

    Carrega o `manifest.yaml` do spec-hub e expõe consultas tipadas.
    """

    def __init__(self, manifest_path: Path) -> None:
        self.manifest_path = manifest_path.resolve()
        self._projects: dict[str, ProjectDefinition] = {}
        self._load()

    def _load(self) -> None:
        import yaml

        if not self.manifest_path.is_file():
            return

        data = yaml.safe_load(self.manifest_path.read_text(encoding="utf-8")) or {}
        repos_data = data.get("repositories", [])

        for entry in repos_data:
            name = entry.get("name", "")
            repo = entry.get("repo", "")
            role_str = entry.get("role", "service")
            language_str = entry.get("language", "yaml")
            deps = entry.get("depends_on", [])
            description = entry.get("description", "")

            if not name or not repo:
                continue

            try:
                role = ProjectRole(role_str.lower())
            except ValueError:
                role = ProjectRole.SERVICE

            try:
                language = ProjectLanguage(language_str.lower())
            except ValueError:
                language = ProjectLanguage.YAML

            self._projects[name] = ProjectDefinition(
                name=name,
                repo=repo,
                role=role,
                language=language,
                depends_on=deps if isinstance(deps, list) else [],
                description=description,
            )

    def get(self, name: str) -> ProjectDefinition | None:
        return self._projects.get(name)

    def get_by_repo(self, repo: str) -> ProjectDefinition | None:
        for p in self._projects.values():
            if p.repo == repo:
                return p
        return None

    def all(self) -> list[ProjectDefinition]:
        return list(self._projects.values())

    def get_dependencies(self, name: str) -> list[ProjectDefinition]:
        """Retorna as dependências diretas de um projeto."""
        project = self.get(name)
        if not project:
            return []
        return [self._projects[dep] for dep in project.depends_on if dep in self._projects]

    def get_dependents(self, name: str) -> list[ProjectDefinition]:
        """Retorna os projetos que dependem deste."""
        dependents = []
        for p in self._projects.values():
            if name in p.depends_on:
                dependents.append(p)
        return dependents

    def topological_order(self) -> list[ProjectDefinition]:
        """Retorna os projetos em ordem topológica (dependências primeiro)."""
        visited = set()
        temp = set()
        order = []

        def visit(name: str) -> None:
            if name in temp:
                raise ValueError(f"Ciclo de dependência detectado envolvendo {name}")
            if name in visited:
                return
            temp.add(name)
            project = self._projects.get(name)
            if project:
                for dep in project.depends_on:
                    if dep in self._projects:
                        visit(dep)
            temp.remove(name)
            visited.add(name)
            if name in self._projects:
                order.append(self._projects[name])

        for name in self._projects:
            if name not in visited:
                visit(name)

        return order


# Catálogo de agentes (definições)
from ..agents import AgentConfig, KNOWN_AGENTS


class AgentCatalog:
    """Catálogo de definições de agentes de IA."""

    def __init__(self) -> None:
        self._agents: dict[str, Any] = KNOWN_AGENTS.copy()

    def get(self, agent_id: str) -> Any | None:
        return self._agents.get(agent_id.lower())

    def all(self) -> list[Any]:
        return list(self._agents.values())

    def register(self, agent_id: str, config: Any) -> None:
        self._agents[agent_id.lower()] = agent_id


# Catálogo de especificações (definições)
@dataclass(slots=True)
class SpecDefinition:
    """Definição de uma especificação no ecossistema."""

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
        self._specs: dict[str, SpecDefinition] = {}

    def add(self, spec: SpecDefinition) -> None:
        self._specs[spec.spec_id] = spec

    def get(self, spec_id: str) -> SpecDefinition | None:
        return self._specs.get(spec_id)

    def all(self) -> list[SpecDefinition]:
        return list(self._specs.values())

    def get_by_product(self, product: str) -> list[SpecDefinition]:
        return [s for s in self._specs.values() if product in s.product]

    def get_by_status(self, status: str) -> list[SpecDefinition]:
        return [s for s in self._specs.values() if s.status == status]