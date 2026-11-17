"""Módulo de Coleta de Artefatos, Diffs e Telemetria do Cross-Repo Gate."""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import redis

from harness_state.config import get_active_config
from harness_state.spec_parser import parse_spec_tasks
from harness_state.state import parse_spec_reference, redis_spec_key


def execute_gh_command(args: list[str]) -> subprocess.CompletedProcess:
    """Executa um comando gh CLI injetando token caso presente no ambiente.

    Args:
        args: Argumentos da linha de comando para o binário gh.

    Returns:
        subprocess.CompletedProcess com retorno e saídas do comando.
    """
    env = os.environ.copy()
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN")
    if token:
        env["GH_TOKEN"] = token
        env["GITHUB_TOKEN"] = token
    return subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def fetch_spec(
    spec_id: str,
    hub_repo: str = "",
    out_file: Path = Path("gate_artifacts/spec.md"),
) -> Path:
    """Baixa a especificação do hub via GitHub API e decodifica base64.

    Args:
        spec_id: Identificador da especificação (ex: SPEC-002-crm-messaging-schedule).
        hub_repo: Repositório do spec hub; se vazio, obtém da configuração/ambiente.
        out_file: Caminho local de destino para salvar a especificação.

    Returns:
        Caminho do arquivo gravado.

    Raises:
        RuntimeError: Se a especificação não puder ser recuperada ou estiver vazia.
    """
    resolved_hub = (
        hub_repo
        or os.environ.get("HARNESS_SPEC_HUB_REPO", "")
        or os.environ.get("SPEC_HUB_REPO", "")
        or get_active_config().spec_hub.default_repo
    )
    out_file.parent.mkdir(parents=True, exist_ok=True)
    api_path = f"repos/{resolved_hub}/contents/specs/{spec_id}.md"
    result = execute_gh_command(["api", api_path, "--jq", ".content"])

    content_bytes = b""
    if result.returncode == 0 and result.stdout.strip():
        clean_b64 = result.stdout.strip().replace("\n", "")
        content_bytes = base64.b64decode(clean_b64)
    else:
        jq_expr = f'.[] | select(.name | startswith("{spec_id}")) | .content'
        list_cmd = ["api", f"repos/{resolved_hub}/contents/specs", "--jq", jq_expr]
        fallback_res = execute_gh_command(list_cmd)
        if fallback_res.returncode == 0 and fallback_res.stdout.strip():
            first_entry = fallback_res.stdout.strip().splitlines()[0]
            content_bytes = base64.b64decode(first_entry.replace("\n", ""))

    if not content_bytes:
        msg = (
            f"Não foi possível recuperar o arquivo de especificação "
            f"para {spec_id} em {resolved_hub}."
        )
        raise RuntimeError(msg)

    out_file.write_bytes(content_bytes)
    return out_file


def discover_tasks_from_redis(
    spec_id: str,
    redis_host: str,
    redis_port: int,
) -> list[tuple[str, int, str]]:
    """Busca tarefas registradas para uma spec via Redis.

    Args:
        spec_id: Identificador da especificação.
        redis_host: Host do servidor Redis.
        redis_port: Porta do servidor Redis.

    Returns:
        Lista de tuplas (repositorio, pr_number, task_id).
    """
    tasks_found: list[tuple[str, int, str]] = []
    try:
        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
            socket_timeout=3,
        )
        ecosystem, parsed_id = parse_spec_reference(spec_id)
        data = client.get(redis_spec_key(ecosystem, parsed_id))
        if data:
            spec = json.loads(data)
            org = (
                os.environ.get("HARNESS_GITHUB_ORG", "")
                or get_active_config().spec_hub.github_org
            )
            for tid, task in spec.get("tasks", {}).items():
                repo = task.get("repo", "")
                pr = task.get("pr_number")
                if repo and pr:
                    if "/" not in repo and org:
                        repo = f"{org}/{repo}"
                    tasks_found.append((repo, int(pr), tid))
    except (redis.RedisError, json.JSONDecodeError, KeyError, ValueError) as exc:
        print(f"[Collector] Aviso ao consultar Redis: {exc}", file=sys.stderr)

    return tasks_found


