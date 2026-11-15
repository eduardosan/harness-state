"""Testes unitários para decomposição e geração de especificações técnicas."""

from pathlib import Path

from harness_state.models import SubTask
from harness_state.spec.fanout import (
    SpecSyncOutcome,
    fanout_all_repository_specs,
    filter_relevant_spec_sections,
    generate_repo_spec,
    mark_repo_spec_status,
    save_repo_spec,
    sync_spoke_spec_to_hub,
)
from harness_state.spec.lifecycle import extract_yaml_frontmatter

SAMPLE_MAIN_SPEC = """---
spec_id: SPEC-004
title: "Pipeline de Vendas Automatizado"
product:
  - paralax-support
capability: crm
target_repositories:
  - repo: paralax-ia/paralax-evo-crm
    wave: 1
    role: sdk
  - repo: paralax-ia/paralax-support
    wave: 2
    role: ai-agent
  - repo: paralax-ia/argocd
    wave: 3
    role: gitops
status: APPROVED
---

# SPEC-004: Pipeline de Vendas Automatizado

## 1. Contexto e Motivação
Descrição do contexto corporativo geral.

### Princípio Arquitetural Mandatório: Zero Arquivos de Configuração no Git (12-Factor)
Toda configuração deve vir estritamente de variáveis de ambiente.

## 2. Estrutura do Funil
Estrutura global do funil comercial.

## 3. Escopo e Repositórios Afetados

### [Onda 1] `paralax-ia/paralax-evo-crm` (SDK de Integração - `task-1`)
Requisitos específicos para o SDK paralax-evo-crm.

### [Onda 2] `paralax-ia/paralax-support` (Agente Paralax Support - `task-2`)
Requisitos específicos para o agente paralax-support.

### [Onda 3] `paralax-ia/argocd` (GitOps / Infraestrutura - `task-3`)
Requisitos específicos para manifestos do ArgoCD.

## 4. Contratos de Interface

### 4.1. Contrato da API REST do CRM (`evo-ai-crm-community`)
Rotas e payloads da API REST.

### 4.2. Contratos do SDK Python (`paralax-evo-crm`)
Modelos e métodos do SDK paralax-evo-crm.

### 4.3. Configuração no Agente (`paralax-support`)
Configuração e callbacks no agente paralax-support.

### 4.4. Injeção Declarativa no ArgoCD (`argocd`)
Manifestos K8s e injeção de env vars no repositório argocd.

## 5. Critérios de Aceitação (Gherkin)

### Cenário 1: Leitura de Configurações no SDK
Dado que o SDK paralax-evo-crm inicializa.

### Cenário 2: Decisão de Transição via LLM no Agente
Dado que o agente paralax-support processa a mensagem com LLM.

### Cenário 3: Injeção de Variáveis pelo ArgoCD
Dado que o manifesto do argocd injeta as variáveis no pod.
"""


def test_filter_relevant_spec_sections_extracts_repo_specific() -> None:
    """Business Rule: Filtra seções mantendo contexto e escopo do repositório."""
    filtered = filter_relevant_spec_sections(
        body=SAMPLE_MAIN_SPEC,
        repo_name="paralax-ia/paralax-evo-crm",
        task_id="task-1",
    )
    assert "Contexto e Motivação" in filtered
    assert "paralax-evo-crm" in filtered
    assert "Contratos do SDK Python (`paralax-evo-crm`)" in filtered
    assert "[Onda 2] `paralax-ia/paralax-support`" not in filtered


def test_generate_repo_spec_creates_complete_sub_spec(tmp_path: Path) -> None:
    """Business Rule: Gera sub-spec autocontida com metadados do spoke."""
    main_spec_file = tmp_path / "SPEC-004.md"
    main_spec_file.write_text(SAMPLE_MAIN_SPEC, encoding="utf-8")

    subtask = SubTask(
        id="task-1",
        repo="paralax-ia/paralax-evo-crm",
        branch="feat/spec-004-crm",
        wave=1,
        expected_version="0.2.0",
    )

    spec_text = generate_repo_spec(
        main_spec_path=main_spec_file,
        repo_name="paralax-ia/paralax-evo-crm",
        task=subtask,
    )

    frontmatter, body = extract_yaml_frontmatter(spec_text)
    assert frontmatter["spec_id"] == "SPEC-004"
    assert frontmatter["parent_spec"] == "SPEC-004"
    assert frontmatter["repo"] == "paralax-ia/paralax-evo-crm"
    assert frontmatter["task_id"] == "task-1"
    assert frontmatter["wave"] == 1
    assert frontmatter["status"] == "IN_PROGRESS"
    assert "Contexto e Motivação" in body
    assert "paralax-evo-crm" in body


