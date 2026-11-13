"""Testes unitários para integração sob demanda com o Superpowers."""

from pathlib import Path
from unittest.mock import patch

from harness_state.installer import (
    detect_project_language,
    install_agent_guidelines,
    install_module_harness,
)
from harness_state.superpowers import install_superpowers_from_upstream


def test_install_module_harness_ci_mode_keeps_agent_context(tmp_path: Path) -> None:
    """Business Rule: modo CI deve carregar skills de contexto no projeto alvo.

    O agente headless da esteira roda exatamente no alvo onde `harness init
    --ci` é executado; o contexto (skills por linguagem + AGENTS/CLAUDE) nunca
    pode ser omitido, pois pertence ao harness e não ao modo de execução.
    """
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'spoke-ci'\n", encoding="utf-8"
    )

    result = install_module_harness(project_root=tmp_path, ci_mode=True)

    installed = set(result.installed_skills)
    assert ".claude/skills/fluent-python/SKILL.md" in installed
    assert ".claude/skills/python-style/SKILL.md" in installed
    assert ".claude/skills/federated-sdd/SKILL.md" in installed
    assert ".claude/skills/tdd-workflow/SKILL.md" in installed
    agents_md = tmp_path / "AGENTS.md"
    assert agents_md.is_file()
    assert "<!-- SUPERPOWERS-HARNESS:START -->" in agents_md.read_text(
        encoding="utf-8"
    )


def test_detect_project_language_detection_matrix(tmp_path: Path) -> None:
    """Business Rule: init detecta a linguagem do projeto pelos manifestos."""
    cases = (
        ("pyproject.toml", "python"),
        ("go.mod", "go"),
        ("package.json", "typescript"),
        ("tsconfig.json", "typescript"),
    )
    for manifest_name, expected in cases:
        root = tmp_path / manifest_name.replace(".", "_")
        root.mkdir()
        (root / manifest_name).write_text("[]", encoding="utf-8")
        assert detect_project_language(root) == expected


def test_install_module_harness_installs_federated_sdd_skill(
    tmp_path: Path,
) -> None:
    """Business Rule: O harness deve instalar a skill federated-sdd por padrão.

    Verifica se a skill de conexão entre o Superpowers e o ecossistema federado
    está presente e contém as diretrizes do spec-hub e fan-out cirúrgico.
    """
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text("[project]\nname = 'test-spoke'\n", encoding="utf-8")

    install_module_harness(project_root=tmp_path)

    federated_sdd_md = tmp_path / ".claude" / "skills" / "federated-sdd" / "SKILL.md"
    assert federated_sdd_md.is_file()

    content = federated_sdd_md.read_text(encoding="utf-8")
    assert "name: federated-sdd" in content
    assert "harness spec plan" in content
    assert "harness spec fanout" in content
    assert "harness spec sync-hub" in content


def test_install_superpowers_from_upstream_copies_skills(
    tmp_path: Path,
) -> None:
    """Business Rule: install_superpowers_from_upstream deve clonar e copiar skills.

    Garante que o comando baixa do repositório upstream oficial e popula o
    diretório .claude/skills do projeto sem necessitar de vendor local no repositório.
    """
    mock_upstream = tmp_path / "mock_upstream"
    upstream_skills = mock_upstream / "skills"

    brainstorming_dir = upstream_skills / "brainstorming"
    brainstorming_dir.mkdir(parents=True)
    (brainstorming_dir / "SKILL.md").write_text(
        "---\nname: brainstorming\n---\n# Brainstorming\n", encoding="utf-8"
    )

    using_sp_dir = upstream_skills / "using-superpowers"
    using_sp_dir.mkdir(parents=True)
    (using_sp_dir / "SKILL.md").write_text(
        "---\nname: using-superpowers\n---\n# Using Superpowers\n",
        encoding="utf-8",
    )
    references_dir = using_sp_dir / "references"
    references_dir.mkdir()
    (references_dir / "claude-code-tools.md").write_text(
        "# Claude Tools", encoding="utf-8"
    )

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n", encoding="utf-8"
    )

    with patch(
        "harness_state.superpowers.sync_superpowers_upstream",
        return_value=mock_upstream,
    ):
        installed = install_superpowers_from_upstream(project_root=project_dir)

    target_skills = project_dir / ".claude" / "skills"
    assert (target_skills / "brainstorming" / "SKILL.md").is_file()
    assert (target_skills / "using-superpowers" / "SKILL.md").is_file()
    assert (
        target_skills / "using-superpowers" / "references" / "claude-code-tools.md"
    ).is_file()
    assert (target_skills / "federated-sdd" / "SKILL.md").is_file()

    agents_md = project_dir / "AGENTS.md"
    assert agents_md.is_file()
    assert "using-superpowers" in agents_md.read_text(encoding="utf-8")
    assert any("brainstorming" in p for p in installed)


def test_install_module_harness_creates_agent_guidelines(
    tmp_path: Path,
) -> None:
    """Business Rule: O instalador deve gerar diretrizes nos arquivos de instruções.

    Verifica se AGENTS.md e CLAUDE.md são criados com o bloco de instruções do
    Superpowers e Federated SDD.
    """
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text("[project]\nname = 'test-spoke'\n", encoding="utf-8")

    install_module_harness(project_root=tmp_path)

    agents_md = tmp_path / "AGENTS.md"
    claude_md = tmp_path / "CLAUDE.md"

    assert agents_md.is_file()
    assert claude_md.is_file()

    agents_content = agents_md.read_text(encoding="utf-8")
    assert "<!-- SUPERPOWERS-HARNESS:START -->" in agents_content
    assert "using-superpowers" in agents_content
    assert "harness spec plan" in agents_content


