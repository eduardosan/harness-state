"""Testes unitários para ciclo de vida e aprovação de specs."""

from pathlib import Path

from harness_state.models import SpecRun, SubTask, TaskState
from harness_state.spec.lifecycle import (
    approve_spec,
    build_spec_refine_prompt,
    create_spec_draft,
    ensure_spec_has_prompts,
    get_frozen_and_pending_tasks,
    get_next_spec_id,
    merge_refined_spec,
    resolve_spec_file_path,
    resolve_specs_directory,
    validate_spec_feasibility,
)


def test_get_next_spec_id_when_empty(tmp_path: Path) -> None:
    """Business Rule: Quando não houver specs, o primeiro ID é SPEC-001."""
    next_id = get_next_spec_id(tmp_path)
    assert next_id == "SPEC-001"


def test_get_next_spec_id_increments_highest(tmp_path: Path) -> None:
    """Business Rule: O próximo ID incrementa o maior sequencial existente."""
    (tmp_path / "SPEC-001-health.md").write_text("spec 1", encoding="utf-8")
    (tmp_path / "SPEC-003-orchestration.md").write_text("spec 3", encoding="utf-8")

    next_id = get_next_spec_id(tmp_path)
    assert next_id == "SPEC-004"


def test_create_spec_draft_generates_file_with_draft_status(tmp_path: Path) -> None:
    """Business Rule: Criação de rascunho deve gerar arquivo com status DRAFT."""
    spec_path = create_spec_draft(
        title="Nova Funcionalidade",
        specs_dir=tmp_path,
    )

    assert spec_path.is_file()
    assert "SPEC-001-nova-funcionalidade.md" in spec_path.name
    content = spec_path.read_text(encoding="utf-8")
    assert "status: DRAFT" in content
    assert "SPEC-001" in content
    assert "Nova Funcionalidade" in content


