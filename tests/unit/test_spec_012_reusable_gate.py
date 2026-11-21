"""Testes unitários para validação de SPEC-012: Avaliação Canônica de Tags via Workflows Reutilizáveis, Gate Federado e Comandos de Ciclo de Vida."""

from pathlib import Path

import yaml
from click.testing import CliRunner

from harness_state.cli import main
from harness_state.installer import install_module_harness


def test_reusable_tag_evaluation_schema_and_cross_repo_contracts() -> None:
    """Business Rule: reusable-tag-evaluation.yml deve expor inputs cross-repo (tag, target_repo, commit_sha, fast, runs_on), secret token e outputs de veredito."""
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "reusable-tag-evaluation.yml"

    assert workflow_path.is_file(), "reusable-tag-evaluation.yml deve existir em .github/workflows/"
    content = workflow_path.read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)

    on_clause = parsed.get("on") or parsed.get(True, {})
    assert "workflow_call" in on_clause, "Workflow deve ser disparável via workflow_call"
    call_spec = on_clause["workflow_call"]

    inputs = call_spec.get("inputs", {})
    assert "tag" in inputs, "Input 'tag' é obrigatório"
    assert inputs["tag"]["required"] is True
    assert "target_repo" in inputs, "Input 'target_repo' é obrigatório para avaliação cross-repo"
    assert "commit_sha" in inputs, "Input 'commit_sha' é obrigatório para SHA exato do commit"
    assert "fast" in inputs, "Input 'fast' deve estar presente"
    assert "runs_on" in inputs, "Input 'runs_on' deve permitir customização do runner"

    secrets = call_spec.get("secrets", {})
    assert "token" in secrets, "Secret 'token' é necessário para autenticação do target_repo via GitHub App"

    outputs = call_spec.get("outputs", {})
    assert "status" in outputs, "Output 'status' (APPROVED/REJECTED) deve ser exportado"
    assert "compliance_score" in outputs, "Output 'compliance_score' deve ser exportado"

    # Validação do job e steps
    jobs = parsed.get("jobs", {})
    assert "evaluate-tag-release" in jobs, "Job evaluate-tag-release deve existir"
    job = jobs["evaluate-tag-release"]
    assert "runs-on" in job

    # Validações dos passos de checkout cross-repo e status API
    assert "target_repo" in content
    assert "flywheel/tag-gate" in content, "Workflow deve registrar status API com contexto flywheel/tag-gate para target_repo"


def test_test_workflows_contain_ci_deduplication() -> None:
    """Business Rule: reusable-test.yml ou test.yml deve conter verificação de check-runs prévios para evitar retestes na main."""
    repo_root = Path(__file__).resolve().parents[2]
    workflows_dir = repo_root / ".github" / "workflows"

    test_workflow_path = workflows_dir / "test.yml"
    reusable_test_path = workflows_dir / "reusable-test.yml"

    assert reusable_test_path.is_file(), "reusable-test.yml deve existir como workflow reutilizável canônico"
    reusable_content = reusable_test_path.read_text(encoding="utf-8")
    assert "workflow_call" in reusable_content
    assert "check-runs" in reusable_content
    assert "PREV_CHECK" in reusable_content

    test_content = test_workflow_path.read_text(encoding="utf-8")
    assert "check-runs" in test_content, "test.yml deve verificar check-runs prévios no push para main"


def test_catalog_and_installer_inject_tag_gate_workflow(tmp_path: Path) -> None:
    """Business Rule: O catálogo deve incluir template tag-gate.yml e o instalador deve provisioná-lo no spoke."""
    repo_root = Path(__file__).resolve().parents[2]
    tag_gate_template = (
        repo_root
        / "src"
        / "harness_state"
        / "catalog"
        / "pipeline"
        / "common"
        / "tag-gate.yml"
    )
    assert tag_gate_template.is_file(), "Template tag-gate.yml deve existir no catálogo de pipelines"

    content = tag_gate_template.read_text(encoding="utf-8")
    assert "reusable-tag-evaluation.yml" in content, "Template deve invocar reusable-tag-evaluation.yml"

    # Simula instalação em um módulo spoke
    spoke_dir = tmp_path / "mock-spoke"
    spoke_dir.mkdir()
    (spoke_dir / "pyproject.toml").write_text("[project]\nname = 'mock-spoke'\n", encoding="utf-8")

    result = install_module_harness(spoke_dir, force=True)
    installed_tag_gate = spoke_dir / ".github" / "workflows" / "tag-gate.yml"
    assert installed_tag_gate.is_file(), "tag-gate.yml deve ter sido instalado em .github/workflows/"
    assert ".github/workflows/tag-gate.yml" in result.installed_pipeline_files


def test_cli_verify_command_registered_and_functional(tmp_path: Path) -> None:
    """Business Rule: O comando harness verify deve inspecionar conformidade estática local via AST e complexidade."""
    runner = CliRunner()
    result = runner.invoke(main, ["verify", "--help"])
    assert result.exit_code == 0, f"Comando 'harness verify --help' deve funcionar: {result.output}"
    assert "--path" in result.output

    # Executa verificação em diretório vazio (deve passar)
    spoke_dir = tmp_path / "clean-spoke"
    spoke_dir.mkdir()
    run_result = runner.invoke(main, ["verify", "--path", str(spoke_dir)])
    assert run_result.exit_code == 0
    assert "Conformidade" in run_result.output or "✓" in run_result.output


def test_cli_spec_sync_hub_command_registered(tmp_path: Path) -> None:
    """Business Rule: O comando harness spec sync-hub deve reconciliar a sub-spec do spoke com a spec mestre do hub."""
    runner = CliRunner()
    help_result = runner.invoke(main, ["spec", "sync-hub", "--help"])
    assert help_result.exit_code == 0, f"Comando 'harness spec sync-hub --help' deve funcionar: {help_result.output}"
    assert "--repo-spec" in help_result.output
    assert "--hub-spec" in help_result.output

    # Cria mock de sub-spec e hub-spec
    spoke_spec = tmp_path / "spoke-spec.md"
    spoke_spec.write_text(
        "---\nspec_id: SPEC-012\nrepo: eduardosan/harness-state\n---\n\n## 1. Contexto\n\nContexto spoke.\n",
        encoding="utf-8",
    )
    hub_spec = tmp_path / "hub-spec.md"
    hub_spec.write_text(
        "---\nspec_id: SPEC-012\n---\n\n## 1. Contexto\n\nContexto hub.\n",
        encoding="utf-8",
    )

    run_result = runner.invoke(
        main,
        ["spec", "sync-hub", "--repo-spec", str(spoke_spec), "--hub-spec", str(hub_spec)],
    )
    assert run_result.exit_code == 0
    assert "sincronizada" in run_result.output.lower()


def test_cli_map_all_command_registered() -> None:
    """Business Rule: O comando harness map-all deve mapear produtos, capacidades e contratos do ecossistema."""
    runner = CliRunner()
    result = runner.invoke(main, ["map-all", "--help"])
    assert result.exit_code == 0, f"Comando 'harness map-all --help' deve funcionar: {result.output}"
    assert "--spec-hub-dir" in result.output