def discover_tasks_from_spec_prs(
    spec_id: str,
    spec_file: Path,
) -> list[tuple[str, int, str]]:
    """Analisa a spec e busca PRs abertos correspondentes via GitHub CLI.

    Args:
        spec_id: Identificador da especificação.
        spec_file: Caminho do arquivo de especificação local.

    Returns:
        Lista de tuplas (repositorio, pr_number, task_id).
    """
    tasks_found: list[tuple[str, int, str]] = []
    if not spec_file.is_file():
        return tasks_found

    lines = spec_file.read_text(encoding="utf-8").splitlines()
    parsed_tasks = parse_spec_tasks(lines, spec_id=spec_id)
    print(
        f"[Collector] Tarefas identificadas na spec: {len(parsed_tasks)}",
        file=sys.stderr,
    )

    for task in parsed_tasks:
        print(
            f"[Collector] Consultando PR em {task.repo} branch {task.branch}...",
            file=sys.stderr,
        )
        cmd = [
            "pr",
            "list",
            "-R",
            task.repo,
            "--head",
            task.branch,
            "--state",
            "open",
            "--json",
            "number",
        ]
        res = execute_gh_command(cmd)
        if res.returncode == 0:
            try:
                items = json.loads(res.stdout)
                if items:
                    pr_num = int(items[0]["number"])
                    print(
                        f"[Collector] PR #{pr_num} encontrado para {task.repo}!",
                        file=sys.stderr,
                    )
                    tasks_found.append((task.repo, pr_num, task.task_id))
            except (json.JSONDecodeError, KeyError, IndexError, ValueError) as exc:
                print(
                    f"[Collector] Erro ao parsear JSON de PR: {exc}",
                    file=sys.stderr,
                )
        else:
            err_msg = res.stderr.strip()
            print(
                f"[Collector] gh pr list erro ({res.returncode}): {err_msg}",
                file=sys.stderr,
            )

    return tasks_found


def discover_tasks(
    spec_id: str,
    spec_file: Path | None = None,
    redis_host: str = "",
    redis_port: int = 0,
) -> list[tuple[str, int, str]]:
    """Descobre tarefas e PRs ativos consultando Redis e fallback de PRs abertos.

    Args:
        spec_id: Identificador da especificação.
        spec_file: Caminho do arquivo da spec (para fallback).
        redis_host: Host do Redis; se vazio, obtém da configuração/ambiente.
        redis_port: Porta do Redis; se 0, obtém da configuração/ambiente.

    Returns:
        Lista de tuplas (repositorio, pr_number, task_id).
    """
    cfg = get_active_config()
    r_host = (
        redis_host
        or os.environ.get("HARNESS_REDIS_HOST", "")
        or cfg.redis.internal_host
        or cfg.redis.external_host
    )
    r_port = (
        redis_port
        or int(os.environ.get("HARNESS_REDIS_PORT", "0"))
        or cfg.redis.internal_port
        or cfg.redis.external_port
    )
    tasks = discover_tasks_from_redis(spec_id, r_host, r_port)
    if not tasks and spec_file and spec_file.is_file():
        tasks = discover_tasks_from_spec_prs(spec_id, spec_file)
    return tasks


def fetch_file_content_from_repo(repo: str, fpath: str) -> str:
    """Busca o conteúdo decodificado de um arquivo via GitHub API.

    Args:
        repo: Nome do repositório (ex: org/repo).
        fpath: Caminho relativo do arquivo no repositório.

    Returns:
        Conteúdo em texto do arquivo decodificado, ou string vazia se indisponível.
    """
    cmd = ["api", f"repos/{repo}/contents/{fpath}", "--jq", ".content"]
    res = execute_gh_command(cmd)
    if res.returncode == 0 and res.stdout.strip():
        try:
            b64_str = res.stdout.strip().replace("\n", "")
            return base64.b64decode(b64_str).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return ""
    return ""


def enrich_patch_with_source_code(
    repos: set[str],
    spec_file: Path | None,
    diffs_out: Path,
) -> None:
    """Anexa código implementado quando o diff contiver apenas markdown.

    Args:
        repos: Conjunto de repositórios envolvidos.
        spec_file: Caminho do arquivo spec.md para introspecção.
        diffs_out: Arquivo de patch de saída.
    """
    spec_text = (
        spec_file.read_text(encoding="utf-8")
        if spec_file and spec_file.is_file()
        else ""
    )
    pattern = r"[\`\s]([a-zA-Z0-9_\-\./]+\.(?:py|go|ts|js))[\`\s]"
    mentioned_files = set(re.findall(pattern, spec_text))

    enrichment_blocks: list[str] = []
    for repo in sorted(repos):
        for fpath in sorted(mentioned_files):
            code = fetch_file_content_from_repo(repo, fpath)
            if code:
                header = f"\n=== CODIGO FONTE IMPLEMENTADO: {repo}/{fpath} ===\n"
                enrichment_blocks.append(f"{header}{code}\n")

    if enrichment_blocks:
        with open(diffs_out, "a", encoding="utf-8") as file_handle:
            file_handle.writelines(enrichment_blocks)


