"""Testes unitários para o módulo de ciclo de vida de bugs guiado por SDD."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from harness_state.agents import AgentRunner, DetectedAgent
from harness_state.bug import (
    BugPlan,
    StateBackendUnavailableError,
    build_bug_feedback_prompt,
    build_bug_fix_prompt,
    build_gcloud_logging_command,
    compile_bug_issue_markdown,
    create_github_bug_issue,
    elicit_bug_plan_with_llm,
    ensure_state_backends_available,
    extract_log_query_context_with_llm,
    generate_test_file_from_plan,
    infer_spoke_from_prompt_heuristic,
    interactive_fetch_cloud_logs,
    load_bug_plan_target,
    load_cloud_environment_config,
    merge_bug_pr_and_close_issue,
    parse_bug_issue_markdown,
    publish_bug_pr,
    record_bug_state_in_redis,
    refine_bug_plan_with_llm,
    resolve_container_name_for_spoke,
    resolve_flow_containers_for_spoke,
    resolve_github_repo_for_spoke,
    resolve_most_probable_spoke,
    resolve_spoke_directory,
    resolve_spoke_wave_and_dependencies,
    send_bug_telemetry_to_es,
    update_github_bug_issue,
    update_github_issue_status_label,
)


class FlakyRedisFactory:
    """Fake Redis factory that fails a fixed number of times before succeeding."""

    def __init__(self, failures: int) -> None:
        """Initializes the factory.

        Args:
            failures: Number of initial calls that raise ConnectionError.
        """
        self.failures = failures
        self.attempts = 0

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Counts the attempt and raises or returns a fake client.

        Args:
            *args: Ignored positional arguments.
            **kwargs: Ignored keyword arguments.

        Returns:
            A MagicMock standing in for the Redis client.

        Raises:
            ConnectionError: While the failure budget is not exhausted.
        """
        self.attempts += 1
        if self.attempts <= self.failures:
            raise ConnectionError("Timeout connecting to server")
        return MagicMock()




def test_compile_bug_issue_markdown_structure() -> None:
    """Business Rule: A compilação deve conter as seções obrigatórias da SSOT."""
    plan = BugPlan(
        title="[Bug] Erro de concorrência ao atualizar status",
        summary="Status do agendamento permanece CONFIRMED após cancelamento.",
        observed_behavior="Status permanece inalterado.",
        expected_behavior="Status deve transicionar para CANCELLED.",
        affected_spoke="google-calendar-agent",
        affected_capability="scheduling",
        runtime_contract="CalendarService.cancel_appointment",
        reproduction_steps=[
            "Cancelar evento no Google Calendar",
            "Consultar status no CRM",
        ],
        test_file_path="tests/unit/test_issue_105_cancel.py",
        test_function_name="test_cancellation_syncs_to_crm",
        business_rule=(
            "Ao cancelar evento no Calendar, status no CRM deve ser CANCELLED."
        ),
        selected_cloud_log=(
            '{"timestamp": "2026-10-24T08:15:00Z", "severity": "ERROR"}'
        ),
        intake_prompt="Ao cancelar consulta médica, o status no CRM continua CONFIRMED",
    )

    markdown = compile_bug_issue_markdown(plan)

    assert "<!-- flywheel:bug-plan:v1 -->" in markdown
    assert "## 📋 Sumário Executivo do Defeito" in markdown
    assert plan.summary in markdown
    assert "## 🔍 Sintomas Observados vs. Comportamento Esperado" in markdown
    assert plan.observed_behavior in markdown
    assert plan.expected_behavior in markdown
    assert "## ☁️ Evidência Selecionada no Google Cloud Logging (GCP)" in markdown
    assert "2026-10-24T08:15:00Z" in markdown
    assert "## 🎯 Fronteiras Arquiteturais & Capacidades DDD Afetadas" in markdown
    assert "`google-calendar-agent`" in markdown
    assert "`scheduling`" in markdown
    assert "## 🧪 Especificação do Teste TDD (Fail-First Contract)" in markdown
    assert "`tests/unit/test_issue_105_cancel.py`" in markdown
    assert '"""Business Rule: Ao cancelar evento no Calendar' in markdown




def test_parse_bug_issue_markdown_reconstitution() -> None:
    """Business Rule: O parse do markdown deve reconstruir fidedignamente o BugPlan."""
    plan = BugPlan(
        title="",
        summary="Falha no timeout do sidecar S2S",
        observed_behavior="HTTP 504 Gateway Timeout",
        expected_behavior="Resposta 200 OK com fallback",
        affected_spoke="evo-crm",
        affected_capability="crm-gateway",
        runtime_contract="ProxyOutbound.dispatch",
        reproduction_steps=["Executar requisição concorrente"],
        test_file_path="tests/unit/test_s2s_timeout.py",
        test_function_name="test_proxy_timeout_fallback",
        business_rule="Requisições com timeout devem ativar circuito de fallback.",
        selected_cloud_log='{"error": "upstream request timeout"}',
        intake_prompt="Sidecar S2S retorna 504 em alta carga",
    )

    markdown = compile_bug_issue_markdown(plan)
    parsed_plan = parse_bug_issue_markdown(markdown)

    assert parsed_plan.summary == plan.summary
    assert parsed_plan.observed_behavior == plan.observed_behavior
    assert parsed_plan.expected_behavior == plan.expected_behavior
    assert parsed_plan.affected_spoke == plan.affected_spoke
    assert parsed_plan.affected_capability == plan.affected_capability
    assert parsed_plan.runtime_contract == plan.runtime_contract
    assert parsed_plan.test_file_path == plan.test_file_path
    assert parsed_plan.test_function_name == plan.test_function_name
    assert parsed_plan.business_rule == plan.business_rule
    assert parsed_plan.selected_cloud_log is not None
    assert "upstream request timeout" in parsed_plan.selected_cloud_log
    assert parsed_plan.intake_prompt == plan.intake_prompt




def test_compile_and_parse_bug_issue_markdown_with_prompts() -> None:
    """Business Rule: Serializa e reconstrói prompts de IA afetados sob governança."""
    plan = BugPlan(
        title="Alucinação em modelo veicular",
        summary="Veículo citado sem dados de estoque",
        observed_behavior="Alucina Prisma",
        expected_behavior="Apresenta apenas Onix",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="SearchAgent.respond",
        prompts=["vehicles/vehicle_search_agent_instruction"],
    )

    markdown = compile_bug_issue_markdown(plan)
    assert "## 📝 Prompts de IA Sob Governança (Langfuse)" in markdown
    expected_prompt_line = (
        "- **Prompts Afetados:** `vehicles/vehicle_search_agent_instruction`"
    )
    assert expected_prompt_line in markdown

    parsed = parse_bug_issue_markdown(markdown)
    assert parsed.prompts == ["vehicles/vehicle_search_agent_instruction"]




