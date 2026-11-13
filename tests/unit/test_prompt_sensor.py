"""Testes unitários do sensor de governança de prompts (SPEC-PROMPT-01).

Valida a conformidade de prompts modificados no código local contra as
especificações e a fonte única da verdade no Langfuse.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from harness_state.prompt_manager import PromptManagementError
from harness_state.sensors.prompt_sensor import (
    PromptGovernanceSensor,
    detect_prompt_files_in_diff,
    discover_prompts_in_repository,
    extract_prompt_text_from_file,
    find_local_prompt_file_for_name,
    is_prompt_file,
    pull_prompts_from_langfuse_ssot,
    sync_modified_prompts_as_draft,
)


def test_detect_prompt_files_identifies_matching_paths() -> None:
    """Business Rule: Identifica arquivos de prompt por convenção de nome e pasta."""
    changed = [
        "src/vehicles/prompts.py",
        "src/vehicles/models.py",
        "prompts/customer_support.txt",
        "templates/prompt_instructions.md",
        "vehicles/crm_client.py",
    ]
    detected = detect_prompt_files_in_diff(changed)
    assert "src/vehicles/prompts.py" in detected
    assert "prompts/customer_support.txt" in detected
    assert "templates/prompt_instructions.md" in detected
    assert "src/vehicles/models.py" not in detected
    assert "vehicles/crm_client.py" not in detected


def test_sensor_passes_when_no_prompt_files_changed(tmp_path: Path) -> None:
    """Business Rule: Sensor é aprovado se nenhuma alteração toca em prompts."""
    sensor = PromptGovernanceSensor(project_root=tmp_path)
    sample_files = ["src/main.py", "tests/test_main.py"]
    with patch.object(sensor, "get_changed_files", return_value=sample_files):
        violations = sensor.validate(declared_prompts=[])
        assert violations == []


def test_sensor_fails_when_prompt_files_changed_without_declaration(
    tmp_path: Path,
) -> None:
    """Business Rule: Bloqueia com PRM001 se prompts mudaram sem declaração."""
    sensor = PromptGovernanceSensor(project_root=tmp_path)
    sample_files = ["vehicles/prompts.py", "README.md"]
    with patch.object(sensor, "get_changed_files", return_value=sample_files):
        violations = sensor.validate(declared_prompts=[])
        assert len(violations) == 1
        assert violations[0].code == "PRM001"
        assert "vehicles/prompts.py" in violations[0].message


def test_sensor_passes_when_prompt_files_changed_and_declared_in_spec(
    tmp_path: Path,
) -> None:
    """Business Rule: Aprova quando os arquivos de prompt estão na spec."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.fetch_prompt.return_value = ("instrucao", 1)
    sensor = PromptGovernanceSensor(project_root=tmp_path, prompt_manager=mock_mgr)
    sample_files = ["vehicles/prompts.py"]
    with patch.object(sensor, "get_changed_files", return_value=sample_files):
        violations = sensor.validate(declared_prompts=["paralax/vehicles-support"])
        assert violations == []