def test_create_spec_draft_replaces_module_name_placeholder(tmp_path: Path) -> None:
    """Business Rule: Substitui placeholder 'module-name' pelo nome real do spoke."""
    module_specs = tmp_path / "customer-support-vehicles" / "specs"
    spec_path = create_spec_draft(
        title="Refactor Vehicles",
        specs_dir=module_specs,
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "module-name" not in content
    assert "customer-support-vehicles" in content


def test_approve_spec_transitions_status_to_approved(tmp_path: Path) -> None:
    """Business Rule: Aprovação (Gate 2) altera status da spec para APPROVED."""
    spec_path = create_spec_draft(
        title="Automação de Testes",
        specs_dir=tmp_path,
    )

    success = approve_spec(spec_path)
    assert success is True

    updated_content = spec_path.read_text(encoding="utf-8")
    assert "status: APPROVED" in updated_content
    assert "status: DRAFT" not in updated_content


def test_resolve_specs_directory_prefers_explicit(tmp_path: Path) -> None:
    """Business Rule: Diretório explícito tem precedência sobre autodescoberta."""
    explicit = tmp_path / "custom-specs"
    explicit.mkdir()
    resolved = resolve_specs_directory(specs_dir=explicit, workspace_root=tmp_path)
    assert resolved == explicit


def test_resolve_specs_directory_discovers_spec_hub(tmp_path: Path) -> None:
    """Business Rule: Na raiz do workspace, specs devem ir para spec-hub/specs."""
    hub_dir = tmp_path / "paralax-spec-hub"
    hub_dir.mkdir(parents=True)
    manifest = hub_dir / "manifest.yaml"
    manifest.write_text("version: '1.0'\nrepositories: []\n", encoding="utf-8")
    hub_specs = hub_dir / "specs"
    hub_specs.mkdir()

    resolved = resolve_specs_directory(workspace_root=tmp_path)
    assert resolved == hub_specs


def test_resolve_spec_file_path_finds_by_id_or_name(tmp_path: Path) -> None:
    """Business Rule: Localizar arquivo de spec por ID ou nome no diretório."""
    specs_dir = tmp_path / "specs"
    specs_dir.mkdir()
    target_spec = specs_dir / "SPEC-003-orchestration.md"
    target_spec.write_text("status: DRAFT", encoding="utf-8")

    found_direct = resolve_spec_file_path(target_spec, specs_dir=specs_dir)
    assert found_direct == target_spec

    found_by_name = resolve_spec_file_path(
        "SPEC-003-orchestration.md", specs_dir=specs_dir
    )
    assert found_by_name == target_spec

    found_by_id = resolve_spec_file_path("SPEC-003", specs_dir=specs_dir)
    assert found_by_id == target_spec


def test_get_frozen_and_pending_tasks_separates_correctly() -> None:
    """Business Rule: Tarefas READY e APPROVED são congeladas; demais são refináveis."""
    tasks = {
        "task-1": SubTask(
            id="task-1",
            repo="paralax-ia/crm",
            branch="task/1",
            status=TaskState.READY,
            pr_number=10,
        ),
        "task-2": SubTask(
            id="task-2",
            repo="paralax-ia/support",
            branch="task/2",
            status=TaskState.PENDING,
        ),
        "task-3": SubTask(
            id="task-3",
            repo="paralax-ia/billing",
            branch="task/3",
            status=TaskState.APPROVED,
            pr_number=11,
        ),
    }
    spec_run = SpecRun(
        spec_id="SPEC-001",
        title="Teste",
        author="test-author",
        tasks=tasks,
        declared_status="DRAFT",
    )

    frozen, pending = get_frozen_and_pending_tasks(spec_run)
    assert len(frozen) == 2
    assert {t.id for t in frozen} == {"task-1", "task-3"}
    assert len(pending) == 1
    assert pending[0].id == "task-2"


def test_merge_refined_spec_preserves_frozen_tasks() -> None:
    """Business Rule: Merge de spec refinada preserva tarefas finalizadas ou aprovadas."""
    old_tasks = {
        "task-1": SubTask(
            id="task-1",
            repo="paralax-ia/crm",
            branch="task/1",
            status=TaskState.READY,
            pr_number=10,
        ),
        "task-2": SubTask(
            id="task-2",
            repo="paralax-ia/support",
            branch="task/2-old",
            status=TaskState.PENDING,
        ),
    }
    existing_spec = SpecRun(
        spec_id="SPEC-001",
        title="Versão 1",
        author="test-author",
        tasks=old_tasks,
        declared_status="APPROVED",
    )

    new_tasks = {
        "task-1": SubTask(
            id="task-1",
            repo="paralax-ia/crm",
            branch="task/1-modified",
            status=TaskState.PENDING,
        ),
        "task-2": SubTask(
            id="task-2",
            repo="paralax-ia/support",
            branch="task/2-new",
            status=TaskState.PENDING,
        ),
        "task-3": SubTask(
            id="task-3",
            repo="paralax-ia/billing",
            branch="task/3",
            status=TaskState.PENDING,
        ),
    }
    new_spec = SpecRun(
        spec_id="SPEC-001",
        title="Versão 2",
        author="test-author",
        tasks=new_tasks,
        declared_status="DRAFT",
    )

    merged = merge_refined_spec(existing_spec=existing_spec, new_parsed=new_spec)
    assert merged.tasks["task-1"].status == TaskState.READY
    assert merged.tasks["task-1"].branch == "task/1"
    assert merged.tasks["task-2"].branch == "task/2-old"
    assert "task-3" in merged.tasks
    assert merged.declared_status == "APPROVED"


def test_ensure_spec_has_prompts_injects_discovered_prompts(tmp_path: Path) -> None:
    """Business Rule: Auto-descoberta injeta prompts descobertos na spec."""
    agent_repo = tmp_path / "customer-support-vehicles"
    agent_repo.mkdir()
    vehicles_dir = agent_repo / "vehicles"
    vehicles_dir.mkdir()
    (vehicles_dir / "agent.py").write_text(
        'prompt_name = "vehicles/vehicle_search_agent_instruction"\n',
        encoding="utf-8",
    )
    (vehicles_dir / "prompts.py").write_text(
        "INSTRUCTION = 'teste'\n", encoding="utf-8"
    )

    spec_file = tmp_path / "SPEC-009.md"
    spec_file.write_text(
        """---
spec_id: SPEC-009
title: "Audio"
target_repositories:
  - repo: paralax-ia/customer-support-vehicles
    wave: 2
    role: ai-agent
status: DRAFT
---
# SPEC-009
""",
        encoding="utf-8",
    )

    enriched = ensure_spec_has_prompts(spec_file, workspace_root=tmp_path)
    assert len(enriched) > 0
    updated_content = spec_file.read_text(encoding="utf-8")
    assert "vehicles/vehicle_search_agent_instruction" in updated_content


def test_approve_spec_auto_injects_prompts(tmp_path: Path) -> None:
    """Business Rule: Aprovação (approve_spec) injeta prompts do repositório."""
    agent_repo = tmp_path / "customer-support-vehicles"
    agent_repo.mkdir()
    vehicles_dir = agent_repo / "vehicles"
    vehicles_dir.mkdir()
    (vehicles_dir / "agent.py").write_text(
        'prompt_name = "vehicles/vehicle_search_agent_instruction"\n',
        encoding="utf-8",
    )
    (vehicles_dir / "prompts.py").write_text(
        "INSTRUCTION = 'teste'\n", encoding="utf-8"
    )

    spec_file = tmp_path / "SPEC-009.md"
    spec_file.write_text(
        """---
spec_id: SPEC-009
title: "Audio"
target_repositories:
  - repo: paralax-ia/customer-support-vehicles
    wave: 2
    role: ai-agent
status: DRAFT
---
# SPEC-009
""",
        encoding="utf-8",
    )

    success = approve_spec(spec_file, workspace_root=tmp_path)
    assert success is True
    content = spec_file.read_text(encoding="utf-8")
    assert "status: APPROVED" in content
    assert "vehicles/vehicle_search_agent_instruction" in content


def test_build_spec_refine_prompt_includes_mandatory_prompt_governance_rule(
    tmp_path: Path,
) -> None:
    """Business Rule: O prompt de refinamento exige governança de prompts."""
    spec_file = tmp_path / "SPEC-009.md"
    prompt = build_spec_refine_prompt(
        spec_path=spec_file,
        spec_content="# SPEC-009",
        frozen_tasks=[],
        pending_tasks=[],
        user_instruction="Atualizar modelo",
    )
    assert "MANDATORY PROMPT GOVERNANCE" in prompt
    assert "SPEC-PROMPT-01" in prompt


def test_build_spec_refine_prompt_includes_technical_feasibility_rule(
    tmp_path: Path,
) -> None:
    """Business Rule: Refinamento exige viabilidade técnica e compatibilidade."""
    spec_file = tmp_path / "SPEC-009.md"
    prompt = build_spec_refine_prompt(
        spec_path=spec_file,
        spec_content="# SPEC-009",
        frozen_tasks=[],
        pending_tasks=[],
        user_instruction="Adicionar suporte a streaming de áudio via Live API",
    )
    assert "MANDATORY TECHNICAL FEASIBILITY" in prompt
    assert "Section 3.1" in prompt
    assert "role: spike" in prompt


def test_create_spec_draft_includes_technical_feasibility_section(
    tmp_path: Path,
) -> None:
    """Business Rule: Rascunhos devem conter a seção 3.1 de viabilidade técnica."""
    spec_path = create_spec_draft(
        title="Streaming de Voz com ADK",
        specs_dir=tmp_path,
    )
    content = spec_path.read_text(encoding="utf-8")
    assert "3.1. Viabilidade Técnica e Compatibilidade de SDKs" in content
    assert "Plano de Fallback Arquitetural" in content


def test_validate_spec_feasibility_detects_unverified_live_api() -> None:
    """Business Rule: Detecta falta de análise de compatibilidade para Live API."""
    infeasible_spec = """---
spec_id: SPEC-009
title: "Integração Gemini Live API"
status: DRAFT
target_repositories:
  - repo: paralax-ia/customer-support-vehicles
    wave: 1
    role: ai-agent
---
# SPEC-009: Integração Gemini Live API

## 1. Contexto e Motivação
Adicionar chamadas via Live API do ADK.

## 2. Escopo
Escopo aqui.

## 3. Contratos de Interface
Chamadas diretas bidirecionais via websocket.
"""
    is_valid, issues = validate_spec_feasibility(infeasible_spec)
    assert is_valid is False
    assert len(issues) >= 1
    assert any("3.1" in issue or "Viabilidade Técnica" in issue for issue in issues)


def test_validate_spec_feasibility_passes_when_section_and_fallback_present() -> None:
    """Business Rule: Aprova spec quando seção 3.1 e fallback/spike presentes."""
    valid_spec = """---
spec_id: SPEC-009
title: "Integração Gemini Live API"
status: DRAFT
target_repositories:
  - repo: paralax-ia/customer-support-vehicles
    wave: 0
    role: spike
---
# SPEC-009: Integração Gemini Live API

## 3. Contratos de Interface

### 3.1. Viabilidade Técnica e Compatibilidade de SDKs / APIs Externas
- Dependências: google-genai>=1.0.0
- Protocolo: WebSocket bidirecional Live API
- Limitações: Sem paridade com function calling síncrono.
- Plano de Fallback Arquitetural: Fallback para turn-by-turn se desconectar.
- Tarefa de Spike na Onda 0 para comprovação do SDK.
"""
    is_valid, issues = validate_spec_feasibility(valid_spec)
    assert is_valid is True
    assert len(issues) == 0


def test_validate_spec_feasibility_passes_for_standard_spec() -> None:
    """Business Rule: Specs padrão sem APIs de streaming passam na validação."""
    standard_spec = """---
spec_id: SPEC-001
title: "Cadastro de Veículos"
status: DRAFT
target_repositories:
  - repo: paralax-ia/customer-support-vehicles
    wave: 1
    role: service
---
# SPEC-001: Cadastro de Veículos
## 1. Contexto
Cadastro de veículos via API REST.
## 3. Contratos de Interface
Endpoint POST /vehicles.
"""
    is_valid, issues = validate_spec_feasibility(standard_spec)
    assert is_valid is True
    assert len(issues) == 0


def test_match_canonical_prompt_does_not_overwrite_declared_name_with_generic_instruction() -> None:
    """Business Rule: Prompts declarados com namespace de repositório não devem ser substituídos pelo fallback genérico instruction."""
    from harness_state.spec.lifecycle import match_canonical_prompt

    declared = "harness-state/architect_spec_discovery"
    discovered = ["harness_state/instruction"]
    clean_short = "harness_state"

    canonical = match_canonical_prompt(declared, discovered, clean_short)
    assert canonical == declared