def test_generate_test_file_from_plan_creates_failing_test(
    tmp_path: Path,
) -> None:
    """Business Rule: A geração de teste TDD deve instanciar arquivo com falha."""
    plan = BugPlan(
        title="Bug Test",
        summary="Resumo",
        observed_behavior="Errado",
        expected_behavior="Certo",
        affected_spoke="sample-spoke",
        affected_capability="core",
        runtime_contract="Service.run",
        test_file_path="tests/unit/test_sample_bug.py",
        test_function_name="test_contract_violation_repro",
        business_rule="O cálculo de comissão deve considerar descontos aplicados.",
    )

    test_path = generate_test_file_from_plan(plan, tmp_path)

    assert test_path.is_file()
    assert test_path.name == "test_sample_bug.py"

    content = test_path.read_text(encoding="utf-8")
    assert "def test_contract_violation_repro() -> None:" in content
    expected_docstring = (
        '"""Business Rule: O cálculo de comissão deve considerar '
        'descontos aplicados."""'
    )
    assert expected_docstring in content
    expected_assert = (
        'assert False, "Reprodução TDD: falha mandatória antes da correção."'
    )
    assert expected_assert in content




def test_generate_test_file_from_plan_preserves_existing_file(
    tmp_path: Path,
) -> None:
    """Business Rule: generate_test_file não sobrescreve testes já existentes."""
    plan = BugPlan(
        title="Bug Test",
        summary="Resumo",
        observed_behavior="Errado",
        expected_behavior="Certo",
        affected_spoke="sample-spoke",
        affected_capability="core",
        runtime_contract="Service.run",
        test_file_path="tests/unit/test_sample_bug.py",
        test_function_name="test_contract_violation_repro",
        business_rule="Regra.",
    )
    test_file = tmp_path / "tests" / "unit" / "test_sample_bug.py"
    test_file.parent.mkdir(parents=True, exist_ok=True)
    custom_content = "def test_custom() -> None:\n    pass\n"
    test_file.write_text(custom_content, encoding="utf-8")

    result_path = generate_test_file_from_plan(plan, tmp_path)
    assert result_path == test_file
    assert test_file.read_text(encoding="utf-8") == custom_content




def test_load_cloud_environment_config_from_manifest(tmp_path: Path) -> None:
    """Business Rule: Deve extrair as configurações de nuvem a partir do manifest."""
    manifest_content = (
        "version: 1\n"
        "name: test-hub\n"
        "cloud_environments:\n"
        "  production:\n"
        "    provider: gcp\n"
        "    project_id: paralax-prod\n"
        "    project_number: '847291039482'\n"
        "    kubernetes:\n"
        "      cluster_name: prod-gke-cluster\n"
        "      location: us-east1\n"
        "      namespace: production\n"
    )
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_content, encoding="utf-8")

    config = load_cloud_environment_config(manifest_file, environment="production")
    assert config["provider"] == "gcp"
    assert config["project_id"] == "paralax-prod"
    assert config["kubernetes"]["cluster_name"] == "prod-gke-cluster"




def test_load_cloud_env_config_missing_environment_raises(
    tmp_path: Path,
) -> None:
    """Business Rule: Se o ambiente não for declarado, deve levantar KeyError."""
    manifest_content = (
        "version: 1\ncloud_environments:\n  staging:\n    provider: gcp\n"
    )
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_content, encoding="utf-8")

    with pytest.raises(KeyError) as exc_info:
        load_cloud_environment_config(manifest_file, environment="production")

    assert "não declarado em cloud_environments" in str(exc_info.value)




def test_build_gcloud_logging_command_with_relative_since() -> None:
    """Business Rule: Consulta de logs com tempo relativo gera timestamp válido."""
    cloud_config = {
        "project_id": "paralax-prod",
        "kubernetes": {
            "cluster_name": "prod-gke-cluster",
            "namespace": "production",
        },
    }

    cmd = build_gcloud_logging_command(
        cloud_config=cloud_config,
        container_name="evo-ai-crm-community",
        severity="ERROR",
        since="2h",
        limit=50,
    )

    cmd_string = " ".join(cmd)
    assert "gcloud logging read" in cmd_string
    assert 'resource.labels.container_name="evo-ai-crm-community"' in cmd_string
    assert 'resource.labels.cluster_name="prod-gke-cluster"' in cmd_string
    assert "severity>=ERROR" in cmd_string
    assert "--freshness=2h" in cmd_string
    assert "--project=paralax-prod" in cmd_string
    assert "--limit=50" in cmd_string
    assert "--format=json" in cmd_string




def test_build_gcloud_logging_command_with_absolute_time_range() -> None:
    """Business Rule: Consulta com intervalo absoluto deve combinar start e end."""
    cloud_config = {
        "project_id": "paralax-prod",
        "kubernetes": {
            "cluster_name": "prod-gke-cluster",
            "namespace": "production",
        },
    }

    cmd = build_gcloud_logging_command(
        cloud_config=cloud_config,
        container_name="evolution-api",
        severity="WARNING",
        start_time="2026-10-24T08:00:00Z",
        end_time="2026-10-24T08:30:00Z",
        custom_filter='textPayload:"reconnect"',
    )

    cmd_string = " ".join(cmd)
    time_clause = (
        'timestamp >= "2026-10-24T08:00:00Z" AND timestamp <= "2026-10-24T08:30:00Z"'
    )
    assert time_clause in cmd_string
    assert '(textPayload:"reconnect")' in cmd_string
    assert "severity>=WARNING" in cmd_string




def test_resolve_most_probable_spoke_exact_and_substring() -> None:
    """Business Rule: Normalizar correspondências exatas e parciais de spokes."""
    repos = [
        {"name": "customer-support-vehicles", "role": "ai-agent"},
        {"name": "google-calendar-agent", "role": "ai-agent"},
        {"name": "paralax-evo-crm", "role": "sdk"},
    ]
    assert (
        resolve_most_probable_spoke("customer-support-vehicles", repos)
        == "customer-support-vehicles"
    )
    assert (
        resolve_most_probable_spoke("paralax-ia/google-calendar-agent", repos)
        == "google-calendar-agent"
    )
    assert resolve_most_probable_spoke("vehicles", repos) == "customer-support-vehicles"
    assert resolve_most_probable_spoke("unknown", repos) == "unknown"




def test_infer_spoke_from_prompt_heuristic() -> None:
    """Business Rule: Inferir spoke por palavras-chave do domínio de negócio."""
    repos = [
        {"name": "customer-support-vehicles", "role": "ai-agent"},
        {"name": "google-calendar-agent", "role": "ai-agent"},
    ]
    prompt_cars = "erro na busca de carros do agente de veículos"
    assert (
        infer_spoke_from_prompt_heuristic(prompt_cars, repos)
        == "customer-support-vehicles"
    )

    prompt_agenda = "falha ao sincronizar agenda médica do doutor"
    assert (
        infer_spoke_from_prompt_heuristic(prompt_agenda, repos)
        == "google-calendar-agent"
    )

    prompt_generic = "erro genérico sem palavras chave conhecidas"
    assert infer_spoke_from_prompt_heuristic(prompt_generic, repos) == "unknown"