def test_generate_repo_spec_propagates_prompts_to_frontmatter(tmp_path: Path) -> None:
    """Business Rule: A sub-spec deve herdar os prompts declarados na spec central."""
    spec_with_prompts = (
        "---\n"
        "spec_id: SPEC-009\n"
        "title: Suporte a Audio\n"
        "prompts:\n"
        "  - vehicles/vehicle_search_agent_instruction\n"
        "target_repositories:\n"
        "  - repo: paralax-ia/customer-support-vehicles\n"
        "    wave: 2\n"
        "status: APPROVED\n"
        "---\n\n"
        "# SPEC-009: Suporte a Audio\n"
    )
    main_spec_file = tmp_path / "SPEC-009.md"
    main_spec_file.write_text(spec_with_prompts, encoding="utf-8")

    subtask = SubTask(
        id="task-2",
        repo="paralax-ia/customer-support-vehicles",
        branch="feat/spec-009-audio",
        wave=2,
    )

    spec_text = generate_repo_spec(
        main_spec_path=main_spec_file,
        repo_name="paralax-ia/customer-support-vehicles",
        task=subtask,
    )

    frontmatter, _ = extract_yaml_frontmatter(spec_text)
    assert "prompts" in frontmatter
    assert "vehicles/vehicle_search_agent_instruction" in frontmatter["prompts"]


def test_save_repo_spec_writes_to_repo_specs_dir(tmp_path: Path) -> None:
    """Business Rule: Salva sub-spec no diretório specs/ do spoke."""
    repo_dir = tmp_path / "paralax-evo-crm"
    repo_dir.mkdir()

    saved_path = save_repo_spec(
        repo_dir=repo_dir,
        spec_id="SPEC-004",
        content="# SPEC-004 Sub Spec\n\nDetalhes da task.",
    )

    assert saved_path.exists()
    assert saved_path.parent == repo_dir / "specs"
    assert saved_path.name == "SPEC-004.md"
    assert "Detalhes da task" in saved_path.read_text(encoding="utf-8")


def test_mark_repo_spec_status_updates_frontmatter(tmp_path: Path) -> None:
    """Business Rule: Atualiza o status no frontmatter da spec para IMPLEMENTED."""
    repo_dir = tmp_path / "paralax-evo-crm"
    specs_dir = repo_dir / "specs"
    specs_dir.mkdir(parents=True)

    spec_file = specs_dir / "SPEC-004.md"
    spec_file.write_text(
        "---\nspec_id: SPEC-004\nstatus: IN_PROGRESS\n---\n\n# Body",
        encoding="utf-8",
    )

    updated = mark_repo_spec_status(
        repo_dir=repo_dir,
        spec_id="SPEC-004",
        new_status="IMPLEMENTED",
    )
    assert updated is True

    frontmatter, body = extract_yaml_frontmatter(spec_file.read_text(encoding="utf-8"))
    assert frontmatter["status"] == "IMPLEMENTED"
    assert body.strip() == "# Body"


def test_filter_relevant_spec_sections_mutual_exclusion() -> None:
    """Business Rule: As seções extraídas para diferentes spokes devem ser disjuntas."""
    # 1. Filtro para crm
    crm_filtered = filter_relevant_spec_sections(
        body=SAMPLE_MAIN_SPEC,
        repo_name="paralax-ia/paralax-evo-crm",
        task_id="task-1",
    )
    assert "paralax-evo-crm" in crm_filtered
    assert "Contratos do SDK Python (`paralax-evo-crm`)" in crm_filtered
    assert "Cenário 1: Leitura de Configurações no SDK" in crm_filtered
    # Não pode conter partes exclusivas do Agente ou do ArgoCD
    assert "[Onda 2] `paralax-ia/paralax-support`" not in crm_filtered
    assert "[Onda 3] `paralax-ia/argocd`" not in crm_filtered
    assert "Configuração no Agente (`paralax-support`)" not in crm_filtered
    assert "Injeção Declarativa no ArgoCD (`argocd`)" not in crm_filtered
    assert "Cenário 2: Decisão de Transição via LLM no Agente" not in crm_filtered
    assert "Cenário 3: Injeção de Variáveis pelo ArgoCD" not in crm_filtered

    # 2. Filtro para argocd
    argocd_filtered = filter_relevant_spec_sections(
        body=SAMPLE_MAIN_SPEC,
        repo_name="paralax-ia/argocd",
        task_id="task-3",
    )
    assert "argocd" in argocd_filtered
    assert "Injeção Declarativa no ArgoCD (`argocd`)" in argocd_filtered
    assert "Cenário 3: Injeção de Variáveis pelo ArgoCD" in argocd_filtered
    # Não pode conter partes exclusivas do SDK ou do Agente
    assert "[Onda 1] `paralax-ia/paralax-evo-crm`" not in argocd_filtered
    assert "[Onda 2] `paralax-ia/paralax-support`" not in argocd_filtered
    assert "Contratos do SDK Python (`paralax-evo-crm`)" not in argocd_filtered
    assert "Configuração no Agente (`paralax-support`)" not in argocd_filtered
    assert "Cenário 1: Leitura de Configurações no SDK" not in argocd_filtered
    assert "Cenário 2: Decisão de Transição via LLM no Agente" not in argocd_filtered


