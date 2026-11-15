"""Testes unitários para o extrator de capacidades da plataforma."""

import tempfile
from pathlib import Path

import yaml

from harness_state.capabilities import (
    BusinessCapability,
    CapabilityExtractor,
    CapabilityModel,
    DomainInspector,
    ProductModel,
    load_all_products,
    load_business_capability,
    load_manifest,
    load_product,
    save_business_capability,
)


def test_load_manifest_valid() -> None:
    """Business Rule: Deve carregar repos e dependências do manifest.yaml."""
    content = {
        "version": "1.0",
        "project": "paralax-ia",
        "repositories": [
            {
                "name": "paralax-evo-crm",
                "repo": "paralax-ia/paralax-evo-crm",
                "role": "sdk",
                "language": "python",
                "depends_on": [],
            },
            {
                "name": "customer-support-vehicles",
                "repo": "paralax-ia/customer-support-vehicles",
                "role": "ai-agent",
                "language": "python",
                "depends_on": ["paralax-evo-crm"],
            },
        ],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(content, f)
        temp_path = Path(f.name)

    manifest = load_manifest(temp_path)
    assert manifest.project == "paralax-ia"
    assert len(manifest.repositories) == 2
    assert manifest.repositories[0].name == "paralax-evo-crm"
    assert manifest.repositories[1].depends_on == ["paralax-evo-crm"]


def test_extract_python_classes_and_functions() -> None:
    """Business Rule: Extrai classes, métodos e docstrings públicas de módulos."""
    code = '''
class CRMAPIClient:
    """Cliente HTTP para comunicação assíncrona com o CRM."""

    async def health_check(self) -> dict:
        """Verifica a saúde do serviço."""
        return {"status": "healthy"}

    def _private_method(self):
        pass

def calculate_checksum(data: str) -> str:
    """Calcula o checksum SHA256 dos dados."""
    return "abc"
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        repo_dir = Path(tmpdir)
        src_file = repo_dir / "client.py"
        src_file.write_text(code, encoding="utf-8")

        extractor = CapabilityExtractor()
        cap = extractor.inspect_python_repo(
            repo_name="paralax-evo-crm",
            role="sdk",
            repo_dir=repo_dir,
        )

        assert cap.name == "paralax-evo-crm"
        assert cap.role == "sdk"
        assert len(cap.classes) == 1
        assert cap.classes[0]["name"] == "CRMAPIClient"
        assert len(cap.classes[0]["methods"]) == 1
        assert cap.classes[0]["methods"][0]["name"] == "health_check"
        assert len(cap.functions) == 1
        assert cap.functions[0]["name"] == "calculate_checksum"


def test_export_capability_to_yaml() -> None:
    """Business Rule: Exporta especificação de capacidade em YAML padronizado."""
    cap = CapabilityModel(
        name="customer-support-vehicles",
        role="ai-agent",
        language="python",
        description="Agente de atendimento a clientes de concessionárias",
        classes=[
            {
                "name": "VehiclesAgent",
                "docstring": "Agente ADK",
                "methods": [{"name": "run", "docstring": "Executa fluxo"}],
            }
        ],
        functions=[],
        routes=[],
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        extractor = CapabilityExtractor()
        out_file = extractor.export_capability_yaml(cap, out_dir)

        assert out_file.is_file()
        with open(out_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data["name"] == "customer-support-vehicles"
        assert data["role"] == "ai-agent"
        assert data["classes"][0]["name"] == "VehiclesAgent"


def test_load_and_save_business_capability() -> None:
    """Business Rule: Carrega e persiste Business Capabilities no formato DDD."""
    cap_data = {
        "version": "1.0",
        "capability_id": "customer-relationship-management",
        "name": "Gestão de CRM",
        "subdomain_type": "supporting",
        "description": "Gestão de contatos e conversas",
        "ubiquitous_language": {
            "Contact": "Pessoa física ou jurídica no CRM.",
            "WorkingHours": "Janela de expediente comercial.",
        },
        "context_map": {
            "upstream_authoritative": "evo-ai-crm-community",
            "sdk_layer": "paralax-evo-crm",
            "downstream_consumers": ["customer-support-vehicles"],
        },
        "specs": [
            {
                "id": "SPEC-001",
                "title": "Healthcheck",
                "status": "MERGED",
                "spec_path": "specs/SPEC-001.md",
            }
        ],
        "runtime_contracts": {
            "classes": [{"name": "CRMAPIClient", "methods": ["health_check"]}]
        },
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        cap_file = Path(tmpdir) / "capability.yaml"
        with open(cap_file, "w", encoding="utf-8") as f:
            yaml.dump(cap_data, f)

        loaded = load_business_capability(cap_file)
        assert loaded.capability_id == "customer-relationship-management"
        assert loaded.subdomain_type == "supporting"
        assert "Contact" in loaded.ubiquitous_language
        assert loaded.context_map["sdk_layer"] == "paralax-evo-crm"
        assert len(loaded.specs) == 1
        assert loaded.specs[0]["id"] == "SPEC-001"

        loaded.name = "CRM Atualizado"
        save_business_capability(loaded, cap_file)

        reloaded = load_business_capability(cap_file)
        assert reloaded.name == "CRM Atualizado"


def test_domain_inspector_audit_and_sync() -> None:
    """Business Rule: DomainInspector audita domínio e sincroniza contratos."""
    cap = BusinessCapability(
        version="1.0",
        capability_id="customer-relationship-management",
        name="CRM",
        subdomain_type="supporting",
        description="Domínio de CRM",
        ubiquitous_language={
            "Contact": "Identidade do contato.",
            "WorkingHours": "Janela de atendimento.",
            "Invoice": "Fatura financeira.",
        },
        context_map={
            "sdk_layer": "paralax-evo-crm",
            "downstream_consumers": [],
        },
        specs=[],
        runtime_contracts={},
    )

    sample_code = '''
class ContactClient:
    """Cliente para manipulação de Contact e WorkingHours."""

    def get_contact(self, contact_id: str):
        """Retorna os dados do Contact."""
        return {}

    def check_working_hours(self):
        """Valida WorkingHours."""
        return True
'''
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_dir = Path(tmpdir)
        sdk_dir = workspace_dir / "paralax-evo-crm"
        sdk_dir.mkdir(parents=True)
        (sdk_dir / "client.py").write_text(sample_code, encoding="utf-8")

        inspector = DomainInspector()
        audit_result = inspector.audit_capability(cap, workspace_dir)

        assert "Contact" in audit_result["terms_covered"]
        assert "WorkingHours" in audit_result["terms_covered"]
        assert "Invoice" in audit_result["terms_missing"]
        assert len(audit_result["classes"]) >= 1

        cap_file = workspace_dir / "capability.yaml"
        synced_cap = inspector.sync_capability(cap, workspace_dir, cap_file)

        assert cap_file.is_file()
        assert len(synced_cap.runtime_contracts["classes"]) >= 1
        assert synced_cap.runtime_contracts["classes"][0]["name"] == "ContactClient"


def test_domain_inspector_update_spec_status() -> None:
    """Business Rule: Atualiza o status de spec em sua capability."""
    cap_data = {
        "version": "1.0",
        "capability_id": "customer-relationship-management",
        "name": "CRM",
        "subdomain_type": "supporting",
        "description": "CRM",
        "ubiquitous_language": {},
        "context_map": {},
        "specs": [
            {
                "id": "SPEC-002",
                "title": "Messaging",
                "status": "PROPOSED",
                "spec_path": "specs/SPEC-002.md",
            }
        ],
        "runtime_contracts": {},
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        spec_hub_dir = Path(tmpdir)
        cap_dir = spec_hub_dir / "capabilities" / "customer-relationship-management"
        cap_dir.mkdir(parents=True)
        cap_file = cap_dir / "capability.yaml"
        with open(cap_file, "w", encoding="utf-8") as f:
            yaml.dump(cap_data, f)

        inspector = DomainInspector()
        updated = inspector.update_spec_status(spec_hub_dir, "SPEC-002", "MERGED")
        assert updated is True

        with open(cap_file, "r", encoding="utf-8") as f:
            updated_data = yaml.safe_load(f)

        assert updated_data["specs"][0]["status"] == "MERGED"


def test_domain_inspector_map_all_repositories() -> None:
    """Business Rule: Mapeia repositórios do manifesto e detecta órfãos."""
    manifest_content = {
        "version": "1.0",
        "project": "paralax-ia",
        "repositories": [
            {
                "name": "paralax-evo-crm",
                "repo": "paralax-ia/paralax-evo-crm",
                "role": "sdk",
                "language": "python",
            },
            {
                "name": "unmapped-service",
                "repo": "paralax-ia/unmapped-service",
                "role": "microservice",
                "language": "python",
            },
        ],
    }

    cap_data = {
        "version": "1.0",
        "capability_id": "customer-relationship-management",
        "name": "CRM",
        "subdomain_type": "supporting",
        "description": "CRM",
        "ubiquitous_language": {"Contact": "Contato"},
        "context_map": {
            "sdk_layer": "paralax-evo-crm",
            "downstream_consumers": [],
        },
        "specs": [],
        "runtime_contracts": {},
    }

    crm_code = '''
class CRMClient:
    """Cliente para Contact."""

    def get_contact(self):
        """Busca Contact."""
        return {}
'''
    unmapped_code = '''
class UnmappedWorker:
    """Worker sem capability."""

    def execute(self):
        pass
'''

    with tempfile.TemporaryDirectory() as tmpdir:
        root_dir = Path(tmpdir)
        spec_hub_dir = root_dir / "paralax-spec-hub"
        workspace_dir = root_dir / "workspace"

        spec_hub_dir.mkdir()
        workspace_dir.mkdir()

        with open(spec_hub_dir / "manifest.yaml", "w", encoding="utf-8") as f:
            yaml.dump(manifest_content, f)

        cap_dir = spec_hub_dir / "capabilities" / "customer-relationship-management"
        cap_dir.mkdir(parents=True)
        cap_file = cap_dir / "capability.yaml"
        with open(cap_file, "w", encoding="utf-8") as f:
            yaml.dump(cap_data, f)

        crm_repo = workspace_dir / "paralax-evo-crm"
        crm_repo.mkdir()
        (crm_repo / "client.py").write_text(crm_code, encoding="utf-8")

        unmapped_repo = workspace_dir / "unmapped-service"
        unmapped_repo.mkdir()
        (unmapped_repo / "worker.py").write_text(unmapped_code, encoding="utf-8")

        inspector = DomainInspector()
        report = inspector.map_all_repositories(spec_hub_dir, workspace_dir)

        assert report["project_name"] == "paralax-ia"
        assert report["total_repositories"] == 2
        assert "paralax-evo-crm" in report["inspected_repositories"]
        assert "unmapped-service" in report["inspected_repositories"]
        assert "unmapped-service" in report["unmapped_repositories"]
        assert len(report["capabilities_mapped"]) == 1
        assert (
            report["capabilities_mapped"][0]["capability_id"]
            == "customer-relationship-management"
        )
        assert len(report["capabilities_mapped"][0]["classes"]) >= 1

        with open(cap_file, "r", encoding="utf-8") as f:
            disk_cap = yaml.safe_load(f)
        assert len(disk_cap["runtime_contracts"]["classes"]) >= 1
        assert disk_cap["runtime_contracts"]["classes"][0]["name"] == "CRMClient"


def test_load_product_valid() -> None:
    """Business Rule: Carrega metadados e capacidades de um Produto a partir do YAML."""
    product_data = {
        "version": "1.0",
        "product_id": "customer-support-vehicles",
        "name": "Dealership Support",
        "client_segment": "Automotive Dealerships",
        "description": "Atendimento automatizado para concessionárias.",
        "repositories": ["customer-support-vehicles"],
        "capabilities": ["conversational-ai-agent", "customer-relationship-management"],
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.dump(product_data, f)
        temp_path = Path(f.name)

    product = load_product(temp_path)
    assert isinstance(product, ProductModel)
    assert product.product_id == "customer-support-vehicles"
    assert product.name == "Dealership Support"
    assert product.client_segment == "Automotive Dealerships"
    assert "customer-support-vehicles" in product.repositories
    assert "conversational-ai-agent" in product.capabilities


def test_load_all_products() -> None:
    """Business Rule: Carrega produtos na pasta products/ do spec hub."""
    with tempfile.TemporaryDirectory() as tmpdir:
        spec_hub_dir = Path(tmpdir)
        products_dir = spec_hub_dir / "products"
        products_dir.mkdir()

        p1_data = {
            "version": "1.0",
            "product_id": "dealership-support",
            "name": "Dealership Support",
            "client_segment": "Automotive",
            "description": "Vendas e pós-vendas",
            "repositories": ["dealership-repo"],
            "capabilities": ["crm"],
        }
        p2_data = {
            "version": "1.0",
            "product_id": "clinic-support",
            "name": "Clinic Support",
            "client_segment": "Health",
            "description": "Agendamentos de saúde",
            "repositories": ["clinic-repo"],
            "capabilities": ["scheduling"],
        }
        with open(products_dir / "dealership.yaml", "w", encoding="utf-8") as f:
            yaml.dump(p1_data, f)
        with open(products_dir / "clinic.yaml", "w", encoding="utf-8") as f:
            yaml.dump(p2_data, f)

        loaded_products = load_all_products(spec_hub_dir)
        assert len(loaded_products) == 2
        product_ids = [p[0].product_id for p in loaded_products]
        assert "dealership-support" in product_ids
        assert "clinic-support" in product_ids


def test_business_capability_scope_and_supported_products() -> None:
    """Business Rule: Valida scope e supported_products na BusinessCapability."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cap_file = Path(tmpdir) / "capability.yaml"
        cap = BusinessCapability(
            capability_id="appointment-scheduling",
            name="Agendamento",
            scope="product-specific",
            supported_products=["duo-dermato-support"],
            subdomain_type="core",
            description="Agendamento médico",
        )
        save_business_capability(cap, cap_file)

        loaded = load_business_capability(cap_file)
        assert loaded.scope == "product-specific"
        assert loaded.supported_products == ["duo-dermato-support"]


def test_map_all_repositories_with_products() -> None:
    """Business Rule: map_all_repositories organiza dados por Produto."""
    manifest_content = {
        "version": "1.0",
        "project": "paralax-ia",
        "repositories": [
            {
                "name": "customer-support-vehicles",
                "repo": "paralax-ia/customer-support-vehicles",
                "role": "ai-agent",
                "language": "python",
                "depends_on": [],
            }
        ],
    }
    cap_data = {
        "version": "1.0",
        "capability_id": "customer-relationship-management",
        "name": "CRM",
        "scope": "platform",
        "supported_products": ["customer-support-vehicles"],
        "subdomain_type": "supporting",
        "description": "Gestão de CRM",
        "ubiquitous_language": {"Contact": "Contato"},
        "context_map": {
            "upstream_authoritative": "customer-support-vehicles",
            "downstream_consumers": [],
        },
        "specs": [],
        "runtime_contracts": {},
    }
    product_data = {
        "version": "1.0",
        "product_id": "customer-support-vehicles",
        "name": "Dealership Support",
        "client_segment": "Automotive Dealerships",
        "description": "Atendimento para concessionárias.",
        "repositories": ["customer-support-vehicles"],
        "capabilities": ["customer-relationship-management"],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        root_dir = Path(tmpdir)
        spec_hub_dir = root_dir / "paralax-spec-hub"
        workspace_dir = root_dir / "workspace"

        spec_hub_dir.mkdir()
        workspace_dir.mkdir()

        with open(spec_hub_dir / "manifest.yaml", "w", encoding="utf-8") as f:
            yaml.dump(manifest_content, f)

        products_dir = spec_hub_dir / "products"
        products_dir.mkdir()
        with open(products_dir / "vehicles.yaml", "w", encoding="utf-8") as f:
            yaml.dump(product_data, f)

        cap_dir = spec_hub_dir / "capabilities" / "customer-relationship-management"
        cap_dir.mkdir(parents=True)
        with open(cap_dir / "capability.yaml", "w", encoding="utf-8") as f:
            yaml.dump(cap_data, f)

        repo_dir = workspace_dir / "customer-support-vehicles"
        repo_dir.mkdir()
        (repo_dir / "agent.py").write_text(
            "class Contact:\n    pass\n", encoding="utf-8"
        )

        inspector = DomainInspector()
        report = inspector.map_all_repositories(spec_hub_dir, workspace_dir)

        assert "products" in report
        assert len(report["products"]) == 1
        p_info = report["products"][0]
        assert p_info["product_id"] == "customer-support-vehicles"
        assert p_info["client_segment"] == "Automotive Dealerships"
        assert "customer-support-vehicles" in p_info["repositories"]
        assert "customer-relationship-management" in p_info["capabilities"]