def test_load_bug_plan_target_from_file(tmp_path: Path) -> None:
    """Business Rule: Deve carregar o BugPlan a partir de arquivo explícito."""
    plan = BugPlan(
        title="[Bug] Erro no Checkout",
        summary="Falha no processamento de pagamento",
        observed_behavior="Erro 500",
        expected_behavior="Status 200",
        affected_spoke="evo-ai-crm-community",
        affected_capability="billing",
        runtime_contract="BillingService.charge",
    )
    md_file = tmp_path / "meu_bug.md"
    md_file.write_text(compile_bug_issue_markdown(plan), encoding="utf-8")

    loaded_plan, loaded_path = load_bug_plan_target(
        target=str(md_file), workspace_root=tmp_path
    )
    assert loaded_plan.title == "[Bug] Erro no Checkout"
    assert loaded_plan.affected_spoke == "evo-ai-crm-community"
    assert loaded_path == md_file




def test_load_bug_plan_target_default_bug_issue(tmp_path: Path) -> None:
    """Business Rule: Deve carregar bug_issue.md por padrão na ausência de alvo."""
    plan = BugPlan(
        title="[Bug] Falha Padrão",
        summary="Erro padrão detectado",
        observed_behavior="Timeout",
        expected_behavior="Resposta rápida",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="VehicleSearch.find",
    )
    default_file = tmp_path / "bug_issue.md"
    default_file.write_text(compile_bug_issue_markdown(plan), encoding="utf-8")

    loaded_plan, loaded_path = load_bug_plan_target(
        target=None, workspace_root=tmp_path
    )
    assert loaded_plan.title == "[Bug] Falha Padrão"
    assert loaded_path == default_file




def test_load_bug_plan_target_not_found_raises(tmp_path: Path) -> None:
    """Business Rule: Deve lançar FileNotFoundError se nenhum plano for localizado."""
    with pytest.raises(FileNotFoundError, match="Nenhum plano de defeito encontrado"):
        load_bug_plan_target(target=None, workspace_root=tmp_path)




def test_resolve_spoke_directory(tmp_path: Path) -> None:
    """Business Rule: Deve resolver o diretório do spoke correto no workspace."""
    spoke_dir = tmp_path / "customer-support-vehicles"
    spoke_dir.mkdir()

    resolved = resolve_spoke_directory(
        affected_spoke="customer-support-vehicles",
        workspace_root=tmp_path,
    )
    assert resolved == spoke_dir

    unknown_resolved = resolve_spoke_directory(
        affected_spoke="unknown",
        workspace_root=tmp_path,
    )
    assert unknown_resolved == tmp_path




def test_build_bug_fix_prompt() -> None:
    """Business Rule: Prompt de fix deve conter metadados e restrições obrigatórias."""
    plan = BugPlan(
        title="[Bug] Erro na busca de carros",
        summary="Busca por marca falha com 500",
        observed_behavior="HTTP 500 retornado",
        expected_behavior="Lista de veículos retornada",
        affected_spoke="customer-support-vehicles",
        affected_capability="vehicles_search",
        runtime_contract="VehicleCatalog.search",
        business_rule="Busca de veículos deve retornar lista vazia se nada achado.",
        test_function_name="test_search_cars_by_brand",
    )
    prompt = build_bug_fix_prompt(plan, "tests/unit/test_cars.py")
    assert "Task: Solução do Defeito TDD" in prompt
    assert "tests/unit/test_cars.py" in prompt
    assert "test_search_cars_by_brand" in prompt
    assert "NUNCA defina funções aninhadas" in prompt
    assert "Busca de veículos deve retornar lista vazia" in prompt




def test_build_bug_fix_prompt_requires_rca_deliverable_and_issue_link() -> None:
    """Business Rule: Prompt de fix exige RCA Ishikawa/5 Whys e vínculo da issue.

    O agente deve entregar o Ishikawa (6 categorias) e os 5 Porquês no corpo do
    PR e referenciar `Fixes #N`, para que a esteira post-merge identifique a
    issue.
    """
    plan = BugPlan(
        title="[Bug] Modelo inválido",
        summary="404",
        observed_behavior="Err",
        expected_behavior="Ok",
        affected_spoke="customer-support-vehicles",
        affected_capability="config",
        runtime_contract="Config",
        issue_id=51,
    )
    prompt = build_bug_fix_prompt(plan, "tests/unit/test_config.py")
    for category in (
        "Método",
        "Máquina/Ambiente",
        "Mão de Obra/Agente",
        "Material/Dependências",
        "Medição/Testes",
        "Meio Ambiente",
    ):
        assert category in prompt
    assert "Diagrama de Ishikawa" in prompt
    assert "5 Porquês" in prompt
    assert "Fixes #51" in prompt




def test_agent_runner_retries_on_429() -> None:
    """Business Rule: O runner deve tentar novamente quando ocorrer erro 429."""
    agent = DetectedAgent(
        id="antigravity",
        name="Google Antigravity CLI",
        binary_path="/mock/bin/agy",
        description="Agente mock",
    )
    res_429 = MagicMock(
        returncode=3,
        stdout="error: RESOURCE_EXHAUSTED (code 429): quota exceeded",
        stderr="",
    )
    res_success = MagicMock(
        returncode=0,
        stdout="Concluído com sucesso",
        stderr="",
    )
    mock_sub = MagicMock(side_effect=[res_429, res_success])

    with patch("time.sleep") as mock_sleep:
        runner = AgentRunner(subprocess_runner=mock_sub)
        code, out = runner.run_prompt(
            agent=agent,
            working_dir=Path("/tmp"),
            prompt_text="fix bug",
        )
        assert code == 0
        assert out == "Concluído com sucesso"
        assert mock_sub.call_count == 2
        assert mock_sleep.call_count == 1




def test_resolve_github_repo_for_spoke() -> None:
    """Business Rule: Deve resolver o repo completo org/repo a partir do manifesto."""
    manifest_repos = [
        {
            "name": "customer-support-vehicles",
            "repo": "paralax-ia/customer-support-vehicles",
        },
        {"name": "paralax-evo-crm", "repo": "paralax-ia/paralax-evo-crm"},
    ]
    assert (
        resolve_github_repo_for_spoke("customer-support-vehicles", manifest_repos)
        == "paralax-ia/customer-support-vehicles"
    )
    assert (
        resolve_github_repo_for_spoke("meu-spoke", default_org="paralax-ia")
        == "paralax-ia/meu-spoke"
    )
    assert resolve_github_repo_for_spoke("owner/custom-repo") == "owner/custom-repo"




def test_create_github_bug_issue_success() -> None:
    """Business Rule: Invocar gh issue create e extrair número e link da issue."""
    plan = BugPlan(
        title="[Bug] Erro 500 no login",
        summary="Timeout de autenticação",
        observed_behavior="500",
        expected_behavior="200",
        affected_spoke="evo-crm",
        affected_capability="auth",
        runtime_contract="Auth.login",
    )
    mock_proc = MagicMock(
        returncode=0,
        stdout="https://github.com/paralax-ia/evo-crm/issues/42\n",
    )
    with patch("harness_state.bug.subprocess.run", return_value=mock_proc):
        num, url = create_github_bug_issue(
            plan=plan,
            markdown_body="## Descrição",
            target_repo="paralax-ia/evo-crm",
            ready=True,
        )
        assert num == 42
        assert url == "https://github.com/paralax-ia/evo-crm/issues/42"
        assert plan.issue_id == 42