def test_sensor_validates_langfuse_draft_when_configured(tmp_path: Path) -> None:
    """Business Rule: Bloqueia com PRM002 se o prompt não existe no Langfuse."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.fetch_prompt.side_effect = PromptManagementError("Prompt not found")

    sensor = PromptGovernanceSensor(project_root=tmp_path, prompt_manager=mock_mgr)
    sample_files = ["vehicles/prompts.py"]
    with patch.object(sensor, "get_changed_files", return_value=sample_files):
        violations = sensor.validate(declared_prompts=["paralax/missing-prompt"])
        assert len(violations) == 1
        assert violations[0].code == "PRM002"
        assert "paralax/missing-prompt" in violations[0].message


def test_discover_prompts_in_repository_finds_langfuse_prompts(
    tmp_path: Path,
) -> None:
    """Business Rule: Descobre nomes de prompts em arquivos Python por convenção."""
    agent_code = (
        'prompt_name = "vehicles/vehicle_search_agent_instruction"\n'
        "langfuse_prompt = langfuse_client.get_prompt(prompt_name)\n"
    )
    (tmp_path / "agent.py").write_text(agent_code, encoding="utf-8")

    service_code = 'prompt = client.get_prompt("paralax/global_greeting")\n'
    (tmp_path / "service.py").write_text(service_code, encoding="utf-8")

    discovered = discover_prompts_in_repository(tmp_path)
    assert "paralax/global_greeting" in discovered
    assert "vehicles/vehicle_search_agent_instruction" in discovered


def test_extract_prompt_text_from_python_file(tmp_path: Path) -> None:
    """Business Rule: Extrai o texto contido na constante INSTRUCTION."""
    prompt_file = tmp_path / "prompts.py"
    prompt_file.write_text(
        'INSTRUCTION = """Você é um especialista em suporte ao cliente."""\n',
        encoding="utf-8",
    )
    extracted = extract_prompt_text_from_file(prompt_file)
    assert extracted == "Você é um especialista em suporte ao cliente."


def test_extract_prompt_text_from_raw_text_file(tmp_path: Path) -> None:
    """Business Rule: Extrai o conteúdo integral de arquivos textuais de prompt."""
    prompt_file = tmp_path / "instructions.txt"
    prompt_file.write_text(
        "Instrução direta em arquivo texto puro.",
        encoding="utf-8",
    )
    extracted = extract_prompt_text_from_file(prompt_file)
    assert extracted == "Instrução direta em arquivo texto puro."


def test_sync_modified_prompts_as_draft_pushes_to_langfuse(tmp_path: Path) -> None:
    """Business Rule: Sincroniza arquivos de prompt alterados como draft no Langfuse."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.push_draft.return_value = 2

    prompt_dir = tmp_path / "vehicles"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_dir / "prompts.py"
    prompt_file.write_text(
        'INSTRUCTION = """Instrução revisada pós correção de defeito."""\n',
        encoding="utf-8",
    )
    agent_file = prompt_dir / "agent.py"
    agent_file.write_text(
        'prompt_name = "vehicles/vehicle_search_agent_instruction"\n',
        encoding="utf-8",
    )

    with patch(
        "harness_state.sensors.prompt_sensor.PromptGovernanceSensor.get_changed_files",
        return_value=["vehicles/prompts.py"],
    ):
        synced = sync_modified_prompts_as_draft(
            project_root=tmp_path, prompt_manager=mock_mgr
        )

    assert len(synced) == 1
    assert synced[0][0] == "vehicles/vehicle_search_agent_instruction"
    assert synced[0][1] == 2
    mock_mgr.push_draft.assert_called_once_with(
        "vehicles/vehicle_search_agent_instruction",
        "Instrução revisada pós correção de defeito.",
        label="draft",
    )


def test_find_local_prompt_file_for_name(tmp_path: Path) -> None:
    """Business Rule: Localiza o arquivo físico de prompt correspondente ao ID."""
    vehicles_dir = tmp_path / "vehicles"
    vehicles_dir.mkdir(parents=True)
    prompt_file = vehicles_dir / "prompts.py"
    prompt_file.write_text("INSTRUCTION = 'abc'", encoding="utf-8")

    found = find_local_prompt_file_for_name(
        project_root=tmp_path,
        prompt_name="vehicles/vehicle_search_agent_instruction",
    )
    assert found == prompt_file


def test_pull_prompts_from_langfuse_ssot_updates_local_fallback(
    tmp_path: Path,
) -> None:
    """Business Rule: Sincroniza versão mais recente do Langfuse (SSOT) no código."""
    vehicles_dir = tmp_path / "vehicles"
    vehicles_dir.mkdir(parents=True)
    prompt_file = vehicles_dir / "prompts.py"
    prompt_file.write_text(
        'INSTRUCTION = """Versão antiga desatualizada no código."""\n',
        encoding="utf-8",
    )

    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.fetch_prompt.return_value = (
        "Versão oficial vigente no Langfuse (Fonte da Verdade).",
        5,
    )
    mock_mgr.update_local_fallback.side_effect = lambda f, text: (
        f.write_text(f'INSTRUCTION = """{text}"""\n', encoding="utf-8") or True
    )

    synced = pull_prompts_from_langfuse_ssot(
        project_root=tmp_path,
        prompt_manager=mock_mgr,
        target_prompts=["vehicles/vehicle_search_agent_instruction"],
    )

    assert len(synced) == 1
    prompt_name, version, rel_path = synced[0]
    assert prompt_name == "vehicles/vehicle_search_agent_instruction"
    assert version == 5
    assert rel_path == "vehicles/prompts.py"

    updated_content = prompt_file.read_text(encoding="utf-8")
    assert "Versão oficial vigente no Langfuse (Fonte da Verdade)." in updated_content


def test_is_prompt_file_ignores_harness_and_specs() -> None:
    """Business Rule: Arquivos em .harness e specs nunca são considerados prompts."""
    assert not is_prompt_file(".harness/current_task_prompt.md")
    assert not is_prompt_file("specs/SPEC-010.md")
    assert not is_prompt_file(".harness/specs/spec.md")
    assert not is_prompt_file(".harness/current_task_prompt.md")
    assert is_prompt_file("vehicles/prompts.py")
    assert is_prompt_file("prompts/instructions.txt")