def test_install_agent_guidelines_idempotent(tmp_path: Path) -> None:
    """Business Rule: Atualizações em AGENTS.md e CLAUDE.md devem ser idempotentes.

    Garante que re-execuções substituem a seção delimitada sem duplicar blocos.
    """
    agents_md = tmp_path / "AGENTS.md"
    initial_content = "# Meu Projeto\n\nTexto original do projeto.\n"
    agents_md.write_text(initial_content, encoding="utf-8")

    install_agent_guidelines(tmp_path)
    content_first = agents_md.read_text(encoding="utf-8")
    assert "Texto original do projeto." in content_first
    assert content_first.count("<!-- SUPERPOWERS-HARNESS:START -->") == 1

    install_agent_guidelines(tmp_path)
    content_second = agents_md.read_text(encoding="utf-8")
    assert content_second.count("<!-- SUPERPOWERS-HARNESS:START -->") == 1
    assert content_first == content_second


def test_install_module_harness_installs_fluent_python_skill_and_specs(
    tmp_path: Path,
) -> None:
    """Business Rule: O harness instala a skill fluent-python e as 14 specs normativas.

    Garante que projetos Python recebem SKILL.md e todas as specs em references/.
    """
    pyproject_file = tmp_path / "pyproject.toml"
    pyproject_file.write_text("[project]\nname = 'python-spoke'\n", encoding="utf-8")

    install_module_harness(project_root=tmp_path)

    fluent_python_dir = tmp_path / ".claude" / "skills" / "fluent-python"
    skill_md = fluent_python_dir / "SKILL.md"
    assert skill_md.is_file()

    skill_text = skill_md.read_text(encoding="utf-8")
    assert "name: fluent-python" in skill_text
    assert "Grupo A" in skill_text

    references_dir = fluent_python_dir / "references"
    assert references_dir.is_dir()
    for spec_index in range(14):
        spec_prefix = f"SPEC-PY-{spec_index:02d}"
        matching_specs = list(references_dir.glob(f"{spec_prefix}*.md"))
        assert len(matching_specs) == 1


def test_install_agent_guidelines_carrega_rca_guidelines_para_agentes(
    tmp_path: Path,
) -> None:
    """Business Rule: Todo agente provisionado recebe a diretriz mandatória de RCA.

    O bloco instalado em AGENTS.md/CLAUDE.md deve instruir o carregamento de
    `specs/prompts/rca_guidelines.md` exigindo as 3 Etapas Canônicas de
    Investigação (Triagem de Esporadicidade, Ishikawa e 5 Porquês) antes de
    qualquer correção de bug, além da proibição de mascaramento de erros.
    """
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("# Meu Projeto\n", encoding="utf-8")

    install_agent_guidelines(tmp_path)
    agents_content = agents_md.read_text(encoding="utf-8")

    assert "rca_guidelines.md" in agents_content
    assert "Triagem de Esporadicidade" in agents_content
    assert "Ishikawa" in agents_content
    assert "5 Porquês" in agents_content


def test_install_module_harness_federated_sdd_redireciona_spec_para_specs(
    tmp_path: Path,
) -> None:
    """Business Rule: skill federated-sdd manda gravar a spec no SSOT specs/."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'spoke-x'\n", encoding="utf-8"
    )

    install_module_harness(project_root=tmp_path, ci_mode=True)

    skill = (tmp_path / ".claude/skills/federated-sdd/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "docs/superpowers/specs/" in skill
    assert "<project>-spec-hub/specs/SPEC-XXX.md" in skill
    assert "`SPEC-XXX-<slug>.md`" in skill


def test_instalada_federated_sdd_e_copia_fiel_do_catalogo() -> None:
    """Business Rule: a copia instalada de federated-sdd nunca diverge do catalogo.

    Este repo mantem a copia instalada (`.claude/skills/federated-sdd`) sob
    controle de versao; ela deve permanecer identica a origem embutida no
    pacote (`src/harness_state/catalog/skills/common/federated-sdd`).
    """
    repo_root = Path(__file__).resolve().parents[2]
    catalog = (
        repo_root
        / "src/harness_state/catalog/skills/common/federated-sdd/SKILL.md"
    ).read_text(encoding="utf-8")
    installed = (repo_root / ".claude/skills/federated-sdd/SKILL.md").read_text(
        encoding="utf-8"
    )

    assert installed == catalog


def test_install_agent_guidelines_redireciona_spec_para_pasta_specs(
    tmp_path: Path,
) -> None:
    """Business Rule: diretrizes mandam gravar a spec no SSOT specs/, não em docs/."""
    for name in ("AGENTS.md", "CLAUDE.md"):
        (tmp_path / name).write_text("contexto\n", encoding="utf-8")

    result = install_agent_guidelines(tmp_path)

    assert set(result) == {"AGENTS.md", "CLAUDE.md"}
    for name in ("AGENTS.md", "CLAUDE.md"):
        content = (tmp_path / name).read_text(encoding="utf-8")
        assert "docs/superpowers/specs/" in content
        assert "<project>-spec-hub/specs/SPEC-XXX.md" in content
        assert "`SPEC-XXX-<slug>.md`" in content