def test_update_github_bug_issue() -> None:
    """Business Rule: Deve atualizar o título e o corpo da issue via gh issue edit."""
    plan = BugPlan(
        title="[Bug] Título Atualizado",
        summary="Resumo atualizado",
        observed_behavior="500",
        expected_behavior="200",
        affected_spoke="evo-crm",
        affected_capability="auth",
        runtime_contract="Auth.login",
    )
    mock_proc = MagicMock(returncode=0, stdout="", stderr="")
    with patch("harness_state.bug.subprocess.run", return_value=mock_proc) as mock_run:
        success = update_github_bug_issue(
            issue_id=42,
            plan=plan,
            markdown_body="## Corpo Refinado",
            target_repo="paralax-ia/evo-crm",
        )
        assert success is True
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd and "edit" in cmd
        assert "42" in cmd
        assert "--title" in cmd
        assert "[Bug] Título Atualizado" in cmd




def test_refine_bug_plan_with_llm() -> None:
    """Business Rule: Refinamento com LLM deve incorporar as orientações do usuário."""
    initial_plan = BugPlan(
        title="[Bug] Erro na busca de carros",
        summary="Busca falha",
        observed_behavior="500",
        expected_behavior="Lista de carros",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.find",
        issue_id=77,
    )
    fake_refined_data = {
        "title": "[Bug] Erro 500 na busca de carros por ano e marca",
        "summary": "Filtro por ano e marca dispara NullPointerException.",
        "observed_behavior": "Erro 500 no endpoint /vehicles/search.",
        "expected_behavior": "Retorna HTTP 200 com array de veículos.",
        "affected_spoke": "customer-support-vehicles",
        "affected_capability": "search",
        "runtime_contract": "VehicleCatalog.search",
        "reproduction_steps": ["1. Buscar por marca Ford", "2. Filtrar por 2024"],
        "test_file_path": "tests/unit/test_search.py",
        "test_function_name": "test_search_by_year",
        "business_rule": "Filtros válidos devem retornar registros correspondentes.",
    }
    with patch("harness_state.bug.call_llm_json_completion", return_value=fake_refined_data):
        refined = refine_bug_plan_with_llm(
            current_plan=initial_plan,
            refinement_instruction="adicionar filtro por ano e marca",
            stream=False,
        )
        assert refined.title == "[Bug] Erro 500 na busca de carros por ano e marca"
        assert "NullPointerException" in refined.summary
        assert refined.issue_id == 77




def test_resolve_container_name_for_spoke() -> None:
    """Business Rule: O resolvedor deve mapear spokes para containers do GKE."""
    assert (
        resolve_container_name_for_spoke("customer-support-vehicles")
        == "prod-customer-support-v2-vehicles"
    )
    assert (
        resolve_container_name_for_spoke("google-calendar-agent")
        == "prod-paralax-calendar"
    )
    assert resolve_container_name_for_spoke("custom-app") == "custom-app"




def test_compile_bug_issue_markdown_prevents_duplicate_business_rule() -> None:
    """Business Rule: O Markdown gerado não deve duplicar o prefixo Business Rule."""
    plan = BugPlan(
        title="[Bug] Timeout na busca",
        summary="A busca está tomando timeout sem retornar.",
        observed_behavior="Timeout na requisição",
        expected_behavior="Resposta rápida",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.find",
        test_file_path="tests/unit/test_search.py",
        test_function_name="test_search",
        business_rule=(
            "Business Rule: A busca deve retornar veículos dentro do timeout."
        ),
    )
    md = compile_bug_issue_markdown(plan)
    expected_docstring = (
        '"""Business Rule: A busca deve retornar veículos dentro do timeout."""'
    )
    assert '"""Business Rule: Business Rule:' not in md
    assert expected_docstring in md




def test_resolve_flow_containers_for_spoke() -> None:
    """Business Rule: O fluxo de qualquer agente deve incluir o evo-bot-runtime."""
    containers = resolve_flow_containers_for_spoke("customer-support-vehicles")
    assert "prod-customer-support-v2-vehicles" in containers
    assert "evo-bot-runtime" in containers




def test_interactive_fetch_cloud_logs_auto_found() -> None:
    """Business Rule: Busca no fluxo roda sem perguntas se encontrar logs."""
    fake_json = (
        '[{"timestamp": "2026-10-24T14:00:00Z", '
        '"textPayload": "Timeout no runtime do bot"}]'
    )
    mock_proc = MagicMock(returncode=0, stdout=fake_json, stderr="")

    with patch("harness_state.bug.subprocess.run", return_value=mock_proc):
        # Nenhuma pergunta deve ser feita se o log for encontrado direto
        res = interactive_fetch_cloud_logs(
            spoke="customer-support-vehicles",
            prompt_fn=lambda _: pytest.fail("Nenhuma pergunta deveria ser feita"),
        )
        assert res == fake_json




def test_interactive_fetch_cloud_logs_needs_more_info_and_llm_mapping() -> None:
    """Business Rule: Se nada for achado, pede info e remapeia via LLM."""
    empty_proc = MagicMock(returncode=0, stdout="[]", stderr="")
    found_json = (
        '[{"timestamp": "2026-10-24T14:30:00Z", "textPayload": "Erro 500 no evo-crm"}]'
    )
    success_proc = MagicMock(returncode=0, stdout=found_json, stderr="")

    responses = ["aconteceu por volta das 14h30 envolvendo o evo-crm"]
    mock_llm_data = {
        "containers": [
            "prod-customer-support-v2-vehicles",
            "evo-bot-runtime",
            "evo-crm",
        ],
        "since": "2h",
        "start_time": "2026-10-24T14:20:00Z",
        "end_time": "2026-10-24T14:40:00Z",
        "severity": "ERROR",
        "custom_filter": None,
    }

    with (
        patch("harness_state.bug.subprocess.run", side_effect=[empty_proc, success_proc]),
        patch("harness_state.bug.call_llm_json_completion", return_value=mock_llm_data),
    ):
        res = interactive_fetch_cloud_logs(
            spoke="customer-support-vehicles",
            prompt_fn=lambda _: responses.pop(0),
        )
        assert res == found_json




def test_extract_log_query_context_with_llm_fallback() -> None:
    """Business Rule: Fallback determinístico deve identificar evo-crm pelo texto."""
    base = ["prod-customer-support-v2-vehicles", "evo-bot-runtime"]
    with patch("harness_state.bug.call_llm_json_completion", return_value=None):
        ctx = extract_log_query_context_with_llm(
            user_response="deu erro no evo-crm ontem à tarde",
            base_containers=base,
        )
        assert "evo-crm" in ctx["containers"]
        assert ctx["since"] == "6h"




