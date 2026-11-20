"""Motor de reconciliação de deltas de arquitetura e código de specs (SPEC-011)."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml

from harness_state.models import (
    RevisionType,
    SpecEvolutionPlan,
    SpecRevision,
    SpecRun,
    SubTask,
    TaskState,
)
from harness_state.spec.lifecycle import extract_yaml_frontmatter
from harness_state.spec_parser import parse_spec_tasks

CONTRACT_PATTERN = re.compile(r"def\s+([a-zA-Z0-9_]+)\s*\(", re.MULTILINE)
CLASS_PATTERN = re.compile(r"class\s+([a-zA-Z0-9_]+)\b", re.MULTILINE)


def extract_contracts(text: str) -> set[str]:
    """Extrai assinaturas e símbolos contratuais declarados em blocos de código.

    Args:
        text: Texto contendo contratos em markdown ou blocos de código.

    Returns:
        Conjunto de símbolos contratuais extraídos.
    """
    contracts: set[str] = set()
    for match in CONTRACT_PATTERN.finditer(text):
        contracts.add(f"def {match.group(1)}")
    for match in CLASS_PATTERN.finditer(text):
        contracts.add(f"class {match.group(1)}")
    return contracts


def parse_semver(version_str: str) -> tuple[int, int, int]:
    """Interpreta string SemVer em tupla de inteiros (major, minor, patch).

    Args:
        version_str: String de versão (ex: '1.2.3').

    Returns:
        Tupla (major, minor, patch).
    """
    cleaned = version_str.strip().lstrip("v")
    parts = cleaned.split(".")
    try:
        major = int(parts[0]) if len(parts) > 0 else 1
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return major, minor, patch
    except (ValueError, IndexError):
        return 1, 0, 0


def bump_semver(current_version: str, revision_type: RevisionType) -> str:
    """Calcula a próxima versão SemVer de acordo com o tipo de revisão.

    Args:
        current_version: Versão SemVer atual.
        revision_type: Tipo de revisão (MAJOR_BREAKING, MINOR_EVOLUTION, PATCH_CORRECTION).

    Returns:
        Próxima string de versão SemVer.
    """
    major, minor, patch = parse_semver(current_version)
    if revision_type == RevisionType.MAJOR_BREAKING:
        return f"{major + 1}.0.0"
    if revision_type == RevisionType.MINOR_EVOLUTION:
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


class SpecEvolutionEngine:
    """Motor de reconciliação de deltas de arquitetura e código de specs."""

    def __init__(self, spec_hub_dir: Path) -> None:
        """Inicializa o motor com o diretório raiz do spec-hub.

        Args:
            spec_hub_dir: Raiz do repositório spec-hub.
        """
        self.spec_hub_dir = spec_hub_dir

    def analyze_spec_evolution(
        self,
        spec_path: Path,
        instruction: str,
        current_run: SpecRun | None = None,
        previous_spec_content: str | None = None,
    ) -> SpecEvolutionPlan:
        """Compara a spec modificada com a baseline e gera o plano de evolução.

        Args:
            spec_path: Caminho da especificação modificada.
            instruction: Instrução do operador descrevendo a alteração.
            current_run: Estado persistido anterior da especificação no StateStore.
            previous_spec_content: Conteúdo anterior da spec para diff contratual.

        Returns:
            Instância de SpecEvolutionPlan contendo tarefas congeladas e a executar.
        """
        content = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""
        frontmatter, _ = extract_yaml_frontmatter(content)
        spec_id = str(frontmatter.get("spec_id") or spec_path.stem)

        current_version = "1.0.0"
        if current_run and current_run.spec_version:
            current_version = current_run.spec_version
        elif frontmatter.get("spec_version"):
            current_version = str(frontmatter.get("spec_version"))

        frozen_tasks, tasks_to_execute = self._classify_tasks(
            content=content, spec_id=spec_id, current_run=current_run
        )

        has_breaking = self._detect_breaking_changes(
            current_content=content,
            previous_content=previous_spec_content,
            has_frozen=len(frozen_tasks) > 0,
        )

        rev_type = RevisionType.MAJOR_BREAKING if has_breaking else RevisionType.MINOR_EVOLUTION
        target_version = bump_semver(current_version, rev_type)

        affected_repos = sorted({task.repo for task in tasks_to_execute if task.repo})

        return SpecEvolutionPlan(
            spec_id=spec_id,
            current_version=current_version,
            target_version=target_version,
            frozen_tasks=frozen_tasks,
            tasks_to_execute=tasks_to_execute,
            affected_repositories=affected_repos,
            has_breaking_changes=has_breaking,
        )

    def _classify_tasks(
        self,
        content: str,
        spec_id: str,
        current_run: SpecRun | None,
    ) -> tuple[list[SubTask], list[SubTask]]:
        """Classifica as tarefas da spec entre congeladas (já aprovadas) e a executar.

        Args:
            content: Conteúdo markdown da spec.
            spec_id: Identificador da especificação.
            current_run: SpecRun corrente, quando existente.

        Returns:
            Tupla (frozen_tasks, tasks_to_execute).
        """
        frozen_tasks: list[SubTask] = []
        tasks_to_execute: list[SubTask] = []

        if current_run is not None:
            for task in current_run:
                if task.status in (TaskState.READY, TaskState.APPROVED):
                    frozen_tasks.append(task)
                else:
                    tasks_to_execute.append(task)
            return frozen_tasks, tasks_to_execute

        # Fallback para parsing direto do Markdown quando não há SpecRun anterior
        parsed_entries = parse_spec_tasks(content.splitlines(), spec_id=spec_id)
        for entry in parsed_entries:
            subtask = SubTask(
                id=entry.task_id,
                repo=entry.repo,
                branch=f"agent/{spec_id.lower()}-{entry.task_id}",
                status=TaskState.APPROVED if entry.checked else TaskState.PENDING,
                wave=entry.wave,
            )
            if entry.checked:
                frozen_tasks.append(subtask)
            else:
                tasks_to_execute.append(subtask)

        return frozen_tasks, tasks_to_execute

    def _detect_breaking_changes(
        self,
        current_content: str,
        previous_content: str | None,
        has_frozen: bool,
    ) -> bool:
        """Verifica se contratos prévios foram removidos ou alterados incompativelmente.

        Args:
            current_content: Conteúdo atual da especificação.
            previous_content: Conteúdo prévio de baseline.
            has_frozen: Se existem tarefas congeladas associadas aos contratos.

        Returns:
            True se breaking change for detectada em contratos de tarefas congeladas.
        """
        if not previous_content or not has_frozen:
            return False

        old_contracts = extract_contracts(previous_content)
        new_contracts = extract_contracts(current_content)

        missing = old_contracts - new_contracts
        return len(missing) > 0

    def apply_evolution_to_spec(
        self,
        spec_path: Path,
        plan: SpecEvolutionPlan,
        author: str,
        instruction: str,
    ) -> SpecRevision:
        """Atualiza a especificação Markdown com SemVer e registra o bloco de revisão.

        Args:
            spec_path: Caminho da especificação Markdown no filesystem.
            plan: Plano de evolução calculado.
            author: Autor da revisão.
            instruction: Instrução da evolução.

        Returns:
            Instância de SpecRevision gerada.
        """
        content = spec_path.read_text(encoding="utf-8")
        frontmatter, body = extract_yaml_frontmatter(content)

        rev_type = (
            RevisionType.MAJOR_BREAKING
            if plan.has_breaking_changes
            else RevisionType.MINOR_EVOLUTION
        )
        rev_id = f"rev-{uuid.uuid4().hex[:8]}"

        revision = SpecRevision(
            revision_id=rev_id,
            spec_id=plan.spec_id,
            version=plan.target_version,
            revision_type=rev_type,
            author=author,
            instruction=instruction,
            created_at=datetime.now(UTC),
            frozen_task_ids=[t.id for t in plan.frozen_tasks],
            new_task_ids=[t.id for t in plan.tasks_to_execute],
        )

        frontmatter["spec_version"] = plan.target_version
        revisions_list = frontmatter.get("revisions")
        if not isinstance(revisions_list, list):
            revisions_list = []
        revisions_list.append(revision.model_dump(mode="json"))
        frontmatter["revisions"] = revisions_list

        new_yaml = yaml.dump(
            frontmatter, sort_keys=False, allow_unicode=True
        ).strip()
        updated_text = f"---\n{new_yaml}\n---\n{body}"
        spec_path.write_text(updated_text, encoding="utf-8")

        return revision
