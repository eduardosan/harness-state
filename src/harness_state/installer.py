"""Instalador do catálogo unificado de Harnesses (`harness init`) por linguagem."""

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from harness_state.guidelines import SUPERPOWERS_GUIDELINES_BLOCK


@dataclass(slots=True)
class HarnessInitResult:
    """Resultado da instalação do harness no pacote local.

    Attributes:
        project_root: Diretório raiz do módulo onde o harness foi instalado.
        language: Linguagem detectada ou selecionada para o módulo.
        installed_skills: Lista de caminhos relativos de skills instaladas.
        installed_pipeline_files: Lista de arquivos de pipeline instalados.
        config_file: Caminho do arquivo de configuração local instalado/verificado.
    """

    project_root: Path
    language: str
    installed_skills: list[str] = field(default_factory=list)
    installed_pipeline_files: list[str] = field(default_factory=list)
    config_file: str = ""



def get_catalog_root() -> Path:
    """Retorna o diretório raiz do catálogo de harnesses embutido no pacote.

    Returns:
        Path apontando para `src/harness_state/catalog`.
    """
    return Path(__file__).resolve().parent / "catalog"


def get_templates_root() -> Path:
    """Retorna o diretório de templates de sensores do repositório.

    Returns:
        Path apontando para `templates/harness` na raiz do repositório.
    """
    return Path(__file__).resolve().parents[2] / "templates" / "harness"


def detect_project_language(project_root: Path) -> str:
    """Detecta a linguagem principal do módulo local a partir de arquivos de manifesto.

    Args:
        project_root: Caminho para a raiz do pacote local.

    Returns:
        Identificador da linguagem ('python', 'go', 'typescript' ou 'cicd').
    """
    if (project_root / "pyproject.toml").is_file() or (
        project_root / "setup.py"
    ).is_file():
        return "python"
    if (project_root / "go.mod").is_file():
        return "go"
    if (project_root / "package.json").is_file() or (
        project_root / "tsconfig.json"
    ).is_file():
        return "typescript"
    if (project_root / ".github" / "workflows").is_dir() or (
        project_root / "cloudbuild"
    ).is_dir():
        return "cicd"
    return "python"


def upsert_guidelines_file(file_path: Path, block: str) -> bool:
    """Insere ou atualiza o bloco de diretrizes em um arquivo markdown.

    Args:
        file_path: Caminho para o arquivo markdown.
        block: Conteúdo do bloco formatado com marcadores de início e fim.

    Returns:
        True se o arquivo foi modificado ou criado; False caso contrário.
    """
    start_tag = "<!-- SUPERPOWERS-HARNESS:START -->"
    end_tag = "<!-- SUPERPOWERS-HARNESS:END -->"

    if not file_path.exists():
        file_path.write_text(block.strip() + "\n", encoding="utf-8")
        return True

    existing_content = file_path.read_text(encoding="utf-8")
    if start_tag in existing_content and end_tag in existing_content:
        before = existing_content.split(start_tag)[0]
        after = existing_content.split(end_tag)[1]
        new_content = before + block.strip() + after
    else:
        new_content = existing_content.rstrip() + "\n\n" + block.strip() + "\n"

    if new_content != existing_content:
        file_path.write_text(new_content, encoding="utf-8")
        return True
    return False


def install_agent_guidelines(project_root: Path) -> list[str]:
    """Garante a presença das diretrizes do Superpowers e SDD em AGENTS.md e CLAUDE.md.

    Args:
        project_root: Raiz do módulo local.

    Returns:
        Lista de caminhos relativos atualizados ou criados.
    """
    updated_files: list[str] = []
    agents_md = project_root / "AGENTS.md"
    if upsert_guidelines_file(agents_md, SUPERPOWERS_GUIDELINES_BLOCK):
        updated_files.append("AGENTS.md")

    claude_md = project_root / "CLAUDE.md"
    if upsert_guidelines_file(claude_md, SUPERPOWERS_GUIDELINES_BLOCK):
        updated_files.append("CLAUDE.md")

    return updated_files