def test_find_local_prompt_file_ignores_harness_current_task_prompt(
    tmp_path: Path,
) -> None:
    """Business Rule: find_local_prompt_file nunca retorna .harness/task_prompt."""
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir(parents=True)
    task_prompt = harness_dir / "current_task_prompt.md"
    task_prompt.write_text(
        "# Task: 1\n## SDD Specification:\n---\nspec_id: SPEC-010\n---",
        encoding="utf-8",
    )

    found = find_local_prompt_file_for_name(
        project_root=tmp_path,
        prompt_name="unrelated/instruction",
    )
    assert found is None


def test_extract_prompt_text_rejects_sdd_spec_content(tmp_path: Path) -> None:
    """Business Rule: extract_prompt_text descarta arquivos markdown de SDD."""
    spec_md = tmp_path / "task_prompt.md"
    spec_md.write_text(
        "---\nspec_id: SPEC-010\ntitle: Audio\n---\n# SPEC-010\nSpec content",
        encoding="utf-8",
    )
    extracted = extract_prompt_text_from_file(spec_md)
    assert extracted == ""


def test_sync_modified_prompts_filters_by_target_repo(tmp_path: Path) -> None:
    """Business Rule: sync_modified_prompts apenas sincroniza prompts do repo alvo."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.push_draft.return_value = 1

    repo_dir = tmp_path / "customer-support-vehicles"
    vehicles_dir = repo_dir / "vehicles"
    vehicles_dir.mkdir(parents=True)
    prompt_file = vehicles_dir / "prompts.py"
    prompt_file.write_text(
        'INSTRUCTION = """Nova instrucao de veiculos"""\n',
        encoding="utf-8",
    )

    declared_prompts = [
        {
            "name": "vehicles/vehicle_search_agent_instruction",
            "target_repo": "paralax-ia/customer-support-vehicles",
            "file": "vehicles/prompts.py",
        },
        {
            "name": "duo_dermato/support",
            "target_repo": "paralax-ia/duo-dermato-support",
            "file": "duo_dermato/prompts.py",
        },
    ]

    # Simula execução no repositório customer-support-vehicles
    with patch(
        "harness_state.sensors.prompt_sensor.PromptGovernanceSensor.get_changed_files",
        return_value=["vehicles/prompts.py"],
    ):
        synced = sync_modified_prompts_as_draft(
            project_root=repo_dir,
            prompt_manager=mock_mgr,
            target_prompts=declared_prompts,
        )

    # Deve sincronizar APENAS o prompt de vehicles, NUNCA o de duo_dermato!
    assert len(synced) == 1
    assert synced[0][0] == "vehicles/vehicle_search_agent_instruction"
    mock_mgr.push_draft.assert_called_once_with(
        "vehicles/vehicle_search_agent_instruction",
        "Nova instrucao de veiculos",
        label="draft",
    )


def test_find_local_prompt_file_locates_root_file_when_prefix_matches_repo(
    tmp_path: Path,
) -> None:
    """Business Rule: localiza prompts.py na raiz se o prefixo bater com o repo."""
    spoke_dir = tmp_path / "customer-support-vehicles"
    spoke_dir.mkdir(parents=True)
    prompt_file = spoke_dir / "prompts.py"
    prompt_file.write_text('INSTRUCTION = "Busca"', encoding="utf-8")

    found = find_local_prompt_file_for_name(
        project_root=spoke_dir,
        prompt_name="vehicles/vehicle_search_agent_instruction",
    )
    assert found == prompt_file


def test_validate_sensor_ignores_prompts_of_other_repos(tmp_path: Path) -> None:
    """Business Rule: validate ignora prompts de outros repositórios da spec."""
    mock_mgr = MagicMock()
    mock_mgr.is_configured = True
    mock_mgr.fetch_prompt.side_effect = lambda name, label=None: (
        ("Instrucao", 1)
        if name == "paralax/support"
        else (_ for _ in ()).throw(PromptManagementError("404"))
    )

    repo_dir = tmp_path / "paralax-support"
    repo_dir.mkdir(parents=True)

    declared_prompts = [
        {
            "name": "duo_dermato/instruction",
            "target_repo": "paralax-ia/duo-dermato-support",
        },
        {
            "name": "paralax/support",
            "target_repo": "paralax-ia/paralax-support",
        },
    ]

    sensor = PromptGovernanceSensor(project_root=repo_dir, prompt_manager=mock_mgr)
    with patch.object(sensor, "get_changed_files", return_value=[]):
        violations = sensor.validate(declared_prompts=declared_prompts)

    assert violations == []