def test_fanout_all_repository_specs_creates_three_distinct_specs(
    tmp_path: Path,
) -> None:
    """Business Rule: Fanout gera 3 specs específicas nos 3 repositórios afetados."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    # Cria os 3 diretórios de repositórios
    crm_dir = workspace / "paralax-evo-crm"
    support_dir = workspace / "paralax-support"
    argocd_dir = workspace / "argocd"
    crm_dir.mkdir()
    support_dir.mkdir()
    argocd_dir.mkdir()

    main_spec_file = workspace / "SPEC-004.md"
    main_spec_file.write_text(SAMPLE_MAIN_SPEC, encoding="utf-8")

    generated = fanout_all_repository_specs(
        main_spec_path=main_spec_file,
        workspace_root=workspace,
    )

    assert len(generated) == 3
    assert "paralax-ia/paralax-evo-crm" in generated
    assert "paralax-ia/paralax-support" in generated
    assert "paralax-ia/argocd" in generated

    crm_spec = generated["paralax-ia/paralax-evo-crm"].read_text(encoding="utf-8")
    support_spec = generated["paralax-ia/paralax-support"].read_text(encoding="utf-8")
    argocd_spec = generated["paralax-ia/argocd"].read_text(encoding="utf-8")

    # Cada arquivo é único e específico
    assert "Contratos do SDK Python (`paralax-evo-crm`)" in crm_spec
    assert "Injeção Declarativa no ArgoCD (`argocd`)" not in crm_spec

    assert "Configuração no Agente (`paralax-support`)" in support_spec
    assert "Injeção Declarativa no ArgoCD (`argocd`)" not in support_spec

    assert "Injeção Declarativa no ArgoCD (`argocd`)" in argocd_spec
    assert "Contratos do SDK Python (`paralax-evo-crm`)" not in argocd_spec


def test_sync_spoke_spec_to_hub_reconciles_changes(tmp_path: Path) -> None:
    """Business Rule: Reconcilia edições locais do spoke de volta para o spec-hub."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    support_dir = workspace / "paralax-support"
    support_dir.mkdir()

    hub_spec_file = workspace / "SPEC-004.md"
    hub_spec_file.write_text(SAMPLE_MAIN_SPEC, encoding="utf-8")

    fanout_all_repository_specs(
        main_spec_path=hub_spec_file,
        workspace_root=workspace,
    )

    support_spec_file = support_dir / "specs" / "SPEC-004.md"
    assert support_spec_file.exists()

    # O agente em paralax-support altera sua sub-spec local adicionando um novo cenário
    current_content = support_spec_file.read_text(encoding="utf-8")
    updated_content = current_content + (
        "\n### Cenário 10: Novo Cenário de Vendas Adicionado no Spoke\n"
        "Dado que o lead enviou documento comprobatório.\n"
        "Quando o agente validar com LLM.\n"
        "Então avança para etapa proposta apresentada.\n"
    )
    support_spec_file.write_text(updated_content, encoding="utf-8")

    outcome = sync_spoke_spec_to_hub(
        spoke_spec_path=support_spec_file,
        hub_spec_path=hub_spec_file,
    )

    assert isinstance(outcome, SpecSyncOutcome)
    assert outcome.success is True
    assert outcome.spec_id == "SPEC-004"
    assert "Critérios de Aceitação (Gherkin)" in outcome.updated_sections

    hub_text = hub_spec_file.read_text(encoding="utf-8")
    assert "Cenário 10: Novo Cenário de Vendas Adicionado no Spoke" in hub_text
    # Garante que as seções dos outros repositórios permaneceram intactas no hub
    assert "[Onda 1] `paralax-ia/paralax-evo-crm`" in hub_text
    assert "[Onda 3] `paralax-ia/argocd`" in hub_text
    assert "Contratos do SDK Python (`paralax-evo-crm`)" in hub_text
    assert "Injeção Declarativa no ArgoCD (`argocd`)" in hub_text