def copy_skill_group(
    source_group_dir: Path, target_skills_dir: Path, project_root: Path
) -> list[str]:
    """Copia todas as pastas de skills de um grupo para o diretório `.claude/skills`.

    Args:
        source_group_dir: Diretório de origem do grupo no catálogo.
        target_skills_dir: Diretório `.claude/skills` no pacote de destino.
        project_root: Raiz do pacote para cálculo de caminhos relativos.

    Returns:
        Lista de caminhos relativos copiados.
    """
    installed: list[str] = []
    if not source_group_dir.is_dir():
        return installed

    for skill_dir in sorted(source_group_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        dest_dir = target_skills_dir / skill_dir.name
        if dest_dir.exists():
            shutil.rmtree(dest_dir)
        shutil.copytree(skill_dir, dest_dir)
        for copied_file in sorted(dest_dir.rglob("*")):
            if copied_file.is_file():
                installed.append(str(copied_file.relative_to(project_root)))
    return installed


def install_sensors(project_root: Path) -> list[str]:
    """Instala os sensores determinísticos do pipeline em `.harness/sensors/`.

    Prioriza os sensores embutidos no catálogo do pacote (`catalog/pipeline/sensors`)
    para funcionar quando instalado globalmente via `uv tool install`.

    Args:
        project_root: Raiz do módulo local.

    Returns:
        Lista de caminhos relativos dos sensores instalados.
    """
    installed: list[str] = []
    sensors_dest = project_root / ".harness" / "sensors"
    sensors_dest.mkdir(parents=True, exist_ok=True)

    catalog_sensors = get_catalog_root() / "pipeline" / "sensors"
    templates_sensors = get_templates_root() / ".harness" / "sensors"
    sensor_names = [
        "format_feedback.sh",
        "ast_sensor.py",
        "complexity_sensor.py",
        "type_baseline.py",
        "spec_router.py",
        "cicd_sensor.py",
        "config_sensor.py",
    ]
    for name in sensor_names:
        src_file = catalog_sensors / name
        if not src_file.is_file():
            src_file = templates_sensors / name
        dest_file = sensors_dest / name
        if src_file.is_file():
            shutil.copy2(src_file, dest_file)
        elif name == "format_feedback.sh":
            dest_file.write_text(
                '#!/usr/bin/env bash\nshift 2\nexec "$@"\n', encoding="utf-8"
            )
        if dest_file.is_file():
            if name.endswith(".sh"):
                dest_file.chmod(0o755)
            installed.append(str(dest_file.relative_to(project_root)))

    return installed


def ensure_gitignore_isolation(resolved_root: Path) -> None:
    """Garante que entradas de isolamento 12-Factor estejam presentes no .gitignore.

    Args:
        resolved_root: Diretório raiz do repositório local.
    """
    gitignore_file = resolved_root / ".gitignore"
    if not gitignore_file.is_file():
        return
    required_ignores = [
        ".harness/config.yaml",
        ".harness/*.yaml",
        ".harness/*.yml",
        ".harness/*.md",
        ".env",
        ".env.*",
        "*.env",
    ]
    content = gitignore_file.read_text(encoding="utf-8")
    missing_ignores = [entry for entry in required_ignores if entry not in content]
    if not missing_ignores:
        return
    with gitignore_file.open("a", encoding="utf-8") as f:
        f.write("\n# Harness & 12-Factor config isolation\n")
        for entry in missing_ignores:
            f.write(f"{entry}\n")


def install_pre_commit_hook(resolved_root: Path, catalog_root: Path) -> None:
    """Instala o hook de pre-commit em `.harness/hooks/` e `.git/hooks/`.

    Args:
        resolved_root: Diretório raiz do módulo local.
        catalog_root: Diretório raiz do catálogo do flywheel.
    """
    hooks_dest = resolved_root / ".harness" / "hooks"
    hooks_dest.mkdir(parents=True, exist_ok=True)
    hook_src = catalog_root / "pipeline" / "hooks" / "pre-commit"
    if not hook_src.is_file():
        return
    hook_dest = hooks_dest / "pre-commit"
    shutil.copy2(hook_src, hook_dest)
    hook_dest.chmod(0o755)
    git_hooks_dir = resolved_root / ".git" / "hooks"
    if git_hooks_dir.is_dir():
        shutil.copy2(hook_src, git_hooks_dir / "pre-commit")
        (git_hooks_dir / "pre-commit").chmod(0o755)


def copy_if_needed(src: Path, dest: Path, force: bool) -> bool:
    """Copia um arquivo caso a origem exista e o destino permita escrita.

    Args:
        src: Caminho do arquivo de origem.
        dest: Caminho do arquivo de destino.
        force: Se True, sobrescreve mesmo que o destino já exista.

    Returns:
        True se o arquivo foi copiado, False caso contrário.
    """
    if src.is_file() and (force or not dest.exists()):
        shutil.copy2(src, dest)
        return True
    return False


def get_default_user_config_path() -> Path:
    """Retorna o caminho padrão do arquivo de configuração do usuário."""
    return Path.home() / ".config" / "harness" / "config.yaml"


def install_module_harness(
    project_root: Path,
    language: str | None = None,
    ci_mode: bool = False,
    force: bool = False,
    with_superpowers: bool = False,
) -> HarnessInitResult:
    """Instala o harness no módulo local.

    Args:
        project_root: Raiz do módulo onde o harness será instalado.
        language: Linguagem opcional; se omitida, é detectada automaticamente.
        ci_mode: Se True, instala apenas pipeline de verificação para CI.
        force: Se True, sobrescreve arquivos de pipeline existentes.
        with_superpowers: Se True, baixa as skills do upstream do Superpowers.

    Returns:
        HarnessInitResult detalhando os artefatos instalados.
    """
    resolved_root = project_root.resolve()
    resolved_lang = language or detect_project_language(resolved_root)
    catalog_root = get_catalog_root()

    # O contexto do agente (skills por linguagem + diretrizes em AGENTS/CLAUDE)
    # é parte estrutural do harness e NÃO depende do modo de execução: a esteira
    # roda agentes headless exatamente onde `harness init --ci` é executado, e
    # omiti-los deixaria o agente sem contexto de estilo, TDD e governança.
    installed_skills: list[str] = []
    target_skills_dir = resolved_root / ".claude" / "skills"
    target_skills_dir.mkdir(parents=True, exist_ok=True)
    common_skills_dir = catalog_root / "skills" / "common"
    lang_skills_dir = catalog_root / "skills" / resolved_lang
    installed_skills.extend(
        copy_skill_group(common_skills_dir, target_skills_dir, resolved_root)
    )
    installed_skills.extend(
        copy_skill_group(lang_skills_dir, target_skills_dir, resolved_root)
    )
    install_agent_guidelines(resolved_root)

    if with_superpowers:
        from harness_state.superpowers import install_superpowers_from_upstream

        installed_skills.extend(
            install_superpowers_from_upstream(project_root=resolved_root)
        )

    installed_pipeline: list[str] = []
    installed_pipeline.extend(install_sensors(resolved_root))
    ensure_gitignore_isolation(resolved_root)

    justfile_src = catalog_root / "pipeline" / resolved_lang / "justfile"
    if not justfile_src.is_file():
        justfile_src = catalog_root / "pipeline" / "python" / "justfile"
    if copy_if_needed(justfile_src, resolved_root / "justfile", force):
        installed_pipeline.append("justfile")

    install_pre_commit_hook(resolved_root, catalog_root)

    specs_dir = resolved_root / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    template_src = catalog_root / "pipeline" / "common" / "SPEC-TEMPLATE.md"
    if copy_if_needed(template_src, specs_dir / "SPEC-TEMPLATE.md", force):
        installed_pipeline.append("specs/SPEC-TEMPLATE.md")

    workflows_dir = resolved_root / ".github" / "workflows"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    post_merge_src = catalog_root / "pipeline" / "common" / "bug-post-merge.yml"
    if copy_if_needed(post_merge_src, workflows_dir / "bug-post-merge.yml", force):
        installed_pipeline.append(".github/workflows/bug-post-merge.yml")

    user_cfg = get_default_user_config_path()
    cfg_display = str(user_cfg) if user_cfg.is_file() else ""

    return HarnessInitResult(
        project_root=resolved_root,
        language=resolved_lang,
        installed_skills=installed_skills,
        installed_pipeline_files=installed_pipeline,
        config_file=cfg_display,
    )


if __name__ == "__main__":
    # Teste rápido
    print("Installer module loaded successfully")