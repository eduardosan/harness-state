def resolve_redis_host(provided_host: str = "") -> str:
    """Resolve o host Redis considerando env vars e fallback local."""
    return (
        provided_host
        or os.environ.get("HARNESS_REDIS_HOST", "")
        or os.environ.get("REDIS_HOST", "")
        or "127.0.0.1"
    )


def resolve_redis_port(provided_port: int = 0) -> int:
    """Resolve a porta do Redis considerando env vars e fallback 6379."""
    if provided_port:
        return provided_port
    env_port = os.environ.get("HARNESS_REDIS_PORT") or os.environ.get("REDIS_PORT")
    if env_port:
        try:
            return int(env_port)
        except ValueError:
            LOGGER.warning("Porta de Redis inválida em env var: %s", env_port)
    return 6379


def resolve_default_spec_hub_repo(provided_repo: str = "") -> str:
    """Resolve o repositório padrão do spec-hub considerando env vars."""
    return (
        provided_repo
        or os.environ.get("HARNESS_SPEC_HUB_REPO", "")
        or os.environ.get("SPEC_HUB_REPO", "")
        or "paralax-ia/paralax-spec-hub"
    )


def resolve_default_flywheel_repo(provided_repo: str = "") -> str:
    """Resolve o repositório padrão do flywheel considerando env vars."""
    return (
        provided_repo
        or os.environ.get("HARNESS_FLYWHEEL_REPO", "")
        or os.environ.get("FLYWHEEL_REPO", "")
        or "paralax-ia/agentic-flywheel"
    )


"""Módulo de Fechamento Transacional do Cross-Repo Harness Gate."""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import redis

LOGGER = logging.getLogger(__name__)

from harness_state.capabilities import DomainInspector
from harness_state.client import (
    derive_hub_ecosystem,
    parse_spec_reference,
    redis_spec_key,
)
from harness_state.contracts import ContractValidationResult
from harness_state.spec.fanout import mark_repo_spec_status


@dataclass
class TransactionalGateResult:
    """Resultado da execução do fechamento transacional do gate."""

    decision: str
    all_merged: bool = False
    merged_prs: list[tuple[str, int]] = field(default_factory=list)
    prompts_promoted: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class GateGitHubClientProtocol(Protocol):
    """Protocolo definindo as operações com a API do GitHub requeridas pelo Gate."""

    def add_label(self, repo: str, pr_number: int, label: str) -> None:
        """Adiciona uma label a um Pull Request."""
        ...

    def merge_pr(self, repo: str, pr_number: int, merge_method: str = "squash") -> bool:
        """Executa o merge de um Pull Request."""
        ...

    def comment_pr(self, repo: str, pr_number: int, comment: str) -> None:
        """Adiciona um comentário em um Pull Request."""
        ...

    def close_issue(
        self, repo: str, issue_number: int, comment: str | None = None
    ) -> bool:
        """Fecha uma issue no repositório de origem."""
        ...


