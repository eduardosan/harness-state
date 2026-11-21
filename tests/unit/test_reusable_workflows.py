"""Testes unitários para validação dos workflows reutilizáveis e templates justfile (SPEC-009G)."""

from pathlib import Path

import yaml


def test_reusable_workflows_exist_and_are_valid_yaml() -> None:
    """Business Rule: Workflows reutilizáveis em .github/workflows/ devem existir e ter sintaxe YAML válida."""
    repo_root = Path(__file__).resolve().parents[2]
    workflows_dir = repo_root / ".github" / "workflows"

    reusable_workflows = [
        "reusable-spec-ci.yml",
        "reusable-tag-evaluation.yml",
        "reusable-release.yml",
    ]

    for workflow_name in reusable_workflows:
        workflow_path = workflows_dir / workflow_name
        assert workflow_path.is_file(), f"Workflow {workflow_name} não encontrado."

        content = workflow_path.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        assert isinstance(parsed, dict), f"Conteúdo do workflow {workflow_name} inválido."
        assert "name" in parsed
        assert "jobs" in parsed


def test_reusable_spec_ci_contains_parallel_evals_and_cache() -> None:
    """Business Rule: reusable-spec-ci.yml deve executar evals em paralelo via pytest -n 4 com cache."""
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "reusable-spec-ci.yml"

    content = workflow_path.read_text(encoding="utf-8")
    assert "pytest -n 4" in content
    assert "actions/cache@v4" in content
    assert "workflow_call" in content


def test_reusable_tag_evaluation_contains_fast_judge_mode() -> None:
    """Business Rule: reusable-tag-evaluation.yml deve suportar fast mode com voto único e expor outputs."""
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "reusable-tag-evaluation.yml"

    content = workflow_path.read_text(encoding="utf-8")
    assert "--fast" in content
    assert "compliance_score" in content
    assert "status" in content
    assert "workflow_call" in content


def test_reusable_release_contains_workflow_call_and_semver() -> None:
    """Business Rule: reusable-release.yml deve ser invocável via workflow_call e orquestrar SemVer."""
    repo_root = Path(__file__).resolve().parents[2]
    workflow_path = repo_root / ".github" / "workflows" / "reusable-release.yml"

    content = workflow_path.read_text(encoding="utf-8")
    assert "workflow_call" in content
    assert "reusable-tag-evaluation.yml" in content


def test_justfile_templates_contain_judge_local_recipe() -> None:
    """Business Rule: Templates de justfile poliglota e raiz devem expor a receita judge-local."""
    repo_root = Path(__file__).resolve().parents[2]

    justfiles_to_check = [
        repo_root / "justfile",
        repo_root / "src" / "harness_state" / "catalog" / "pipeline" / "python" / "justfile",
        repo_root / "src" / "harness_state" / "catalog" / "pipeline" / "go" / "justfile",
        repo_root / "src" / "harness_state" / "catalog" / "pipeline" / "typescript" / "justfile",
    ]

    for justfile_path in justfiles_to_check:
        assert justfile_path.is_file(), f"Justfile {justfile_path} não encontrado."
        content = justfile_path.read_text(encoding="utf-8")
        assert "judge-local:" in content, f"Receita judge-local ausente em {justfile_path}"
        assert "harness judge --local" in content


def test_harness_judge_verification_skill_mirror_identity() -> None:
    """Business Rule: A skill harness-judge-verification no catálogo e em .claude/skills deve ser idêntica."""
    repo_root = Path(__file__).resolve().parents[2]
    catalog_skill = (
        repo_root / "src" / "harness_state" / "catalog" / "skills" / "common"
        / "harness-judge-verification" / "SKILL.md"
    )
    installed_skill = (
        repo_root / ".claude" / "skills" / "harness-judge-verification" / "SKILL.md"
    )

    assert catalog_skill.is_file(), "Skill harness-judge-verification ausente no catálogo."
    assert installed_skill.is_file(), "Skill harness-judge-verification ausente em .claude/skills."

    catalog_text = catalog_skill.read_text(encoding="utf-8")
    installed_text = installed_skill.read_text(encoding="utf-8")
    assert catalog_text == installed_text
    assert "harness judge --local" in catalog_text
    assert "Gate Integrity & Test Preservation" in catalog_text
    assert "No Error Masking" in catalog_text
    assert "Public Contract Preservation" in catalog_text