def test_refine_bug_plan_with_llm_incorporates_cloud_log() -> None:
    """Business Rule: O refinamento deve injetar evidências de cloud log e persistir."""
    current_plan = BugPlan(
        title="[Bug] Timeout na busca",
        summary="Timeout observado",
        observed_behavior="Sem retorno",
        expected_behavior="Retorno rápido",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.find",
        test_file_path="tests/unit/test_search.py",
        test_function_name="test_search",
        business_rule="Busca com timeout controlado.",
        selected_cloud_log=None,
    )
    fake_log = '{"error": "504 Gateway Timeout"}'

    with patch("harness_state.bug.call_llm_json_completion", return_value=None):
        refined = refine_bug_plan_with_llm(
            current_plan=current_plan,
            refinement_instruction="adicionar timeout de 5 segundos",
            cloud_log=fake_log,
            agent=None,
        )
        assert refined.selected_cloud_log == fake_log




def test_agent_runner_prompt_file_resolution(tmp_path: Path) -> None:
    """Business Rule: O prompt_file gerado pelo AgentRunner deve ser absoluto."""
    working_dir = tmp_path / "customer-support-vehicles"
    working_dir.mkdir(parents=True, exist_ok=True)

    agent = DetectedAgent(
        id="aider",
        name="Aider",
        binary_path="aider",
        description="Aider CLI",
    )
    runner = AgentRunner()
    mock_proc = MagicMock(returncode=0, stdout="OK", stderr="")
    mock_subproc = MagicMock(return_value=mock_proc)
    runner.subprocess_runner = mock_subproc

    runner.run_prompt(
        agent=agent,
        working_dir=working_dir,
        prompt_text="corrigir defeito de timeout",
        task_label="correção",
    )

    assert mock_subproc.call_count == 1
    called_cmd = mock_subproc.call_args[0][0]
    msg_file_idx = called_cmd.index("--message-file")
    resolved_path = Path(called_cmd[msg_file_idx + 1])
    assert resolved_path.is_absolute()
    assert resolved_path.name == "current_task_prompt.md"
    assert resolved_path.is_file()




def test_agent_runner_continue_session_flags(tmp_path: Path) -> None:
    """Business Rule: continue_session ativa flags de retomada específicas."""
    runner = AgentRunner()
    mock_proc = MagicMock(returncode=0, stdout="OK", stderr="")
    mock_subproc = MagicMock(return_value=mock_proc)
    runner.subprocess_runner = mock_subproc

    agy_agent = DetectedAgent(
        id="antigravity",
        name="Google Antigravity CLI",
        binary_path="/usr/local/bin/agy",
        description="agy",
        default_model="gemini-3.8-flash-high",
    )
    runner.run_prompt(
        agent=agy_agent,
        working_dir=tmp_path,
        prompt_text="teste",
        continue_session=True,
    )
    called_cmd = mock_subproc.call_args[0][0]
    assert "--continue" in called_cmd
    assert "--model" in called_cmd

    aider_agent = DetectedAgent(
        id="aider",
        name="Aider",
        binary_path="aider",
        description="aider",
    )
    runner.run_prompt(
        agent=aider_agent,
        working_dir=tmp_path,
        prompt_text="teste",
        continue_session=True,
    )
    aider_cmd = mock_subproc.call_args[0][0]
    assert "--restore-chat-history" in aider_cmd
    assert "--no-show-model-warnings" in aider_cmd




def test_record_bug_state_in_redis_persists_payload() -> None:
    """Business Rule: O estado transacional do defeito deve ser salvo no Redis."""
    plan = BugPlan(
        title="[Bug] Timeout na busca",
        summary="Timeout ao buscar",
        observed_behavior="Timeout",
        expected_behavior="Lista de carros",
        affected_spoke="customer-support-vehicles",
        affected_capability="vehicle_search",
        runtime_contract="VehicleSearch.find",
        test_file_path="tests/unit/test_search.py",
        test_function_name="test_search",
        business_rule="Busca deve responder dentro do SLA.",
        issue_id=24,
    )
    mock_client = MagicMock()
    with patch("harness_state.bug.redis.Redis", return_value=mock_client):
        ok = record_bug_state_in_redis(
            plan=plan,
            stage="RESOLVED",
            pr_number=38,
            pr_url="https://github.com/paralax-ia/customer-support-vehicles/pull/38",
        )
        assert ok is True
        assert mock_client.set.call_count == 1
        call_key = mock_client.set.call_args[0][0]
        assert call_key == "bug:customer-support-vehicles:24"
        call_val = mock_client.set.call_args[0][1]
        assert '"stage": "RESOLVED"' in call_val
        assert '"pr_number": 38' in call_val
        assert mock_client.sadd.call_count == 1
        assert mock_client.sadd.call_args[0][0] == "bugs:active"




def test_record_bug_state_in_redis_closed_stage_archives() -> None:
    """Business Rule: No estado CLOSED o bug deve ser removido de active e arquivado."""
    plan = BugPlan(
        title="[Bug] Timeout na busca",
        summary="Timeout ao buscar",
        observed_behavior="Timeout",
        expected_behavior="Lista de carros",
        affected_spoke="customer-support-vehicles",
        affected_capability="vehicle_search",
        runtime_contract="VehicleSearch.find",
        test_file_path="tests/unit/test_search.py",
        test_function_name="test_search",
        business_rule="Busca deve responder dentro do SLA.",
        issue_id=24,
    )
    mock_client = MagicMock()
    with patch("harness_state.bug.redis.Redis", return_value=mock_client):
        ok = record_bug_state_in_redis(
            plan=plan,
            stage="CLOSED",
            pr_number=38,
        )
        assert ok is True
        mock_client.srem.assert_called_once_with(
            "bugs:active", "bug:customer-support-vehicles:24"
        )
        mock_client.sadd.assert_called_once_with(
            "bugs:archived", "bug:customer-support-vehicles:24"
        )




def test_send_bug_telemetry_to_es_posts_json() -> None:
    """Business Rule: Telemetria do bugfix deve ser enviada ao Elasticsearch."""
    plan = BugPlan(
        title="[Bug] Timeout",
        summary="Timeout",
        observed_behavior="Err",
        expected_behavior="Ok",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.find",
        issue_id=24,
    )
    mock_resp = MagicMock(status=201)
    mock_resp.__enter__.return_value = mock_resp
    with patch(
        "harness_state.bug.urllib.request.urlopen", return_value=mock_resp
    ) as mock_open:
        ok = send_bug_telemetry_to_es(
            plan=plan,
            stage="RESOLVED",
            pr_number=38,
            pr_url="https://github.com/paralax-ia/customer-support-vehicles/pull/38",
            test_passed=True,
        )
        assert ok is True
        assert mock_open.call_count == 1
        req = mock_open.call_args[0][0]
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["stage"] == "RESOLVED"
        assert payload["issue_id"] == 24
        assert payload["event_type"] == "bug_lifecycle"




def test_publish_bug_pr_detects_existing_pr(tmp_path: Path) -> None:
    """Business Rule: publish_bug_pr detecta PR existente se já aberto pelo agente."""
    plan = BugPlan(
        title="[Bug] Timeout na busca",
        summary="Timeout",
        observed_behavior="Err",
        expected_behavior="Ok",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.find",
        issue_id=24,
    )
    mock_branch = MagicMock(returncode=0, stdout="fix/vehicle-search-timeout\n")
    mock_status = MagicMock(returncode=0, stdout="")
    mock_push = MagicMock(returncode=0, stdout="Everything up-to-date\n")
    view_json = (
        '{"number": 38, "url": "https://github.com/paralax-ia/'
        'customer-support-vehicles/pull/38", "body": "Fixes #24"}'
    )
    mock_view = MagicMock(returncode=0, stdout=view_json)

    with patch(
        "harness_state.bug.subprocess.run",
        side_effect=[mock_branch, mock_status, mock_push, mock_view],
    ):
        num, url, msg = publish_bug_pr(repo_dir=tmp_path, plan=plan)
        assert num == 38
        assert "pull/38" in (url or "")
        assert "já ativo" in msg




