"""Testes unitários para o coletor de artefatos e telemetria em harness_state (SPEC-009E)."""

import base64
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from harness_state.collector import (
    collect_diffs,
    discover_tasks,
    fetch_spec,
    send_gate_telemetry,
)


def mock_diff_and_source_run(cmd: list[str], *args: Any, **kwargs: Any) -> MagicMock:
    """Função utilitária de mock para simular diffs e buscas de código-fonte.

    Args:
        cmd: Lista de argumentos do comando subprocess.
        *args: Argumentos posicionais adicionais.
        **kwargs: Argumentos nomeados adicionais.

    Returns:
        MagicMock simulando CompletedProcess com retornos pertinentes.
    """
    if "diff" in cmd:
        return MagicMock(
            returncode=0,
            stdout="+++ b/.harness/specs/spec.md\n# Spec diff",
            stderr="",
        )
    if len(cmd) > 2 and "contents" in cmd[2]:
        code = "class TestClient:\n    pass\n"
        b64_code = base64.b64encode(code.encode("utf-8")).decode("utf-8")
        return MagicMock(returncode=0, stdout=b64_code, stderr="")
    return MagicMock(returncode=0, stdout="", stderr="")


def test_collector_fetch_spec_success(tmp_path: Path) -> None:
    """Business Rule: Recupera a spec do hub via GitHub API decodificando base64."""
    out_file = tmp_path / "spec.md"
    encoded_content = base64.b64encode(b"# Spec 002 Content").decode("utf-8")

    fake_proc = MagicMock(returncode=0, stdout=encoded_content, stderr="")
    with patch("subprocess.run", return_value=fake_proc) as mock_run:
        result = fetch_spec(
            spec_id="SPEC-002-test",
            hub_repo="paralax-ia/paralax-spec-hub",
            out_file=out_file,
        )

        assert result == out_file
        assert out_file.read_text(encoding="utf-8") == "# Spec 002 Content"
        assert mock_run.called


def test_collector_discover_tasks_from_spec_fallback(tmp_path: Path) -> None:
    """Business Rule: Fallback para parse da spec e consulta de PRs abertos."""
    spec_content = (
        "# SPEC-002-test: Test Spec\n\n"
        "## 4. Plano de Decomposição (Sub-Tarefas)\n\n"
        "- [ ] **Sub-tarefa 1 (`paralax-ia/paralax-evo-crm`):**\n"
        "  - Implementar cliente CRM\n"
    )
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(spec_content, encoding="utf-8")

    fake_pr_json = json.dumps([{"number": 42}])
    fake_proc = MagicMock(returncode=0, stdout=fake_pr_json, stderr="")

    with patch("subprocess.run", return_value=fake_proc):
        tasks = discover_tasks(
            spec_id="SPEC-002-test",
            spec_file=spec_file,
            redis_host="127.0.0.1",
            redis_port=6379,
        )

        assert len(tasks) == 1
        repo, pr_num, _ = tasks[0]
        assert repo == "paralax-ia/paralax-evo-crm"
        assert pr_num == 42


def test_collector_collect_diffs_and_enrichment(tmp_path: Path) -> None:
    """Business Rule: Coleta diffs dos PRs e enriquece com código-fonte."""
    spec_content = (
        "# SPEC-002\n\nConsulte o arquivo `paralax/evo/crm/client.py` para detalhes.\n"
    )
    spec_file = tmp_path / "spec.md"
    spec_file.write_text(spec_content, encoding="utf-8")

    diffs_out = tmp_path / "all_diffs.patch"
    tasks = [("paralax-ia/paralax-evo-crm", 12, "task-1")]

    with patch("subprocess.run", side_effect=mock_diff_and_source_run):
        collect_diffs(
            tasks=tasks,
            spec_file=spec_file,
            diffs_out=diffs_out,
        )

        patch_text = diffs_out.read_text(encoding="utf-8")
        assert "=== REPOSITORIO: paralax-ia/paralax-evo-crm (PR #12) ===" in patch_text
        marker = (
            "=== CODIGO FONTE IMPLEMENTADO: "
            "paralax-ia/paralax-evo-crm/paralax/evo/crm/client.py ==="
        )
        assert marker in patch_text
        assert "class TestClient:" in patch_text


def test_collector_send_telemetry() -> None:
    """Business Rule: Envia telemetria do gate via POST HTTP estruturado."""
    mock_ctx = MagicMock()
    mock_ctx.__enter__.return_value.status = 201

    with patch("urllib.request.urlopen", return_value=mock_ctx) as mock_url:
        success = send_gate_telemetry(
            spec_id="SPEC-002-test",
            status="APPROVED",
            score=1.0,
            es_url="http://127.0.0.1:9200/harness-sensor-telemetry/_doc",
        )
        assert success is True
        assert mock_url.called