class GateGitHubCLIClient:
    """Implementação concreta de operações de gate utilizando o binário CLI gh."""

    def __init__(self, token: str | None = None):
        """Inicializa o cliente com token opcional de autenticação.

        Args:
            token: Token de autenticação da GitHub App ou Personal Access Token.
        """
        self.token = (
            token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        )

    def _execute_gh(self, args: list[str]) -> subprocess.CompletedProcess:
        """Executa um comando gh injetando as variáveis de ambiente necessárias.

        Args:
            args: Argumentos a serem passados para a ferramenta CLI gh.

        Returns:
            Instância de CompletedProcess com a saída e código de término.
        """
        env = os.environ.copy()
        if self.token:
            env["GH_TOKEN"] = self.token
            env["GITHUB_TOKEN"] = self.token
        return subprocess.run(
            ["gh", *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def add_label(self, repo: str, pr_number: int, label: str) -> None:
        """Adiciona uma label a um Pull Request específico via CLI gh.

        Args:
            repo: Identificador do repositório no formato 'owner/name'.
            pr_number: Número do Pull Request.
            label: Nome da label a ser aplicada.
        """
        self._execute_gh(
            ["pr", "edit", str(pr_number), "-R", repo, "--add-label", label]
        )

    def merge_pr(self, repo: str, pr_number: int, merge_method: str = "squash") -> bool:
        """Realiza o merge automático de um Pull Request via CLI gh.

        Args:
            repo: Identificador do repositório no formato 'owner/name'.
            pr_number: Número do Pull Request.
            merge_method: Estratégia de merge ('squash', 'merge', 'rebase').

        Returns:
            True se o merge foi concluído com sucesso, False caso contrário.
        """
        args = [
            "pr",
            "merge",
            str(pr_number),
            "-R",
            repo,
            f"--{merge_method}",
            "--delete-branch",
        ]
        result = self._execute_gh(args)
        return result.returncode == 0

    def comment_pr(self, repo: str, pr_number: int, comment: str) -> None:
        """Adiciona um comentário em um Pull Request via CLI gh.

        Args:
            repo: Identificador do repositório no formato 'owner/name'.
            pr_number: Número do Pull Request.
            comment: Conteúdo textual do comentário.
        """
        self._execute_gh(
            ["pr", "comment", str(pr_number), "-R", repo, "--body", comment]
        )

    def close_issue(
        self, repo: str, issue_number: int, comment: str | None = None
    ) -> bool:
        """Fecha uma issue no repositório de origem via CLI gh.

        Args:
            repo: Identificador do repositório no formato 'owner/name'.
            issue_number: Número da issue a ser fechada.
            comment: Comentário opcional de encerramento.

        Returns:
            True se fechada com sucesso, False caso contrário.
        """
        args = ["issue", "close", str(issue_number), "-R", repo]
        if comment:
            args.extend(["--comment", comment])
        res = self._execute_gh(args)
        return res.returncode == 0


def sync_task_to_state_tracker(
    spec_id: str,
    task_id: str,
    status: str,
    pr_number: int | None = None,
    worker: str = "cross-repo-gate",
    ecosystem: str = "",
) -> None:
    """Atualiza o estado de uma subtarefa no State Tracker remoto.

    Args:
        spec_id: Identificador da especificação.
        task_id: Identificador da tarefa.
        status: Novo estado (ex: APPROVED, FAILED).
        pr_number: Número do PR associado.
        worker: Nome do worker responsável.
        ecosystem: Namespace do ecossistema (hub); com valor, a referência
            enviada ao CLI é `{ecosistema}/{spec_id}` (SPEC-005 C1).
    """
    harness_state_bin = shutil.which("harness")
    if harness_state_bin:
        reference = f"{ecosystem}/{spec_id}" if ecosystem else spec_id
        cmd = [
            harness_state_bin,
            "update",
            reference,
            task_id,
            status,
            "--worker",
            worker,
        ]
        if pr_number is not None:
            cmd.extend(["--pr", str(pr_number)])
        subprocess.run(cmd, capture_output=True, text=True, check=False)
        return

    # Fallback: persistencia direta no Redis
    host = resolve_redis_host()
    port = resolve_redis_port()
    try:
        client = redis.Redis(
            host=host, port=port, decode_responses=True, socket_timeout=5
        )
        ecosystem, parsed_id = parse_spec_reference(spec_id)
        key = redis_spec_key(ecosystem, parsed_id)
        raw_data = client.get(key)
        if raw_data:
            spec_data = json.loads(raw_data)
            tasks = spec_data.get("tasks", {})
            if task_id in tasks:
                tasks[task_id]["status"] = status
                tasks[task_id]["last_worker"] = worker
                if pr_number is not None:
                    tasks[task_id]["pr_number"] = pr_number
                client.set(key, json.dumps(spec_data))
    except (redis.RedisError, json.JSONDecodeError, OSError) as exc:
        LOGGER.debug("Erro ao persistir status no Redis: %s", exc)


class TransactionalGateClosure:
    """Coordenador do fechamento transacional do Cross-Repo Harness Gate."""

    def __init__(
        self,
        github_client: GateGitHubClientProtocol,
        spec_hub_repo: str = "",
        hub_pr_number: int | None = None,
        spec_hub_dir: Path | None = None,
    ):
        """Inicializa o coordenador de fechamento transacional.

        Args:
            github_client: Cliente para interagir com a API do GitHub.
            spec_hub_repo: Repositório central de especificações.
            hub_pr_number: Número opcional do PR central no spec-hub.
            spec_hub_dir: Caminho local do spec-hub para atualizar capabilities.
        """
        self.github_client = github_client
        self.spec_hub_repo = resolve_default_spec_hub_repo(spec_hub_repo or "")
        self.hub_pr_number = hub_pr_number
        self.spec_hub_dir = spec_hub_dir

    def _promote_declared_prompts(
        self,
        prompts: list[str] | None,
        prompts_promoted: list[str],
        errors: list[str],
    ) -> bool:
        """Promove os prompts declarados para 'production' no Langfuse.

        A progressão é atômica: qualquer falha de promoção bloqueia o Gate 5.

        Args:
            prompts: Lista de nomes de prompts declarados.
            prompts_promoted: Lista mutável onde prompts promovidos são adicionados.
            errors: Lista mutável onde falhas de promoção são registradas.

        Returns:
            True quando o fechamento deve ser abortado (promoção bloqueada).
        """
        if not prompts:
            return False
        from harness_state.prompt_promotion import promote_prompts_to_production

        outcome = promote_prompts_to_production(prompts)
        prompts_promoted.extend(outcome.promoted)
        errors.extend(outcome.errors)
        return outcome.blocked

    def _mark_local_spoke_spec_implemented(self, repo: str, spec_id: str) -> None:
        """Marca a sub-spec local do repositório spoke como IMPLEMENTED se existir.

        Args:
            repo: Identificador do repositório (ex: org/repo).
            spec_id: Identificador da especificação.
        """
        repo_short = repo.split("/")[-1]
        for cand_dir in (
            Path(repo_short),
            Path.cwd() / repo_short,
            Path.cwd().parent / repo_short,
        ):
            if cand_dir.is_dir() and (cand_dir / "specs").is_dir():
                mark_repo_spec_status(cand_dir, spec_id, "IMPLEMENTED")
                break

    def _approve_and_merge_spoke_tasks(
        self,
        spec_id: str,
        judge_score: float | None,
        tasks_info: list[dict],
        merged_prs: list[tuple[str, int]],
        errors: list[str],
    ) -> None:
        """Realiza o merge dos PRs dos spokes e fecha as issues correspondentes.

        Args:
            spec_id: Identificador da especificação.
            judge_score: Nota de conformidade do Judge (None = skip explícito).
            tasks_info: Metadados das tarefas e PRs.
            merged_prs: Lista mutável de PRs mergeados.
            errors: Lista mutável de erros ocorridos.
        """
        for task in tasks_info:
            repo = task.get("repo", "")
            pr_num = task.get("pr_number")
            task_id = task.get("task_id", "")

            if repo and pr_num:
                self.github_client.add_label(repo, pr_num, "harness-approved")
                if self.github_client.merge_pr(repo, pr_num):
                    merged_prs.append((repo, pr_num))
                    self._mark_local_spoke_spec_implemented(repo, spec_id)
                else:
                    errors.append(f"Falha ao realizar merge no PR #{pr_num} de {repo}")

            issue_num = task.get("issue_number")
            if repo and issue_num:
                assert pr_num is not None, f"Task {task_id} sem PR mergeado"
                close_comment = self._build_spoke_close_comment(
                    task_id=task_id,
                    spec_id=spec_id,
                    pr_num=pr_num,
                    judge_score=judge_score,
                )
                self.github_client.close_issue(repo, issue_num, close_comment)

            if task_id:
                sync_task_to_state_tracker(
                    ecosystem=self._hub_ecosystem(),
                    spec_id=spec_id,
                    task_id=task_id,
                    status="APPROVED",
                    pr_number=pr_num,
                )

    def _hub_ecosystem(self) -> str:
        """Deriva o namespace do ecossistema a partir do hub resolvido (SPEC-005 C1).

        Returns:
            Nome curto do ecossistema (vazio quando não há hub).
        """
        if self.spec_hub_dir is None:
            return ""
        return derive_hub_ecosystem(self.spec_hub_dir)

    def _build_spoke_close_comment(
        self,
        task_id: str,
        spec_id: str,
        pr_num: int,
        judge_score: float | None,
    ) -> str:
        """Monta o comentário de fechamento da issue da subtarefa no spoke.

        Args:
            task_id: Identificador da subtarefa.
            spec_id: Identificador da especificação.
            pr_num: Número do PR mergeado.
            judge_score: Nota do Judge (None = skip explícito de entregas não-código).

        Returns:
            Comentário completo para close_issue.
        """
        header = (
            f"✅ Subtarefa `{task_id}` concluída e aprovada pelo "
            f"Cross-Repo Harness Gate para `{spec_id}`.\n\n"
            f"- Pull Request #{pr_num} mergeado com sucesso transacional.\n"
        )
        if judge_score is not None:
            return (
                f"{header}- Conformidade validada pelo LLM-as-a-Judge "
                f"com nota {judge_score:.2f}."
            )
        return (
            f"{header}- Conformidade validada pelo LLM-as-a-Judge com "
            "skip explícito (deliverables não-código)."
        )

    def _approve_and_merge_hub_pr(
        self,
        judge_score: float | None,
        judge_reason: str,
        contract_result: ContractValidationResult,
        merged_prs: list[tuple[str, int]],
    ) -> None:
        """Comenta, aplica label e faz merge do PR central no Spec-Hub.

        Args:
            judge_score: Pontuação de conformidade (None = skip explícito).
            judge_reason: Justificativa do LLM Judge.
            contract_result: Resultado da validação de contratos.
            merged_prs: Lista mutável onde o PR do hub é adicionado se mergeado.
        """
        if not self.hub_pr_number:
            return
        num_ep = len(contract_result.endpoints)
        score_text = (
            f"`{judge_score:.2f}`"
            if judge_score is not None
            else "`skip (sem evidência de código)`"
        )
        approval_msg = (
            f"## 🏆 Cross-Repo Harness Gate: Aprovado!\n\n"
            f"- **Score de Conformidade:** {score_text}\n"
            f"- **Avaliação LLM-as-a-Judge:** {judge_reason}\n"
            f"- **Validação de Contratos:** Válida ({num_ep} endpoints)\n\n"
            "Pull Requests dos spokes mergeados com sucesso transacional."
        )
        self.github_client.comment_pr(
            self.spec_hub_repo, self.hub_pr_number, approval_msg
        )
        self.github_client.add_label(
            self.spec_hub_repo, self.hub_pr_number, "harness-approved"
        )
        if self.github_client.merge_pr(self.spec_hub_repo, self.hub_pr_number):
            merged_prs.append((self.spec_hub_repo, self.hub_pr_number))

    def _reject_gate_prs(
        self,
        spec_id: str,
        judge_status: str,
        judge_reason: str,
        contract_result: ContractValidationResult,
        tasks_info: list[dict],
        errors: list[str],
    ) -> TransactionalGateResult:
        """Emite feedback prescritivo de reprovação nos PRs sem realizar merge.

        Args:
            spec_id: Identificador da especificação.
            judge_status: Status retornado pelo Judge.
            judge_reason: Justificativa do Judge.
            contract_result: Resultado de validação de contratos.
            tasks_info: Lista de tarefas e PRs.
            errors: Lista de erros acumulados.

        Returns:
            TransactionalGateResult com decisão FAILED.
        """
        rejection_details = []
        if judge_status != "APPROVED":
            rejection_details.append(f"• **Divergência LLM-Judge:** {judge_reason}")
        if not contract_result.valid:
            rejection_details.append(
                f"• **Violação de Contratos:** {', '.join(contract_result.errors)}"
            )

        rejection_msg = (
            "## ⚠️ Cross-Repo Harness Gate: Reprovado\n\n"
            "O Cross-Repo Gate identificou pendências de conformidade:\n\n"
            + "\n".join(rejection_details)
            + "\n\nPor favor, corrija as divergências apontadas acima para "
            "autorizar o merge transacional."
        )

        for task in tasks_info:
            repo = task.get("repo", "")
            pr_num = task.get("pr_number")
            task_id = task.get("task_id", "")
            if repo and pr_num:
                self.github_client.comment_pr(repo, pr_num, rejection_msg)
            if task_id:
                sync_task_to_state_tracker(
                    ecosystem=self._hub_ecosystem(),
                    spec_id=spec_id,
                    task_id=task_id,
                    status="FAILED",
                    pr_number=pr_num,
                )

        if self.hub_pr_number:
            self.github_client.comment_pr(
                self.spec_hub_repo, self.hub_pr_number, rejection_msg
            )

        return TransactionalGateResult(
            decision="FAILED",
            all_merged=False,
            merged_prs=[],
            errors=errors,
        )

    def execute(
        self,
        spec_id: str,
        judge_status: str,
        judge_score: float | None,
        judge_reason: str,
        contract_result: ContractValidationResult,
        tasks_info: list[dict],
        prompts: list[str] | None = None,
    ) -> TransactionalGateResult:
        """Executa a decisão transacional sobre os repositórios envolvidos.

        Args:
            spec_id: Identificador da especificação.
            judge_status: Status retornado pelo avaliador LLM ('APPROVED' ou 'FAILED').
            judge_score: Pontuação de conformidade (0.0 a 1.0); None quando o
                Gate seguiu como skip (sem evidência de código).
            judge_reason: Justificativa detalhada emitida pelo LLM Judge.
            contract_result: Resultado da validação computacional de contratos.
            tasks_info: Lista de dicionários com dados de repositórios e PRs.
            prompts: Lista opcional de nomes de prompts no Langfuse para promoção.

        Returns:
            Instância de TransactionalGateResult com a decisão e ações executadas.
        """
        is_approved = (judge_status == "APPROVED") and contract_result.valid
        merged_prs: list[tuple[str, int]] = []
        prompts_promoted: list[str] = []
        errors: list[str] = []

        if not is_approved:
            return self._reject_gate_prs(
                spec_id=spec_id,
                judge_status=judge_status,
                judge_reason=judge_reason,
                contract_result=contract_result,
                tasks_info=tasks_info,
                errors=errors,
            )

        promotion_blocked = self._promote_declared_prompts(
            prompts, prompts_promoted, errors
        )
        if promotion_blocked:
            return TransactionalGateResult(
                decision="FAILED",
                all_merged=False,
                merged_prs=[],
                prompts_promoted=prompts_promoted,
                errors=errors,
            )
        self._approve_and_merge_spoke_tasks(
            spec_id=spec_id,
            judge_score=judge_score,
            tasks_info=tasks_info,
            merged_prs=merged_prs,
            errors=errors,
        )
        self._approve_and_merge_hub_pr(
            judge_score=judge_score,
            judge_reason=judge_reason,
            contract_result=contract_result,
            merged_prs=merged_prs,
        )

        if self.spec_hub_dir and self.spec_hub_dir.is_dir():
            inspector = DomainInspector()
            inspector.update_spec_status(self.spec_hub_dir, spec_id, "MERGED")
            inspector.sync_all(self.spec_hub_dir)

        return TransactionalGateResult(
            decision="APPROVED",
            all_merged=len(errors) == 0,
            merged_prs=merged_prs,
            prompts_promoted=prompts_promoted,
            errors=errors,
        )


def is_spec_ready_for_gate(
    spec_id: str,
    redis_host: str = "",
    redis_port: int = 0,
) -> bool:
    """Verifica se uma especificação está pronta para ser avaliada pelo Gate.

    Args:
        spec_id: Identificador da especificação (ex: SPEC-001).
        redis_host: Endereço do host Redis.
        redis_port: Porta do serviço Redis.

    Returns:
        True se a especificação estiver pronta ou for tarefa avulsa,
        False se houver tarefas ativas.
    """
    if not spec_id:
        return False

    host = resolve_redis_host(redis_host or "")
    port = resolve_redis_port(redis_port)
    try:
        client = redis.Redis(
            host=host,
            port=port,
            decode_responses=True,
            socket_timeout=3,
        )
        ecosystem, parsed_id = parse_spec_reference(spec_id)
        data = client.get(redis_spec_key(ecosystem, parsed_id))
        if data:
            spec_info = json.loads(data)
            status = spec_info.get("status", "")
            if status in ("READY", "APPROVED"):
                return True
            tasks = spec_info.get("tasks", {})
            if tasks:
                return all(
                    t.get("status") in ("READY", "APPROVED") for t in tasks.values()
                )
    except (redis.RedisError, json.JSONDecodeError, OSError) as exc:
        LOGGER.warning("[Gate] Aviso ao consultar Redis para prontidão: %s", exc)
        return True

    return True


def dispatch_cross_repo_gate(
    spec_id: str,
    hub_repo: str = "",
    flywheel_repo: str = "",
    token: str | None = None,
) -> bool:
    """Dispara o evento repository_dispatch para o Cross-Repo Harness Gate.

    Args:
        spec_id: Identificador da especificação a ser validada.
        hub_repo: Repositório central onde residem as especificações SDD.
        flywheel_repo: Repositório central do flywheel orchestrator.
        token: Token de autenticação GitHub (GH_TOKEN ou FLYWHEEL_DISPATCH_TOKEN).

    Returns:
        True se o dispatch foi submetido com êxito, False caso contrário.
    """
    target_hub = resolve_default_spec_hub_repo(hub_repo or "")
    target_flywheel = resolve_default_flywheel_repo(flywheel_repo or "")

    auth_token = (
        token
        or os.environ.get("FLYWHEEL_DISPATCH_TOKEN")
        or os.environ.get("GH_TOKEN")
        or os.environ.get("GITHUB_TOKEN")
    )
    env = os.environ.copy()
    if auth_token:
        env["GH_TOKEN"] = auth_token
        env["GITHUB_TOKEN"] = auth_token

    cmd = [
        "gh",
        "api",
        f"repos/{target_flywheel}/dispatches",
        "-f",
        "event_type=cross-repo-gate",
        "-f",
        f"client_payload[spec_id]={spec_id}",
        "-f",
        f"client_payload[spec_repo]={target_hub}",
    ]
    res = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if res.returncode == 0:
        print(
            f"[Gate] 🚀 repository_dispatch 'cross-repo-gate' enviado para "
            f"{target_flywheel} (spec: {spec_id})."
        )
        return True

    err_msg = res.stderr.strip()
    print(
        f"[Gate] ⚠️ Falha ao enviar repository_dispatch ({res.returncode}): {err_msg}",
        file=sys.stderr,
    )
    return False


def trigger_gate_if_ready(
    spec_id: str,
    hub_repo: str = "",
    flywheel_repo: str = "",
    redis_host: str = "",
    redis_port: int = 0,
    token: str | None = None,
) -> bool:
    """Verifica a prontidão da especificação e dispara o gate se pronta.

    Args:
        spec_id: Identificador da especificação.
        hub_repo: Repositório do spec hub.
        flywheel_repo: Repositório central do flywheel.
        redis_host: Host do servidor Redis.
        redis_port: Porta do servidor Redis.
        token: Token opcional de autenticação.

    Returns:
        True se o gate foi disparado, False caso ainda existam pendências.
    """
    if not is_spec_ready_for_gate(spec_id, redis_host, redis_port):
        print(
            f"[Gate] Spec {spec_id} ainda possui tarefas em andamento. "
            "O Gate será acionado após a conclusão das demais."
        )
        return False

    return dispatch_cross_repo_gate(
        spec_id=spec_id,
        hub_repo=hub_repo,
        flywheel_repo=flywheel_repo,
        token=token,
    )


def parse_tasks_file(tasks_file_path: str | None) -> list[dict]:
    """Lê o arquivo de tarefas (formato `repo:pr:tid[:issue]`) em lista de dicts.

    Args:
        tasks_file_path: Caminho para o arquivo de tarefas ou None.

    Returns:
        Lista de dicionários representando cada tarefa do Gate.
    """
    if not tasks_file_path:
        return []
    path = Path(tasks_file_path)
    if not path.is_file():
        return []

    tasks_info: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        parts = stripped.split(":")
        if len(parts) < 2:
            continue
        repo_slug = parts[0]
        pr_num = int(parts[1]) if parts[1].isdigit() else 0
        tid = parts[2] if len(parts) > 2 else ""
        issue_num = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else None
        tasks_info.append(
            {
                "repo": repo_slug,
                "pr_number": pr_num,
                "task_id": tid,
                "issue_number": issue_num,
            }
        )
    return tasks_info


def load_contract_result_file(
    contract_result_path: str | None,
) -> ContractValidationResult:
    """Carrega um `ContractValidationResult` a partir de um arquivo JSON opcional.

    Args:
        contract_result_path: Caminho do JSON de contrato ou None.

    Returns:
        Instância de `ContractValidationResult`.
    """
    if not contract_result_path:
        return ContractValidationResult(valid=True)
    path = Path(contract_result_path)
    if not path.is_file():
        return ContractValidationResult(valid=True)

    c_data = json.loads(path.read_text(encoding="utf-8"))
    return ContractValidationResult(
        valid=c_data.get("valid", True),
        errors=c_data.get("errors", []),
        endpoints=c_data.get("endpoints", []),
        schemas=c_data.get("schemas", []),
    )


def run_trigger_if_ready_cli(
    args_list: list[str],
    default_hub: str,
    default_flywheel: str,
) -> None:
    """Executa o subcomando `trigger-if-ready` da CLI do Gate.

    Args:
        args_list: Argumentos subsequentes a `trigger-if-ready`.
        default_hub: Repositório padrão do spec-hub.
        default_flywheel: Repositório padrão do flywheel.
    """
    parser = argparse.ArgumentParser(
        description="Verifica e dispara o Gate se a spec estiver pronta"
    )
    parser.add_argument("--spec-id", required=True, help="ID da especificação")
    parser.add_argument(
        "--hub-repo",
        default=default_hub,
        help="Repositório central do spec hub",
    )
    parser.add_argument(
        "--flywheel-repo",
        default=default_flywheel,
        help="Repositório do orquestrador",
    )
    parsed = parser.parse_args(args_list)
    triggered = trigger_gate_if_ready(
        spec_id=parsed.spec_id,
        hub_repo=parsed.hub_repo,
        flywheel_repo=parsed.flywheel_repo,
    )
    if not triggered:
        print(f"[Gate] Gatilho não disparado para spec {parsed.spec_id}.")


def run_gate_cli(argv: list[str] | None = None) -> None:
    """CLI para acionamento de fechamento transacional ou disparo do Gate."""
    args_list = argv if argv is not None else sys.argv[1:]

    default_hub = resolve_default_spec_hub_repo()
    default_flywheel = resolve_default_flywheel_repo()

    if args_list and args_list[0] == "trigger-if-ready":
        run_trigger_if_ready_cli(args_list[1:], default_hub, default_flywheel)
        return

    parser = argparse.ArgumentParser(
        description="Fechamento Transacional Cross-Repo Gate SDD"
    )
    parser.add_argument("--spec-id", required=True, help="ID da especificação")
    parser.add_argument(
        "--judge-result", required=True, help="Caminho do JSON da avaliação do Judge"
    )
    parser.add_argument(
        "--contract-result",
        default=None,
        help="Caminho opcional do JSON de validação de contratos",
    )
    parser.add_argument(
        "--tasks-file",
        default=None,
        help="Caminho do arquivo com a lista de tarefas (formato repo:pr:tid)",
    )
    parser.add_argument(
        "--hub-repo",
        default=default_hub,
        help="Repositório central do spec-hub",
    )
    parser.add_argument(
        "--hub-pr",
        type=int,
        default=None,
        help="Número do PR da spec no spec-hub",
    )
    parser.add_argument(
        "--spec-hub-dir",
        default=None,
        help="Caminho do spec-hub para sincronização de capabilities",
    )
    args = parser.parse_args(args_list)

    judge_data = json.loads(Path(args.judge_result).read_text(encoding="utf-8"))
    judge_status = judge_data.get("status", "FAILED")
    raw_score = judge_data.get("compliance_score")
    judge_score = float(raw_score) if raw_score is not None else None
    judge_reason = judge_data.get("reason", "Sem justificativa informada.")

    contract_res = load_contract_result_file(args.contract_result)
    tasks_info = parse_tasks_file(args.tasks_file)

    client = GateGitHubCLIClient()
    closure = TransactionalGateClosure(
        github_client=client,
        spec_hub_repo=args.hub_repo,
        hub_pr_number=args.hub_pr,
        spec_hub_dir=Path(args.spec_hub_dir) if args.spec_hub_dir else None,
    )

    result = closure.execute(
        spec_id=args.spec_id,
        judge_status=judge_status,
        judge_score=judge_score,
        judge_reason=judge_reason,
        contract_result=contract_res,
        tasks_info=tasks_info,
    )

    print(
        json.dumps(
            {
                "decision": result.decision,
                "all_merged": result.all_merged,
                "merged_prs": result.merged_prs,
                "errors": result.errors,
            },
            indent=2,
        )
    )

    if result.decision != "APPROVED":
        sys.exit(1)


if __name__ == "__main__":
    run_gate_cli()
