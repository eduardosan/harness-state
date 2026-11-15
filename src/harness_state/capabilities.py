"""Extrator e Inspetor de Capacidades de Negócio para Spec-Driven Development (SDD)."""

import argparse
import ast
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class RepoMetadata:
    """Metadados de um repositório configurado no manifest.yaml.

    Attributes:
        name: Nome do serviço ou componente.
        repo: Identificador completo do repositório GitHub.
        role: Papel arquitetural (ex: shared-library, sdk, ai-agent).
        language: Linguagem do componente (python, ruby, go).
        depends_on: Lista de dependências declaradas.
    """

    name: str
    repo: str
    role: str
    language: str
    depends_on: list[str] = field(default_factory=list)


@dataclass
class ManifestConfig:
    """Configuração geral do ecossistema carregada a partir do manifest.yaml.

    Attributes:
        version: Versão do esquema do manifesto.
        project: Nome do projeto corporativo.
        repositories: Lista de repositórios registrados.
    """

    version: str
    project: str
    repositories: list[RepoMetadata]


@dataclass
class CapabilityModel:
    """Representação técnica estruturada das capacidades de um repositório.

    Attributes:
        name: Nome do componente.
        role: Papel no ecossistema.
        language: Linguagem de desenvolvimento.
        description: Descrição sucinta do serviço.
        classes: Classes públicas e métodos extraídos da AST.
        functions: Funções públicas de módulo extraídas da AST.
        routes: Rotas HTTP identificadas.
    """

    name: str
    role: str
    language: str
    description: str = ""
    classes: list[dict[str, Any]] = field(default_factory=list)
    functions: list[dict[str, Any]] = field(default_factory=list)
    routes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProductModel:
    """Modelo de domínio para um Produto ou Domínio de Cliente no ecossistema.

    Attributes:
        version: Versão do esquema do produto.
        product_id: Identificador único do produto.
        name: Nome amigável do produto.
        client_segment: Segmento de negócio ou público-alvo atendido.
        description: Proposta de valor e finalidade do produto.
        repositories: Lista de repositórios que compõem a solução deste produto.
        capabilities: Lista de Business Capabilities consumidas ou orquestradas.
    """

    version: str = "1.0"
    product_id: str = ""
    name: str = ""
    client_segment: str = ""
    description: str = ""
    repositories: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)


@dataclass
class BusinessCapability:
    """Modelo de domínio para uma Business Capability no padrão DDD.

    Attributes:
        version: Versão do esquema da capability.
        capability_id: Identificador único e perene da capacidade de negócio.
        name: Nome descritivo da capacidade.
        scope: Escopo da capacidade (platform vs product-specific).
        supported_products: Lista de produtos atendidos por esta capacidade.
        subdomain_type: Classificação de subdomínio DDD (core, supporting, generic).
        description: Declaração do valor de negócio da capacidade.
        ubiquitous_language: Glossário com termos e definições do domínio.
        context_map: Mapeamento de papéis e serviços do domínio.
        specs: Lista de especificações incrementais vinculadas a esta capacidade.
        runtime_contracts: Contratos técnicos reais de classes, métodos e endpoints.
    """

    version: str = "1.0"
    capability_id: str = ""
    name: str = ""
    scope: str = "platform"
    supported_products: list[str] = field(default_factory=list)
    subdomain_type: str = "supporting"
    description: str = ""
    ubiquitous_language: dict[str, str] = field(default_factory=dict)
    context_map: dict[str, Any] = field(default_factory=dict)
    specs: list[dict[str, Any]] = field(default_factory=list)
    runtime_contracts: dict[str, Any] = field(default_factory=dict)


def load_manifest(manifest_path: Path) -> ManifestConfig:
    """Carrega o manifest.yaml do spec-hub e converte para objetos tipados.

    Args:
        manifest_path: Caminho para o arquivo manifest.yaml.

    Returns:
        Instância de ManifestConfig com a lista de repositórios.

    Raises:
        FileNotFoundError: Se o manifesto não existir.
    """
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manifesto não encontrado: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as file:
        data: dict[str, Any] = yaml.safe_load(file) or {}

    repos = []
    for entry in data.get("repositories", []):
        repos.append(
            RepoMetadata(
                name=entry.get("name", ""),
                repo=entry.get("repo", ""),
                role=entry.get("role", "unknown"),
                language=entry.get("language", "python"),
                depends_on=entry.get("depends_on", []),
            )
        )

    return ManifestConfig(
        version=str(data.get("version", "1.0")),
        project=str(data.get("project", "default")),
        repositories=repos,
    )


