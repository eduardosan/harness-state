"""Testes do CLI de preparação (job prepare do hub) em harness_state (SPEC-009E)."""

import json
from pathlib import Path
from typing import Any

from harness_state.prepare import main

REPOS_YML = "repos:\n  - repo: acme/pilot\n    language: python\n"


def run_prepare(
    tmp_path: Path, repo: str, issue: dict[str, Any]
) -> tuple[int, dict[str, str], Path]:
    """Executa o CLI de preparação com arquivos temporários.

    Args:
        tmp_path: Diretório temporário.
        repo: Repo alvo informado no dispatch.
        issue: Payload da issue (formato da API do GitHub).

    Returns:
        Tupla com código de saída, outputs lidos de ``GITHUB_OUTPUT`` e o
        diretório de saída.
    """
    allowlist = tmp_path / "repos.yml"
    allowlist.write_text(REPOS_YML, encoding="utf-8")
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(json.dumps(issue), encoding="utf-8")
    out_dir = tmp_path / "out"
    gh_output = tmp_path / "gh_output"
    code = main(
        [
            "--allowlist",
            str(allowlist),
            "--repo",
            repo,
            "--issue-file",
            str(issue_file),
            "--out-dir",
            str(out_dir),
            "--github-output",
            str(gh_output),
        ]
    )
    outputs: dict[str, str] = {}
    if gh_output.exists():
        for line in gh_output.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            outputs[key] = value
    return code, outputs, out_dir


def valid_issue(**overrides: object) -> dict[str, Any]:
    """Retorna um payload de issue válido.

    Args:
        **overrides: Campos a sobrescrever.

    Returns:
        Dicionário no formato da API de issues do GitHub.
    """
    data: dict[str, Any] = {
        "number": 7,
        "title": "Corrigir bug",
        "body": "A função parse() falha com entrada vazia.",
        "author_association": "OWNER",
    }
    data.update(overrides)
    return data


def test_valid_dispatch_writes_prompt_and_outputs(tmp_path: Path) -> None:
    """Business Rule: Dispatch válido gera o prompt e os parâmetros do job.

    O CLI grava ``prompt.md`` e publica ``proceed=true``, linguagem e branch
    base para os jobs seguintes.
    """
    code, outputs, out_dir = run_prepare(tmp_path, "acme/pilot", valid_issue())
    assert code == 0
    assert outputs["proceed"] == "true"
    assert outputs["language"] == "python"
    assert outputs["base_branch"] == "main"
    assert "parse()" in (out_dir / "prompt.md").read_text(encoding="utf-8")


def test_unknown_repo_fails_hard(tmp_path: Path) -> None:
    """Business Rule: Repo fora da allowlist encerra com código 3.

    É um evento de segurança: o código de saída é 3 e nenhum prompt é gerado.
    """
    code, _, out_dir = run_prepare(tmp_path, "evil/repo", valid_issue())
    assert code == 3
    assert not (out_dir / "prompt.md").exists()


def test_untrusted_author_stops_without_failing(tmp_path: Path) -> None:
    """Business Rule: Autor não confiável encerra silenciosamente.

    O workflow não deve falhar, apenas não prosseguir (``proceed=false``) com
    uma mensagem de motivo.
    """
    issue = valid_issue(author_association="NONE")
    code, outputs, out_dir = run_prepare(tmp_path, "acme/pilot", issue)
    assert code == 0
    assert outputs["proceed"] == "false"
    assert outputs["reject_message"]
    assert not (out_dir / "prompt.md").exists()


def test_oversized_issue_asks_to_split(tmp_path: Path) -> None:
    """Business Rule: Issue grande demais pede para dividir a tarefa.

    ``proceed=false`` e a mensagem orienta o autor a quebrar o trabalho.
    """
    code, outputs, _ = run_prepare(tmp_path, "acme/pilot", valid_issue(body="x" * 9000))
    assert code == 0
    assert outputs["proceed"] == "false"
    assert "dividir" in outputs["reject_message"].lower()


def test_prepare_extracts_spec_id_and_task_id_from_issue_content(
    tmp_path: Path,
) -> None:
    """Business Rule: Prepare extrai spec_id e task_id quando ausentes nos argumentos.

    Garante rastreabilidade no State Tracker mesmo quando os spokes não
    repassam o payload explicitamente no dispatch.
    """
    issue_data = valid_issue(
        title="feat(spec): [SPEC-001-crm-healthcheck] Criar endpoint de healthcheck",
        body=(
            "## 📋 Sub-Spec: Criar endpoint de healthcheck\n\n"
            "Esta issue rastreia a subtarefa `crm-healthcheck-evo-crm` da "
            "especificação central [SPEC-001-crm-healthcheck](https://hub).\n\n"
            "- **Spec ID:** `SPEC-001-crm-healthcheck`\n"
            "- **Onda de Execução:** 1\n"
        ),
    )
    code, outputs, _ = run_prepare(tmp_path, "acme/pilot", issue_data)
    assert code == 0
    assert outputs["proceed"] == "true"
    assert outputs["spec_id"] == "SPEC-001-crm-healthcheck"
    assert outputs["task_id"] == "crm-healthcheck-evo-crm"