def collect_diffs(
    tasks: list[tuple[str, int, str]],
    spec_file: Path | None,
    diffs_out: Path,
) -> Path:
    """Coleta os diffs consolidados dos PRs envolvidos e enriquece com código-fonte.

    Args:
        tasks: Lista de tuplas (repositorio, pr_number, task_id).
        spec_file: Arquivo spec.md para enriquecimento de código fonte.
        diffs_out: Caminho do arquivo de patch consolidado.

    Returns:
        Caminho do arquivo gravado.
    """
    diffs_out.parent.mkdir(parents=True, exist_ok=True)
    all_chunks: list[str] = []
    repos: set[str] = set()

    for repo, pr_num, _ in tasks:
        repos.add(repo)
        print(
            f"[Collector] Baixando diff do PR #{pr_num} em {repo}...",
            file=sys.stderr,
        )
        res = execute_gh_command(["pr", "diff", str(pr_num), "--repo", repo])
        all_chunks.append(f"=== REPOSITORIO: {repo} (PR #{pr_num}) ===\n")
        if res.returncode == 0 and res.stdout:
            all_chunks.append(res.stdout)
        all_chunks.append("\n\n")

    diffs_out.write_text("".join(all_chunks), encoding="utf-8")

    patch_text = diffs_out.read_text(encoding="utf-8")
    has_code = any(
        line.startswith("+++ b/") and not line.endswith(".md")
        for line in patch_text.splitlines()
    )

    if not has_code:
        print(
            "[Collector] Diff contem apenas markdown. Coletando codigo...",
            file=sys.stderr,
        )
        enrich_patch_with_source_code(repos, spec_file, diffs_out)

    final_content = diffs_out.read_text(encoding="utf-8").strip()
    if not final_content:
        empty_msg = "# Sem diffs capturados para esta execucao\n"
        diffs_out.write_text(empty_msg, encoding="utf-8")

    return diffs_out


def send_gate_telemetry(
    spec_id: str,
    status: str,
    score: float,
    es_url: str | None = None,
    agent_id: str | None = None,
) -> bool:
    """Envia payload JSON de telemetria do gate para o cluster Elasticsearch.

    Args:
        spec_id: Identificador da especificação.
        status: Status de conclusão do gate (APPROVED ou FAILED).
        score: Nota de conformidade (0.0 a 1.0).
        es_url: Endpoint HTTP do Elasticsearch; se omitido, resolve via config/env.
        agent_id: Identificador opcional do agente de IA executor.

    Returns:
        True se a telemetria foi enviada com sucesso, False caso contrário.
    """
    resolved_url = es_url
    if not resolved_url:
        cfg = get_active_config()
        base_es = (
            os.environ.get("ES_URL", "").rstrip("/")
            or cfg.elasticsearch.external_url.rstrip("/")
            or cfg.elasticsearch.internal_url.rstrip("/")
        )
        es_idx = (
            os.environ.get("ES_INDEX", "")
            or cfg.elasticsearch.index
            or "harness-sensor-telemetry"
        )
        if base_es:
            resolved_url = f"{base_es}/{es_idx}/_doc"
        else:
            resolved_url = ""

    if not resolved_url:
        print("[Collector] URL do Elasticsearch não configurada.", file=sys.stderr)
        return False

    headers = {"Content-Type": "application/json"}
    es_token = os.environ.get("ES_TOKEN", "").strip()
    if es_token:
        headers["Authorization"] = f"Bearer {es_token}"

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "@timestamp": now,
        "sensor_tool": "cross-repo-gate-judge",
        "spec_id": spec_id,
        "status": status,
        "compliance_score": score,
        "evaluator": "llm-as-a-judge",
        "agent_id": agent_id,
        "runtime": agent_id or "default",
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        resolved_url,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 201)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"[Collector] Falha ao enviar telemetria: {exc}", file=sys.stderr)
        return False


