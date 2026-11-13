"""Testes unitários do sensor determinístico de CI/CD (SPEC-CICD-01)."""

from pathlib import Path

from harness_state.installer import detect_project_language, install_module_harness
from harness_state.sensors.cicd_sensor import CICDValidator


def test_silent_failure_without_business_rule_is_flagged(tmp_path: Path) -> None:
    """Business Rule: Mascaramento silencioso de erro (|| true) deve falhar o pipeline.

    A ausência de anotação de regra de negócio invalida a supressão do erro.
    """
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    wf_file = workflow_dir / "test.yml"
    wf_file.write_text(
        "name: Test\n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          set -e\n"
        "          do_something || true\n",
        encoding="utf-8",
    )

    validator = CICDValidator(tmp_path)
    exit_code = validator.run()

    assert exit_code == 1
    codes = [v.code for v in validator.violations]
    assert "CICD001" in codes


def test_silent_failure_with_business_rule_is_allowed(tmp_path: Path) -> None:
    """Business Rule: Mascaramento e valido se documentado com Business Rule.

    A anotacao '# Business Rule:' na mesma linha ou anterior justifica o tratamento.
    """
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    wf_file = workflow_dir / "test.yml"
    wf_file.write_text(
        "name: Test\n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          set -e\n"
        "          # Business Rule: Tolerar remocao de container previo\n"
        "          docker rm -f my_container || true\n",
        encoding="utf-8",
    )

    validator = CICDValidator(tmp_path)
    exit_code = validator.run()

    assert exit_code == 0
    assert len(validator.violations) == 0


def test_continue_on_error_without_business_rule_is_flagged(tmp_path: Path) -> None:
    """Business Rule: continue-on-error requer justificativa de negocio.

    Garante que falhas nao sejam ignoradas indiscriminadamente.
    """
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    wf_file = workflow_dir / "test.yml"
    wf_file.write_text(
        "name: Test\n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          set -e\n"
        "          pytest\n"
        "        continue-on-error: true\n",
        encoding="utf-8",
    )

    validator = CICDValidator(tmp_path)
    exit_code = validator.run()

    assert exit_code == 1
    codes = [v.code for v in validator.violations]
    assert "CICD002" in codes


def test_multiline_script_without_set_e_is_flagged(tmp_path: Path) -> None:
    """Business Rule: Scripts shell multiline em CI/CD devem iniciar com set -e.

    Garante execução fail-fast evitando continuidade após comandos com erro.
    """
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    wf_file = workflow_dir / "test.yml"
    wf_file.write_text(
        "name: Test\n"
        "on: push\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: |\n"
        "          echo 'sem fail fast'\n"
        "          do_something\n",
        encoding="utf-8",
    )

    validator = CICDValidator(tmp_path)
    exit_code = validator.run()

    assert exit_code == 1
    codes = [v.code for v in validator.violations]
    assert "CICD003" in codes


def test_cloudbuild_script_with_set_e_is_approved(tmp_path: Path) -> None:
    """Business Rule: Passos de Cloud Build com set -e atendem à política fail-fast.

    Valida que arquivos cloudbuild*.yaml são inspecionados e aprovados quando conformes.
    """
    cb_file = tmp_path / "cloudbuild.yaml"
    cb_file.write_text(
        "steps:\n"
        "  - name: 'bash'\n"
        "    entrypoint: 'bash'\n"
        "    args:\n"
        "      - '-c'\n"
        "      - |\n"
        "        set -e\n"
        "        echo 'construindo'\n"
        "        pytest\n",
        encoding="utf-8",
    )

    validator = CICDValidator(tmp_path)
    exit_code = validator.run()

    assert exit_code == 0
    assert len(validator.violations) == 0


def test_invalid_yaml_syntax_is_flagged(tmp_path: Path) -> None:
    """Business Rule: Sintaxe YAML invalida e sinalizada imediatamente."""
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    wf_file = workflow_dir / "invalid.yml"
    wf_file.write_text("name: Test\njobs: [invalid: mapping", encoding="utf-8")

    validator = CICDValidator(tmp_path)
    exit_code = validator.run()

    assert exit_code == 1
    codes = [v.code for v in validator.violations]
    assert "CICD000" in codes


def test_detect_cicd_project_language(tmp_path: Path) -> None:
    """Business Rule: Diretorios com .github/workflows sao identificados como cicd.

    Garante a correta identificação automática de modulos de CI/CD.
    """
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)
    assert detect_project_language(tmp_path) == "cicd"


def test_installer_initializes_cicd_harness(tmp_path: Path) -> None:
    """Business Rule: Instalacao cicd entrega pipeline e sensor dedicado.

    O justfile e os sensores especificos de CI/CD devem ser provisionados no destino.
    """
    workflow_dir = tmp_path / ".github" / "workflows"
    workflow_dir.mkdir(parents=True)

    result = install_module_harness(tmp_path, language="cicd")

    assert result.language == "cicd"
    assert (tmp_path / "justfile").is_file()
    assert (tmp_path / ".harness" / "sensors" / "cicd_sensor.py").is_file()
    justfile_content = (tmp_path / "justfile").read_text(encoding="utf-8")
    assert "cicd_sensor.py" in justfile_content