def test_publish_bug_pr_links_issue_on_existing_pr_without_reference(
    tmp_path: Path,
) -> None:
    """Business Rule: PR pré-aberto pelo agente sem `Fixes #N` deve ser vinculado.

    Sem a referência, o workflow bug-post-merge não identifica a issue e o
    fechamento transacional (ondas topológicas) nunca é disparado.
    """
    plan = BugPlan(
        title="[Bug] Modelo inválido",
        summary="404",
        observed_behavior="Err",
        expected_behavior="Ok",
        affected_spoke="customer-support-vehicles",
        affected_capability="config",
        runtime_contract="Config",
        issue_id=51,
    )
    mock_branch = MagicMock(returncode=0, stdout="fix/agent-model-validation\n")
    mock_status = MagicMock(returncode=0, stdout="")
    mock_push = MagicMock(returncode=0, stdout="")
    view_json = json.dumps(
        {"number": 53, "url": "https://github.com/o/r/pull/53", "body": "## RCA"}
    )
    mock_view = MagicMock(returncode=0, stdout=view_json)
    mock_edit = MagicMock(returncode=0, stdout="")

    with patch(
        "harness_state.bug.subprocess.run",
        side_effect=[mock_branch, mock_status, mock_push, mock_view, mock_edit],
    ) as mock_run:
        num, _, _ = publish_bug_pr(repo_dir=tmp_path, plan=plan)

    assert num == 53
    edit_cmd = mock_run.call_args_list[-1][0][0]
    assert edit_cmd[:4] == ["gh", "pr", "edit", "53"]
    new_body = edit_cmd[edit_cmd.index("--body") + 1]
    assert "## RCA" in new_body
    assert "Fixes #51" in new_body




def test_merge_bug_pr_and_close_issue(tmp_path: Path) -> None:
    """Business Rule: merge_bug_pr mescla PR, fecha Issue e atualiza Redis e ES."""
    plan = BugPlan(
        title="[Bug] Timeout",
        summary="Timeout",
        observed_behavior="Err",
        expected_behavior="Ok",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.find",
        issue_id=24,
    )
    mock_merge = MagicMock(returncode=0, stdout="Merged")
    mock_close = MagicMock(returncode=0, stdout="Closed")

    with (
        patch("harness_state.bug.subprocess.run", side_effect=[mock_merge, mock_close]),
        patch(
            "harness_state.bug.record_bug_state_in_redis", return_value=True
        ) as mock_redis,
        patch("harness_state.bug.send_bug_telemetry_to_es", return_value=True) as mock_es,
    ):
        ok, msg = merge_bug_pr_and_close_issue(
            repo_dir=tmp_path, plan=plan, pr_number=38
        )
        assert ok is True
        assert "mesclado" in msg
        assert mock_redis.call_args[1]["stage"] == "CLOSED"
        assert mock_es.call_args[1]["stage"] == "CLOSED"




def test_update_github_issue_status_label() -> None:
    """Business Rule: Atualização de status da Issue invoca gh issue edit com labels."""
    plan = BugPlan(
        title="[Bug] Erro",
        summary="Falha",
        observed_behavior="X",
        expected_behavior="Y",
        affected_spoke="customer-support-vehicles",
        affected_capability="catalog",
        runtime_contract="X.y",
        issue_id=24,
    )
    mock_proc = MagicMock(returncode=0)
    with patch("harness_state.bug.subprocess.run", return_value=mock_proc) as mock_sub:
        ok = update_github_issue_status_label(
            plan=plan,
            new_status="resolved",
            remove_status="fixing",
        )
        assert ok is True
        cmd = mock_sub.call_args[0][0]
        assert "status:bug/resolved" in cmd
        assert "--remove-label" in cmd
        assert "status:bug/fixing" in cmd




def test_update_github_issue_status_label_with_target_repo() -> None:
    """Business Rule: Atualização de label da Issue deve aceitar target_repo."""
    plan = BugPlan(
        title="[Bug] Erro",
        summary="Falha",
        observed_behavior="X",
        expected_behavior="Y",
        affected_spoke="customer-support-vehicles",
        affected_capability="catalog",
        runtime_contract="X.y",
        issue_id=45,
    )
    mock_proc = MagicMock(returncode=0)
    with patch("harness_state.bug.subprocess.run", return_value=mock_proc) as mock_sub:
        ok = update_github_issue_status_label(
            plan=plan,
            new_status="closed",
            remove_status="resolved",
            target_repo="paralax-ia/customer-support-vehicles",
        )
        assert ok is True
        cmd = mock_sub.call_args[0][0]
        assert "--repo" in cmd
        assert "paralax-ia/customer-support-vehicles" in cmd
        assert "status:bug/closed" in cmd
        assert "--remove-label" in cmd
        assert "status:bug/resolved" in cmd




def test_load_bug_plan_target_with_explicit_repo() -> None:
    """Business Rule: Deve buscar issue no GitHub usando repo explícito."""
    plan_body = """<!-- flywheel:bug-plan:v1 -->
# [Bug] Erro em prompts

## 📋 Sumário Executivo do Defeito
Falha ao validar prompts

## 🎯 Fronteiras Arquiteturais & Capacidades DDD Afetadas
- **Spoke Afetado:** `customer-support-vehicles`
- **Business Capability:** `vehicles`
- **Runtime Contract:** `VehicleSearch`
- **Prompts Governados:** `vehicles_system_prompt`
"""
    mock_proc = MagicMock(returncode=0, stdout=plan_body)
    with patch("harness_state.bug.subprocess.run", return_value=mock_proc) as mock_sub:
        plan, _ = load_bug_plan_target(
            target="45",
            repo="paralax-ia/customer-support-vehicles",
        )
        assert plan.issue_id == 45
        assert "vehicles_system_prompt" in plan.prompts
        cmd = mock_sub.call_args[0][0]
        assert "--repo" in cmd
        assert "paralax-ia/customer-support-vehicles" in cmd




def test_record_bug_state_in_redis_retries_on_timeout() -> None:
    """Business Rule: Deve retentar persistência no Redis em caso de falha."""
    plan = BugPlan(
        title="[Bug] Erro",
        summary="Falha",
        observed_behavior="X",
        expected_behavior="Y",
        affected_spoke="customer-support-vehicles",
        affected_capability="catalog",
        runtime_contract="X.y",
        issue_id=45,
    )
    mock_redis_factory = FlakyRedisFactory(failures=2)

    with (
        patch("harness_state.bug.redis.Redis", side_effect=mock_redis_factory),
        patch("harness_state.bug.time.sleep") as mock_sleep,
    ):
        success = record_bug_state_in_redis(plan, stage="CLOSED", max_retries=3)
        assert success is True
        assert mock_redis_factory.attempts == 3
        assert mock_sleep.call_count == 2