def build_argument_parser() -> argparse.ArgumentParser:
    """Constrói o parser de argumentos CLI do coletor."""
    parser = argparse.ArgumentParser(
        description="Coletor de Artefatos e Telemetria do Cross-Repo Gate"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    cfg = get_active_config()
    default_hub = (
        os.environ.get("HARNESS_SPEC_HUB_REPO", "")
        or os.environ.get("SPEC_HUB_REPO", "")
        or cfg.spec_hub.default_repo
    )
    fetch_parser = subparsers.add_parser(
        "fetch-spec", help="Baixa a especificação do hub"
    )
    fetch_parser.add_argument("--spec-id", required=True, help="Identificador da spec")
    fetch_parser.add_argument(
        "--hub-repo",
        default=default_hub,
        help="Repositório do hub",
    )
    fetch_parser.add_argument(
        "--out-file", default="gate_artifacts/spec.md", help="Arquivo de saída"
    )

    diff_parser = subparsers.add_parser(
        "collect-diffs", help="Coleta diffs e código fonte"
    )
    diff_parser.add_argument("--spec-id", required=True, help="Identificador da spec")
    diff_parser.add_argument(
        "--spec-file", default="gate_artifacts/spec.md", help="Arquivo spec.md"
    )
    diff_parser.add_argument(
        "--tasks-out",
        default="gate_artifacts/tasks.txt",
        help="Arquivo de saída das tarefas",
    )
    diff_parser.add_argument(
        "--diffs-out",
        default="gate_artifacts/all_diffs.patch",
        help="Arquivo de patch unificado",
    )
    redis_h = (
        os.environ.get("HARNESS_REDIS_HOST", "")
        or cfg.redis.internal_host
        or cfg.redis.external_host
    )
    redis_p = int(
        os.environ.get("HARNESS_REDIS_PORT", "0")
        or cfg.redis.internal_port
        or cfg.redis.external_port
        or 0
    )
    diff_parser.add_argument("--redis-host", default=redis_h, help="Host do Redis")
    diff_parser.add_argument(
        "--redis-port", type=int, default=redis_p, help="Porta do Redis"
    )

    telemetry_parser = subparsers.add_parser(
        "send-telemetry", help="Envia telemetria para o Elasticsearch"
    )
    telemetry_parser.add_argument(
        "--spec-id", required=True, help="Identificador da spec"
    )
    telemetry_parser.add_argument("--status", default="FAILED", help="Status do gate")
    telemetry_parser.add_argument(
        "--score", type=float, default=0.0, help="Nota de conformidade"
    )
    base_es = (
        os.environ.get("ES_URL", "").rstrip("/")
        or cfg.elasticsearch.external_url.rstrip("/")
        or cfg.elasticsearch.internal_url.rstrip("/")
    )
    es_idx = os.environ.get("ES_INDEX", "") or cfg.elasticsearch.index
    default_es = f"{base_es}/{es_idx}/_doc" if base_es and es_idx else ""
    telemetry_parser.add_argument(
        "--es-url", default=default_es, help="URL do Elasticsearch"
    )
    telemetry_parser.add_argument(
        "--agent", dest="agent_id", default=None, help="Identificador do agente executor"
    )

    return parser


def main() -> None:
    """Ponto de entrada de execução da CLI do coletor."""
    parser = build_argument_parser()
    args = parser.parse_args()

    if args.command == "fetch-spec":
        fetch_spec(
            spec_id=args.spec_id,
            hub_repo=args.hub_repo,
            out_file=Path(args.out_file),
        )
        print(f"[Collector] Spec baixada com sucesso em {args.out_file}")

    elif args.command == "collect-diffs":
        spec_path = Path(args.spec_file) if args.spec_file else None
        tasks = discover_tasks(
            spec_id=args.spec_id,
            spec_file=spec_path,
            redis_host=args.redis_host,
            redis_port=args.redis_port,
        )

        tasks_out = Path(args.tasks_out)
        tasks_out.parent.mkdir(parents=True, exist_ok=True)
        task_lines = [f"{repo}:{pr}:{tid}\n" for repo, pr, tid in tasks]
        tasks_out.write_text("".join(task_lines), encoding="utf-8")
        print(f"[Collector] {len(tasks)} tarefas registradas em {args.tasks_out}")

        collect_diffs(
            tasks=tasks,
            spec_file=spec_path,
            diffs_out=Path(args.diffs_out),
        )
        print(f"[Collector] Diffs coletados com sucesso em {args.diffs_out}")

    elif args.command == "send-telemetry":
        send_gate_telemetry(
            spec_id=args.spec_id,
            status=args.status,
            score=args.score,
            es_url=args.es_url,
            agent_id=getattr(args, "agent_id", None),
        )


if __name__ == "__main__":
    main()