def load_product(path: Path) -> ProductModel:
    """Carrega um arquivo de produto YAML do spec-hub.

    Args:
        path: Caminho para o arquivo do produto.

    Returns:
        Instância tipada de ProductModel.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de produto não encontrado: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    return ProductModel(
        version=str(data.get("version", "1.0")),
        product_id=str(data.get("product_id", "")),
        name=str(data.get("name", "")),
        client_segment=str(data.get("client_segment", "")),
        description=str(data.get("description", "")).strip(),
        repositories=data.get("repositories", []),
        capabilities=data.get("capabilities", []),
    )


def load_all_products(spec_hub_dir: Path) -> list[tuple[ProductModel, Path]]:
    """Carrega todos os produtos localizados em spec_hub_dir/products/.

    Args:
        spec_hub_dir: Diretório raiz do spec-hub.

    Returns:
        Lista de tuplas (ProductModel, Path).
    """
    products_root = spec_hub_dir / "products"
    if not products_root.is_dir():
        return []

    result = []
    for prod_path in sorted(products_root.glob("*.yaml")):
        prod = load_product(prod_path)
        result.append((prod, prod_path))

    return result


def load_business_capability(path: Path) -> BusinessCapability:
    """Carrega um arquivo capability.yaml orientado a DDD.

    Args:
        path: Caminho absoluto ou relativo para capability.yaml.

    Returns:
        Instância tipada de BusinessCapability.

    Raises:
        FileNotFoundError: Se o arquivo não existir.
    """
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo de capacidade não encontrado: {path}")

    with open(path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    return BusinessCapability(
        version=str(data.get("version", "1.0")),
        capability_id=str(data.get("capability_id", "")),
        name=str(data.get("name", "")),
        scope=str(data.get("scope", "platform")),
        supported_products=data.get("supported_products", []),
        subdomain_type=str(data.get("subdomain_type", "supporting")),
        description=str(data.get("description", "")),
        ubiquitous_language=data.get("ubiquitous_language", {}),
        context_map=data.get("context_map", {}),
        specs=data.get("specs", []),
        runtime_contracts=data.get("runtime_contracts", {}),
    )


def save_business_capability(capability: BusinessCapability, path: Path) -> None:
    """Salva uma BusinessCapability no disco no formato YAML padronizado.

    Args:
        capability: Objeto BusinessCapability a ser persistido.
        path: Caminho de destino para salvar o arquivo capability.yaml.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": capability.version,
        "capability_id": capability.capability_id,
        "name": capability.name,
        "subdomain_type": capability.subdomain_type,
        "scope": capability.scope,
        "supported_products": capability.supported_products,
        "description": capability.description.strip(),
        "ubiquitous_language": capability.ubiquitous_language,
        "context_map": capability.context_map,
        "specs": capability.specs,
        "runtime_contracts": capability.runtime_contracts,
    }
    with open(path, "w", encoding="utf-8") as file:
        yaml.dump(payload, file, sort_keys=False, allow_unicode=True)


def load_all_capabilities(spec_hub_dir: Path) -> list[tuple[BusinessCapability, Path]]:
    """Carrega todas as Business Capabilities localizadas em spec_hub_dir/capabilities.

    Args:
        spec_hub_dir: Diretório raiz do repositório spec-hub.

    Returns:
        Lista de tuplas contendo (BusinessCapability, Path).
    """
    capabilities_root = spec_hub_dir / "capabilities"
    if not capabilities_root.is_dir():
        return []

    result = []
    for cap_path in sorted(capabilities_root.glob("*/capability.yaml")):
        cap = load_business_capability(cap_path)
        result.append((cap, cap_path))

    return result


