"""Testes unitários do sensor de complexidade cognitiva Python (complexipy)."""

import textwrap
from pathlib import Path

import pytest

from harness_state.installer import install_module_harness
from harness_state.sensors.complexity_sensor import (
    ComplexityViolation,
    check_complexity_source,
    main,
    run_complexity_sensor,
)


def test_clean_function_passes_complexity_sensor() -> None:
    """Business Rule: funções com complexidade <= 15 não geram violações."""
    source = textwrap.dedent(
        """
        def compute_discount(total: float, is_vip: bool) -> float:
            if total <= 0:
                return 0.0
            if is_vip:
                return total * 0.2
            return total * 0.05
        """
    )
    violations = check_complexity_source(source, file_label="pricing.py")
    assert violations == []


def test_complex_function_emits_complexipy_refactor_suggestions() -> None:
    """Business Rule: funções acima do limite geram violação com sugestão do complexipy.

    O sensor executa o ``complexipy`` com ``with_plans=True`` e inclui os
    planos de refatoração (ex: C001/C002/C003, linhas e redução estimada)
    no texto formatado para o agente LLM.
    """
    source = textwrap.dedent(
        """
        def overly_complex_processor(items, flags, mode):
            result = []
            for item in items:
                if item.get("enabled"):
                    if mode == "strict":
                        for flag in flags:
                            if flag in item:
                                if item[flag] > 10:
                                    if item.get("special"):
                                        result.append(item[flag] * 2)
                                    else:
                                        result.append(item[flag])
                                elif item[flag] < 0:
                                    result.append(0)
                    elif mode == "lenient":
                        if item.get("fallback"):
                            result.append(1)
            return result
        """
    )
    violations = check_complexity_source(
        source, file_label="src/processor.py", max_complexity=10
    )
    assert len(violations) == 1
    violation = violations[0]
    assert violation.function_name == "overly_complex_processor"
    assert violation.complexity > 10
    assert "Complexipy suggestion" in violation.suggestion_text
    formatted = violation.format_output()
    expected_prefix = f"src/processor.py:{violation.line}:{violation.column}:"
    assert formatted.startswith(expected_prefix)
    assert "Function 'overly_complex_processor' has cognitive complexity" in formatted
    assert "Complexipy suggestion" in formatted


def test_cli_main_returns_nonzero_and_prints_prescriptive_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: CLI do sensor retorna 1 e imprime linha compatível com ruff."""
    bad_file = tmp_path / "complex_mod.py"
    bad_file.write_text(
        textwrap.dedent(
            """
            def deeply_nested(data):
                total = 0
                for row in data:
                    if row:
                        for cell in row:
                            if cell > 0:
                                if cell % 2 == 0:
                                    total += cell
                                else:
                                    total += 1
                return total
            """
        ),
        encoding="utf-8",
    )

    exit_code = main(["--max-complexity-allowed", "5", str(bad_file)])
    out = capsys.readouterr().out.strip()

    assert exit_code == 1
    assert "deeply_nested" in out
    assert "Complexipy suggestion" in out


def test_run_complexity_sensor_scans_directory_and_ignores_venv(
    tmp_path: Path,
) -> None:
    """Business Rule: diretórios ignorados (.venv, .git) não são analisados."""
    venv_dir = tmp_path / ".venv" / "lib"
    venv_dir.mkdir(parents=True)
    (venv_dir / "ignored.py").write_text(
        "def f(x):\n"
        "    if x:\n"
        "        if x > 1:\n"
        "            if x > 2:\n"
        "                return x\n"
        "    return 0\n",
        encoding="utf-8",
    )

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "clean.py").write_text(
        "def add(a: int, b: int) -> int:\n    return a + b\n",
        encoding="utf-8",
    )

    violations = run_complexity_sensor(
        targets=[str(tmp_path)], max_complexity=2, root_dir=tmp_path
    )
    assert violations == []


def test_installer_deploys_complexity_sensor_and_precommit_hook(
    tmp_path: Path,
) -> None:
    """Business Rule: `harness init` instala complexity_sensor.py e pre-commit."""
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    (tmp_path / ".git" / "hooks").mkdir(parents=True)

    res = install_module_harness(project_root=tmp_path, language="python", force=True)

    assert ".harness/sensors/complexity_sensor.py" in res.installed_pipeline_files
    assert (tmp_path / ".harness" / "sensors" / "complexity_sensor.py").is_file()
    justfile_text = (tmp_path / "justfile").read_text(encoding="utf-8")
    assert "complexity_sensor.py" in justfile_text
    hook_text = (tmp_path / ".git" / "hooks" / "pre-commit").read_text(encoding="utf-8")
    assert "complexipy" in hook_text
    assert "--suggest-refactors" in hook_text


def test_complexity_violation_repr_is_informative() -> None:
    """Business Rule: ComplexityViolation implementa __repr__ informativo."""
    v = ComplexityViolation(
        file_path="a.py",
        line=10,
        column=1,
        rule="C001",
        function_name="fn",
        complexity=18,
        max_allowed=15,
        suggestion_text="Complexipy suggestion [C001]: Flatten",
    )
    assert "ComplexityViolation(" in repr(v)
    assert "function_name='fn'" in repr(v)