def test_elicit_bug_plan_with_agent_starts_new_session() -> None:
    """Business Rule: Novos bugs sem ID prévio desativam continue_session."""
    fake_agent = DetectedAgent(
        id="antigravity",
        name="Google Antigravity CLI",
        binary_path="/usr/local/bin/agy",
        description="agy",
    )
    with patch("harness_state.bug.AgentRunner.run_prompt") as mock_run_prompt:
        mock_run_prompt.return_value = (
            0,
            json.dumps(
                {
                    "title": "[Bug] Nova falha",
                    "summary": "Resumo",
                    "observed_behavior": "Obs",
                    "expected_behavior": "Exp",
                    "affected_spoke": "customer-support-vehicles",
                    "affected_capability": "catalog",
                    "runtime_contract": "C.m",
                    "reproduction_steps": ["step 1"],
                    "test_file_path": "tests/test.py",
                    "test_function_name": "test_f",
                    "business_rule": "Rule",
                }
            ),
        )
        plan = elicit_bug_plan_with_llm(
            prompt="Nova falha detectada",
            agent=fake_agent,
            stream=False,
        )
        assert plan.title == "[Bug] Nova falha"
        assert mock_run_prompt.call_count == 1
        assert mock_run_prompt.call_args[1]["continue_session"] is False




def test_ensure_state_backends_available_reports_both_failures() -> None:
    """Business Rule: O bug flow não prossegue sem Redis e Elasticsearch.

    A falha deve nomear explicitamente cada backend indisponível, em vez de
    degradar silenciosamente para um aviso em stderr.
    """
    with (
        patch("harness_state.bug.redis.Redis") as mock_redis,
        patch(
            "harness_state.bug.urllib.request.urlopen",
            side_effect=OSError("connection refused"),
        ),
    ):
        mock_redis.return_value.ping.side_effect = ConnectionError("refused")
        with pytest.raises(StateBackendUnavailableError) as exc_info:
            ensure_state_backends_available()

    message = str(exc_info.value)
    assert "Redis" in message
    assert "Elasticsearch" in message




def test_ensure_state_backends_available_passes_when_both_reachable() -> None:
    """Business Rule: Com Redis e Elasticsearch acessíveis o fluxo prossegue."""
    mock_resp = MagicMock(status=200)
    mock_resp.__enter__.return_value = mock_resp
    with (
        patch("harness_state.bug.redis.Redis") as mock_redis,
        patch("harness_state.bug.urllib.request.urlopen", return_value=mock_resp),
    ):
        mock_redis.return_value.ping.return_value = True
        ensure_state_backends_available()




def test_build_bug_feedback_prompt() -> None:
    """Business Rule: Prompt de feedback traz diagnóstico das falhas."""
    plan = BugPlan(
        title="[Bug] Falha",
        summary="Erro",
        observed_behavior="X",
        expected_behavior="Y",
        affected_spoke="customer-support-vehicles",
        affected_capability="core",
        runtime_contract="Contract.execute",
        business_rule="Regra de ouro.",
        test_file_path="tests/unit/test_repro.py",
        test_function_name="test_err",
        issue_id=55,
    )
    prompt = build_bug_feedback_prompt(
        plan=plan,
        test_file_path="tests/unit/test_repro.py",
        feedback="AssertionError: assert 1 == 2",
        iteration=2,
        max_iterations=5,
    )
    assert "(2/5)" in prompt
    assert "AssertionError: assert 1 == 2" in prompt
    assert "customer-support-vehicles" in prompt
    assert "issue `55`" in prompt




def test_pull_prompts_from_langfuse_ssot_empty_target_prompts_does_not_pull(
    tmp_path: Path,
) -> None:
    """Business Rule: target_prompts vazio não puxa nenhum prompt do SSOT."""
    from harness_state.sensors.prompt_sensor import pull_prompts_from_langfuse_ssot

    mock_mgr = MagicMock(is_configured=True)
    pulled = pull_prompts_from_langfuse_ssot(
        project_root=tmp_path,
        prompt_manager=mock_mgr,
        target_prompts=[],
    )
    assert pulled == []
    mock_mgr.fetch_prompt.assert_not_called()




def test_bug_plan_topological_waves_and_origin_spoke_serialization() -> None:
    """Business Rule: BugPlan serializa spoke originário, onda e dependências."""
    plan = BugPlan(
        title="[Bug] Falha no cálculo de frete",
        summary="Erro ao calcular rota",
        observed_behavior="Erro 500",
        expected_behavior="Retorno 200",
        affected_spoke="paralax-evo-crm",
        affected_capability="routing",
        runtime_contract="Router.calculate",
        origin_spoke="customer-support-vehicles",
        wave=2,
        depends_on=["paralax-evo-crm", "paralax-agents-common"],
    )
    md = compile_bug_issue_markdown(plan)
    assert "- **Spoke Afetado:** `paralax-evo-crm`" in md
    assert "- **Spoke Originário:** `customer-support-vehicles`" in md
    assert "- **Onda Topológica:** `Wave 2`" in md
    assert "- **Depende de:** `paralax-evo-crm`, `paralax-agents-common`" in md

    parsed = parse_bug_issue_markdown(md)
    assert parsed.affected_spoke == "paralax-evo-crm"
    assert parsed.origin_spoke == "customer-support-vehicles"
    assert parsed.wave == 2
    assert parsed.depends_on == ["paralax-evo-crm", "paralax-agents-common"]




def test_publish_bug_pr_creates_agent_branch_prefix(tmp_path: Path) -> None:
    """Business Rule: PRs gerados por IA devem usar prefixo agent/ para auto-release."""
    plan = BugPlan(
        title="[Bug] Timeout na sincronização",
        summary="Sincronização expira",
        observed_behavior="Timeout",
        expected_behavior="Sucesso",
        affected_spoke="paralax-evo-crm",
        affected_capability="crm",
        runtime_contract="Sync.run",
        issue_id=42,
    )
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    branch_proc = MagicMock(returncode=0, stdout="main\n", stderr="")
    checkout_proc = MagicMock(returncode=0, stdout="", stderr="")
    status_proc = MagicMock(returncode=0, stdout=" M file.py\n", stderr="")
    add_proc = MagicMock(returncode=0, stdout="", stderr="")
    commit_proc = MagicMock(returncode=0, stdout="", stderr="")
    push_proc = MagicMock(returncode=0, stdout="", stderr="")
    view_proc = MagicMock(returncode=1, stdout="", stderr="")
    create_proc = MagicMock(
        returncode=0,
        stdout="https://github.com/paralax-ia/paralax-evo-crm/pull/101\n",
        stderr="",
    )

    with patch(
        "harness_state.bug.subprocess.run",
        side_effect=[
            branch_proc,
            checkout_proc,
            status_proc,
            add_proc,
            commit_proc,
            push_proc,
            view_proc,
            create_proc,
        ],
    ) as mock_subproc:
        pr_num, pr_url, _ = publish_bug_pr(repo_dir, plan)

        checkout_call = mock_subproc.call_args_list[1]
        checkout_cmd = checkout_call[0][0]
        assert checkout_cmd[0:3] == ["git", "checkout", "-b"]
        branch_name = checkout_cmd[3]
        assert branch_name.startswith("agent/bug-issue-42-")
        assert pr_num == 101
        assert pr_url == "https://github.com/paralax-ia/paralax-evo-crm/pull/101"