class CapabilityExtractor:
    """Serviço legado de extração de capacidades técnicas a partir de código."""

    def inspect_python_repo(
        self, repo_name: str, role: str, repo_dir: Path
    ) -> CapabilityModel:
        """Inspeciona módulos Python de um repositório para extrair AST.

        Args:
            repo_name: Nome do componente.
            role: Papel arquitetural do componente.
            repo_dir: Diretório raiz do repositório clonado.

        Returns:
            CapabilityModel preenchido com classes, métodos e funções.
        """
        extracted_classes = []
        extracted_functions = []

        python_files = list(repo_dir.rglob("*.py"))
        for py_path in python_files:
            if ".venv" in py_path.parts or "tests" in py_path.parts:
                continue

            parsed_classes, parsed_functions = self.parse_python_file(py_path)
            extracted_classes.extend(parsed_classes)
            extracted_functions.extend(parsed_functions)

        return CapabilityModel(
            name=repo_name,
            role=role,
            language="python",
            description=f"Capacidades computacionais de {repo_name}",
            classes=extracted_classes,
            functions=extracted_functions,
            routes=[],
        )

    def _extract_public_methods(self, class_node: ast.ClassDef) -> list[dict[str, str]]:
        """Extrai métodos públicos declarados no corpo de uma classe AST.

        Args:
            class_node: Nó de definição de classe da AST.

        Returns:
            Lista de dicionários contendo `name` e `docstring`.
        """
        methods: list[dict[str, str]] = []
        for item in class_node.body:
            if isinstance(
                item, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and not item.name.startswith("_"):
                methods.append(
                    {
                        "name": item.name,
                        "docstring": ast.get_docstring(item) or "",
                    }
                )
        return methods

    def parse_python_file(
        self, file_path: Path
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Realiza o parsing da AST de um único arquivo Python.

        Args:
            file_path: Caminho do arquivo a ser parseado.

        Returns:
            Tupla contendo lista de classes e lista de funções encontradas.
        """
        classes: list[dict[str, Any]] = []
        functions: list[dict[str, Any]] = []

        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content)

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
                classes.append(
                    {
                        "name": node.name,
                        "docstring": ast.get_docstring(node) or "",
                        "methods": self._extract_public_methods(node),
                    }
                )
            elif isinstance(
                node, (ast.FunctionDef, ast.AsyncFunctionDef)
            ) and not node.name.startswith("_"):
                functions.append(
                    {
                        "name": node.name,
                        "docstring": ast.get_docstring(node) or "",
                    }
                )

        return classes, functions

    def export_capability_yaml(
        self, capability: CapabilityModel, out_dir: Path
    ) -> Path:
        """Exporta o modelo de capacidade para arquivo YAML no formato canônico.

        Args:
            capability: Objeto CapabilityModel a ser exportado.
            out_dir: Diretório de destino onde salvar o arquivo.

        Returns:
            Caminho do arquivo YAML gerado.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        target_path = out_dir / f"{capability.name}.yaml"

        data = asdict(capability)
        with open(target_path, "w", encoding="utf-8") as file:
            yaml.dump(data, file, sort_keys=False, allow_unicode=True)

        return target_path


class DomainInspector:
    """Auditor de Domínio e Sincronizador de Business Capabilities no padrão DDD."""

    def __init__(self) -> None:
        """Inicializa o DomainInspector com um extrator de AST acoplado."""
        self.extractor = CapabilityExtractor()

    def resolve_repo_path(self, repo_name: str, workspace_root: Path) -> Path | None:
        """Resolve o caminho de um repositório no workspace.

        Args:
            repo_name: Nome do repositório ou componente.
            workspace_root: Diretório raiz contendo os repositórios irmãos.

        Returns:
            Path para o repositório se existir, ou None.
        """
        candidate = workspace_root / repo_name
        if candidate.is_dir():
            return candidate

        parent_candidate = workspace_root.parent / repo_name
        if parent_candidate.is_dir():
            return parent_candidate

        return None

    def _class_matches_term(self, cls_info: dict[str, Any], term_lower: str) -> bool:
        """Verifica se uma classe ou seus métodos mencionam um termo do domínio.

        Args:
            cls_info: Dicionário com metadados da classe extraída.
            term_lower: Termo da linguagem ubíqua em minúsculas.

        Returns:
            True se o termo estiver presente no nome ou docstring da classe/métodos.
        """
        if term_lower in cls_info["name"].lower():
            return True
        if term_lower in cls_info.get("docstring", "").lower():
            return True
        for method in cls_info.get("methods", []):
            if (
                term_lower in method["name"].lower()
                or term_lower in method.get("docstring", "").lower()
            ):
                return True
        return False

    def audit_capability(
        self, capability: BusinessCapability, workspace_root: Path
    ) -> dict[str, Any]:
        """Audita conceitos de negócio e contratos de uma Business Capability.

        Args:
            capability: Objeto da capacidade a auditar.
            workspace_root: Diretório raiz para localização dos repositórios.

        Returns:
            Dicionário com termos cobertos, termos ausentes e contratos extraídos.
        """
        terms = set(capability.ubiquitous_language.keys())
        terms_covered = set()
        all_classes: list[dict[str, Any]] = []
        all_functions: list[dict[str, Any]] = []

        context_map = capability.context_map
        target_repos = [
            context_map[key]
            for key in ("sdk_layer", "upstream_authoritative")
            if context_map.get(key)
        ]

        for repo_name in target_repos:
            repo_path = self.resolve_repo_path(repo_name, workspace_root)
            if not repo_path:
                continue

            cap_model = self.extractor.inspect_python_repo(
                repo_name=repo_name,
                role="service",
                repo_dir=repo_path,
            )
            all_classes.extend(cap_model.classes)
            all_functions.extend(cap_model.functions)

        for term in terms:
            term_lower = term.lower()
            if any(self._class_matches_term(cls, term_lower) for cls in all_classes):
                terms_covered.add(term)

        return {
            "capability_id": capability.capability_id,
            "terms_covered": sorted(terms_covered),
            "terms_missing": sorted(terms - terms_covered),
            "classes": all_classes,
            "functions": all_functions,
        }

    def sync_capability(
        self, capability: BusinessCapability, workspace_root: Path, target_path: Path
    ) -> BusinessCapability:
        """Executa auditoria e atualiza os runtime_contracts no arquivo capability.yaml.

        Args:
            capability: BusinessCapability a sincronizar.
            workspace_root: Diretório de repositórios para inspeção.
            target_path: Caminho de gravação do capability.yaml.

        Returns:
            BusinessCapability atualizada.
        """
        audit_result = self.audit_capability(capability, workspace_root)

        contracts: dict[str, Any] = {}
        if audit_result["classes"]:
            formatted_classes = []
            for cls_info in audit_result["classes"]:
                method_names = [m["name"] for m in cls_info.get("methods", [])]
                formatted_classes.append(
                    {
                        "name": cls_info["name"],
                        "methods": method_names,
                    }
                )
            contracts["classes"] = formatted_classes

        capability.runtime_contracts = contracts
        save_business_capability(capability, target_path)
        return capability

    def sync_all(
        self, spec_hub_dir: Path, workspace_root: Path | None = None
    ) -> list[Path]:
        """Sincroniza todas as capacidades encontradas no spec-hub.

        Args:
            spec_hub_dir: Raiz do spec-hub.
            workspace_root: Diretório de repositórios (padrão: pai do spec_hub_dir).

        Returns:
            Lista de caminhos de arquivos capability.yaml atualizados.
        """
        if workspace_root is None:
            workspace_root = spec_hub_dir.resolve().parent

        capabilities_list = load_all_capabilities(spec_hub_dir)
        updated_paths = []
        for cap, cap_path in capabilities_list:
            self.sync_capability(cap, workspace_root, cap_path)
            updated_paths.append(cap_path)

        return updated_paths

    def update_spec_status(
        self, spec_hub_dir: Path, spec_id: str, new_status: str
    ) -> bool:
        """Localiza a spec em todas as capabilities do spec-hub e atualiza seu status.

        Args:
            spec_hub_dir: Raiz do repositório spec-hub.
            spec_id: Identificador da spec (ex: SPEC-002).
            new_status: Novo status (ex: MERGED, IN_PROGRESS, REJECTED).

        Returns:
            True se a spec foi encontrada e atualizada, False caso contrário.
        """
        capabilities_list = load_all_capabilities(spec_hub_dir)
        found = False

        for cap, cap_path in capabilities_list:
            modified = False
            for spec_item in cap.specs:
                if spec_item.get("id") == spec_id:
                    spec_item["status"] = new_status
                    modified = True
                    found = True

            if modified:
                save_business_capability(cap, cap_path)

        return found

    def map_all_repositories(
        self, spec_hub_dir: Path, workspace_root: Path | None = None
    ) -> dict[str, Any]:
        """Mapeia repositórios do manifesto para as Business Capabilities.

        Args:
            spec_hub_dir: Raiz do spec-hub (manifest.yaml e capabilities/).
            workspace_root: Diretório raiz opcional com repositórios clonados.

        Returns:
            Dicionário com o inventário completo e contratos atualizados.
        """
        if workspace_root is None:
            workspace_root = spec_hub_dir.resolve().parent

        manifest_path = spec_hub_dir / "manifest.yaml"
        manifest_cfg = load_manifest(manifest_path)

        capabilities_list = load_all_capabilities(spec_hub_dir)
        repo_to_caps: dict[str, list[tuple[BusinessCapability, Path]]] = {}
        for cap, cap_path in capabilities_list:
            ctx = cap.context_map
            repos_in_cap = []
            if ctx.get("upstream_authoritative"):
                repos_in_cap.append(ctx["upstream_authoritative"])
            if ctx.get("sdk_layer"):
                repos_in_cap.append(ctx["sdk_layer"])
            repos_in_cap.extend(ctx.get("downstream_consumers", []))
            for r_name in repos_in_cap:
                repo_to_caps.setdefault(r_name, []).append((cap, cap_path))

        inspected_repositories: list[str] = []
        unmapped_repositories: list[str] = []

        for repo_meta in manifest_cfg.repositories:
            r_name = repo_meta.name
            inspected_repositories.append(r_name)
            if r_name not in repo_to_caps:
                unmapped_repositories.append(r_name)

        products_list = load_all_products(spec_hub_dir)
        products_info = []
        for prod, _ in products_list:
            products_info.append(
                {
                    "product_id": prod.product_id,
                    "name": prod.name,
                    "client_segment": prod.client_segment,
                    "description": prod.description,
                    "repositories": prod.repositories,
                    "capabilities": prod.capabilities,
                }
            )

        capabilities_mapped_info = []
        for cap, cap_path in capabilities_list:
            synced_cap = self.sync_capability(cap, workspace_root, cap_path)
            audit_info = self.audit_capability(cap, workspace_root)
            capabilities_mapped_info.append(
                {
                    "capability_id": cap.capability_id,
                    "name": cap.name,
                    "scope": cap.scope,
                    "supported_products": cap.supported_products,
                    "subdomain_type": cap.subdomain_type,
                    "terms_covered": audit_info["terms_covered"],
                    "terms_missing": audit_info["terms_missing"],
                    "classes": synced_cap.runtime_contracts.get("classes", []),
                }
            )

        return {
            "project_name": manifest_cfg.project,
            "manifest_version": manifest_cfg.version,
            "total_repositories": len(manifest_cfg.repositories),
            "inspected_repositories": inspected_repositories,
            "unmapped_repositories": unmapped_repositories,
            "products": products_info,
            "capabilities_mapped": capabilities_mapped_info,
        }


def print_map_all_report(report: dict[str, Any]) -> None:
    """Imprime o relatório formatado do comando `map-all`.

    Args:
        report: Dicionário consolidado retornado por `map_all_repositories`.
    """
    print("=" * 80)
    print(f"📊 INVENTÁRIO DDD DO ECOSSISTEMA: {report['project_name']}")
    print("=" * 80)
    print(f"Total de Repositórios no Manifesto: {report['total_repositories']}")
    print(f"Repositórios Inspecionados: {len(report['inspected_repositories'])}\n")

    if report.get("products"):
        print("📦 PRODUTOS & CORE DOMAINS DE CLIENTES:")
        for prod in report["products"]:
            p_repos = ", ".join(prod["repositories"]) or "nenhum"
            p_caps = ", ".join(prod["capabilities"]) or "nenhuma"
            print(f"  • {prod['product_id']} ({prod['name']})")
            print(f"    - Segmento: {prod['client_segment']}")
            print(f"    - Repositórios: {p_repos}")
            print(f"    - Capacidades Consumidas: {p_caps}")
        print()

    print("🌐 BUSINESS CAPABILITIES (BOUNDED CONTEXTS):")
    for cap_info in report["capabilities_mapped"]:
        covered_str = ", ".join(cap_info["terms_covered"]) or "nenhum"
        missing_str = ", ".join(cap_info["terms_missing"]) or "nenhum"
        scope_str = cap_info.get("scope", "platform")
        supported_str = ", ".join(cap_info.get("supported_products", [])) or "todos"
        cap_id = cap_info["capability_id"]
        cap_name = cap_info["name"]
        cap_sub = cap_info["subdomain_type"]
        print(f"  • {cap_id} ({cap_name}) [{cap_sub}]")
        print(f"    - Escopo: {scope_str} | Produtos Atendidos: {supported_str}")
        print(f"    - Classes Catalogadas: {len(cap_info['classes'])}")
        print(f"    - Termos Cobertos: {covered_str}")
        print(f"    - Termos Ausentes: {missing_str}")

    if report["unmapped_repositories"]:
        print("\n⚠️ REPOSITÓRIOS DO MANIFESTO NÃO MAPEADOS EM NENHUM CONTEXT MAP:")
        for unmapped in report["unmapped_repositories"]:
            print(f"  • {unmapped}")
    print("=" * 80)


def build_capabilities_cli_parser() -> argparse.ArgumentParser:
    """Constrói o parser de linha de comando para o ingestor de capacidades.

    Returns:
        Instância configurada de `argparse.ArgumentParser`.
    """
    parser = argparse.ArgumentParser(
        description="Ingestor e Inspetor de Business Capabilities (SDD / DDD)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser(
        "sync", help="Sincroniza runtime_contracts de capabilities"
    )
    sync_parser.add_argument(
        "--spec-hub-dir", required=True, type=Path, help="Caminho do spec-hub"
    )
    sync_parser.add_argument(
        "--workspace-root", type=Path, default=None, help="Raiz dos repositórios"
    )

    audit_parser = subparsers.add_parser(
        "audit", help="Audita conformidade de domínio DDD"
    )
    audit_parser.add_argument(
        "--spec-hub-dir", required=True, type=Path, help="Caminho do spec-hub"
    )
    audit_parser.add_argument(
        "--capability", default=None, help="ID opcional da capability"
    )
    audit_parser.add_argument(
        "--workspace-root", type=Path, default=None, help="Raiz dos repositórios"
    )

    update_parser = subparsers.add_parser(
        "update-spec", help="Atualiza status de uma spec em sua capability"
    )
    update_parser.add_argument(
        "--spec-hub-dir", required=True, type=Path, help="Caminho do spec-hub"
    )
    update_parser.add_argument(
        "--spec-id", required=True, help="Identificador da spec (ex: SPEC-002)"
    )
    update_parser.add_argument(
        "--status", required=True, help="Novo status (ex: MERGED)"
    )

    map_parser = subparsers.add_parser(
        "map-all", help="Mapeia todos os repositórios do manifesto no spec-hub"
    )
    map_parser.add_argument(
        "--spec-hub-dir", required=True, type=Path, help="Caminho do spec-hub"
    )
    map_parser.add_argument(
        "--workspace-root", type=Path, default=None, help="Raiz dos repositórios"
    )
    return parser


def main() -> None:
    """Ponto de entrada de linha de comando para o Ingestor de Capacidades."""
    parser = build_capabilities_cli_parser()
    args = parser.parse_args()
    inspector = DomainInspector()

    if args.command == "sync":
        updated = inspector.sync_all(args.spec_hub_dir, args.workspace_root)
        print(f"Sincronizadas {len(updated)} capabilities com sucesso.")
        return

    if args.command == "audit":
        workspace_root = args.workspace_root or args.spec_hub_dir.resolve().parent
        for cap, _ in load_all_capabilities(args.spec_hub_dir):
            if args.capability and cap.capability_id != args.capability:
                continue
            report = inspector.audit_capability(cap, workspace_root)
            print(f"=== Auditoria: {cap.capability_id} ({cap.name}) ===")
            print(f"Termos cobertos: {report['terms_covered']}")
            print(f"Termos ausentes: {report['terms_missing']}")
            print(f"Classes extraídas: {len(report['classes'])}\n")
        return

    if args.command == "update-spec":
        success = inspector.update_spec_status(
            args.spec_hub_dir, args.spec_id, args.status
        )
        if success:
            print(f"Spec {args.spec_id} atualizada com sucesso para {args.status}.")
            return
        print(f"Spec {args.spec_id} não encontrada em nenhuma capability.")
        sys.exit(1)

    if args.command == "map-all":
        report = inspector.map_all_repositories(args.spec_hub_dir, args.workspace_root)
        print_map_all_report(report)


if __name__ == "__main__":
    main()
