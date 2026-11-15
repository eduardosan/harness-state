"""Bootstrap idempotente de labels de execução da esteira federada."""

import subprocess
from collections.abc import Callable

LABEL_COLORS = {
    "agent-run": "1D76DB",
    "agent-spec": "0E8A16",
    "agent-local": "BFDADC",
}


def ensure_labels_exist(
    labels: list[str],
    run_gh: Callable[[list[str]], subprocess.CompletedProcess],
    repo: str | None = None,
) -> None:
    """Garante que as labels de execução existam no repo (`label create --force`).

    Args:
        labels: Nomes das labels a garantir.
        run_gh: Callable que executa a CLI gh recebendo a lista de argumentos
            SEM o binário (`gh`) e retornando `CompletedProcess`.
        repo: Slug `owner/name` do repositório (usado via `-R`). Quando None,
            o gh resolve o repositório pelo diretório corrente do runner.

    Raises:
        RuntimeError: Quando o bootstrap falha (permissão/rede).
    """
    desc = "Execução da esteira federada via Agentic Flywheel (SDD)"
    for name in labels:
        args = ["label", "create", name]
        if repo:
            args.extend(["-R", repo])
        args.extend(
            [
                "--color",
                LABEL_COLORS.get(name, "D4C5F9"),
                "--description",
                desc,
                "--force",
            ]
        )
        result = run_gh(args)
        if result.returncode != 0:
            err_msg = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(
                f"gh label create '{name}' falhou"
                f"{f' em {repo}' if repo else ''}: "
                f"{err_msg} — as labels "
                f"{', '.join(labels)} são obrigatórias para a esteira; reveja as "
                "permissões da App/PAT (Issues) ou crie-as manualmente."
            )