def test_resolve_spoke_wave_and_dependencies_from_manifest(tmp_path: Path) -> None:
    """Business Rule: Ondas e dependências lidas de manifest.yaml sem gravar spec."""
    manifest_content = """version: "1.0"
repositories:
  - name: "paralax-agents-common"
    repo: "paralax-ia/paralax-agents-common"
    depends_on: []
  - name: "paralax-evo-crm"
    repo: "paralax-ia/paralax-evo-crm"
    depends_on:
      - "paralax-agents-common"
  - name: "customer-support-vehicles"
    repo: "paralax-ia/customer-support-vehicles"
    depends_on:
      - "paralax-evo-crm"
      - "paralax-agents-common"
"""
    manifest_file = tmp_path / "manifest.yaml"
    manifest_file.write_text(manifest_content, encoding="utf-8")

    wave_lib, deps_lib = resolve_spoke_wave_and_dependencies(
        "paralax-agents-common", workspace_root=tmp_path
    )
    assert wave_lib == 1
    assert deps_lib == []

    wave_sdk, deps_sdk = resolve_spoke_wave_and_dependencies(
        "paralax-evo-crm", workspace_root=tmp_path
    )
    assert wave_sdk == 2
    assert deps_sdk == ["paralax-agents-common"]

    wave_consumer, deps_consumer = resolve_spoke_wave_and_dependencies(
        "customer-support-vehicles", workspace_root=tmp_path
    )
    assert wave_consumer == 3
    assert deps_consumer == ["paralax-evo-crm", "paralax-agents-common"]




def test_ensure_bug_plan_has_prompts_auto_discovers_for_ai_agent(
    tmp_path: Path,
) -> None:
    """Business Rule: 'ensure_bug_plan_has_prompts' descobre prompts em ai-agent."""
    from harness_state.bug import BugPlan, ensure_bug_plan_has_prompts

    ws = tmp_path / "workspace"
    ws.mkdir()
    spoke_dir = ws / "customer-support-vehicles"
    spoke_dir.mkdir()
    (spoke_dir / "prompts.py").write_text(
        'INSTRUCTION = "Isa instructions"\n', encoding="utf-8"
    )

    manifest = ws / "manifest.yaml"
    manifest.write_text(
        "project: paralax-ia\n"
        "repositories:\n"
        "  - repo: paralax-ia/customer-support-vehicles\n"
        "    role: ai-agent\n",
        encoding="utf-8",
    )

    plan = BugPlan(
        title="[Bug] Erro de busca",
        summary="A agente não responde a termos de busca.",
        observed_behavior="Falha na busca.",
        expected_behavior="Retorno correto dos veículos.",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.run",
    )
    prompts = ensure_bug_plan_has_prompts(
        plan=plan, workspace_root=ws, manifest_path=manifest
    )
    assert len(prompts) >= 1
    assert any("customer_support_vehicles" in p or "vehicles" in p for p in prompts)
    assert plan.prompts == prompts




def test_elicit_bug_plan_with_llm_preserves_and_extracts_prompts() -> None:
    """Business Rule: 'elicit_bug_plan_with_llm' extrai 'prompts' do JSON do modelo."""
    from harness_state.bug import elicit_bug_plan_with_llm

    mock_json = {
        "title": "fix(customer-support-vehicles): erro na instrução de busca",
        "summary": "Falha na instrução da agente Isa ao receber áudio.",
        "observed_behavior": "Ignora o áudio.",
        "expected_behavior": "Interpreta áudio e responde em PT-BR.",
        "affected_spoke": "customer-support-vehicles",
        "affected_capability": "multimodal",
        "runtime_contract": "Agent.run",
        "reproduction_steps": ["1. Enviar áudio."],
        "test_file_path": "tests/unit/test_audio.py",
        "test_function_name": "test_audio_handling",
        "business_rule": "Áudio deve ser convertido e respondido.",
        "prompts": ["vehicles/vehicle_search_agent_instruction"],
    }
    with patch("harness_state.bug.call_llm_json_completion", return_value=mock_json):
        plan = elicit_bug_plan_with_llm(
            prompt="A agente Isa falha ao receber áudio",
            manifest_repos=[{"repo": "customer-support-vehicles", "role": "ai-agent"}],
            agent=None,
        )
    assert plan.prompts == ["vehicles/vehicle_search_agent_instruction"]




def test_refine_bug_plan_with_llm_preserves_existing_prompts() -> None:
    """Business Rule: 'refine_bug_plan_with_llm' preserva prompts existentes."""
    from harness_state.bug import BugPlan, refine_bug_plan_with_llm

    current = BugPlan(
        title="[Bug] Erro no bot",
        summary="Bot falha.",
        observed_behavior="Erro 500",
        expected_behavior="200 OK",
        affected_spoke="customer-support-vehicles",
        affected_capability="search",
        runtime_contract="Search.run",
        prompts=["vehicles/vehicle_search_agent_instruction"],
    )
    mock_json = {
        "title": "fix: ajuste fino",
        "summary": "Sumário refinado",
        "observed_behavior": "Erro observado",
        "expected_behavior": "OK",
        "affected_spoke": "customer-support-vehicles",
        "affected_capability": "search",
        "runtime_contract": "Search.run",
        "reproduction_steps": ["1. Rodar"],
        "test_file_path": "tests/unit/test_search.py",
        "test_function_name": "test_search",
        "business_rule": "Regra formal",
    }
    with patch("harness_state.bug.call_llm_json_completion", return_value=mock_json):
        refined = refine_bug_plan_with_llm(
            current_plan=current,
            refinement_instruction="Adicionar detalhe sobre timeout",
            agent=None,
        )
    assert refined.prompts == ["vehicles/vehicle_search_agent_instruction"]




def test_prompt_sensor_validate_accepts_dict_prompts(tmp_path: Path) -> None:
    """Business Rule: 'PromptGovernanceSensor.validate' suporta metadados."""
    from harness_state.sensors.prompt_sensor import PromptGovernanceSensor

    spoke_dir = tmp_path / "spoke"
    spoke_dir.mkdir()

    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.fetch_prompt.return_value = ("prompt text", 1)

    sensor = PromptGovernanceSensor(project_root=spoke_dir, prompt_manager=mock_mgr)
    with patch.object(sensor, "get_changed_files", return_value=[]):
        violations = sensor.validate(
            declared_prompts=[
                {
                    "name": "vehicles/vehicle_search_agent_instruction",
                    "file": "vehicles/prompts.py",
                    "symbol": "INSTRUCTION",
                }
            ]
        )
    assert len(violations) == 0
    mock_mgr.fetch_prompt.assert_called_once_with(
        "vehicles/vehicle_search_agent_instruction"
    )

