"""Sensor determinístico de higiene de configuração e proteção 12-Factor (SPEC-CFG-01).

Bloqueia terminantemente:
* ``CFG001``: Arquivo de configuração proibido (.env, config.yaml, etc.).
* ``CFG002``: Hosts, URLs ou IPs reais corporativos no código de produção.
* ``CFG003``: Configurações, hosts ou credenciais de sistemas reais em testes.
  Testes DEVEM usar valores puramente genéricos (ex: mock-service).
* ``CFG004``: Tokens ou chaves de API secretas com formato real hardcoded.

A saída segue o formato padronizado (arquivo:linha:coluna: CODIGO mensagem)
para consumo direto pelo format_feedback.sh e verificação canônica just verify.
"""

import fnmatch
import os
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

FORBIDDEN_FILE_PATTERNS = [
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.development",
    "*.env",
    "config.yaml",
    "config.yml",
    "config.json",
    ".harness/config.yaml",
    ".harness/config.yml",
    ".harness/*.yaml",
    ".harness/*.yml",
]

# Padrões de domínios corporativos e de produção reais da Paralax IA e ecossistema
REAL_DOMAINS_PATTERN = re.compile(
    r"\b(?:https?://)?(?:[a-zA-Z0-9-]+\.)*(?:paralax\.ia\.br|eduardosan\.com|for\.mat\.br)\b",
    re.IGNORECASE,
)

# Padrões de IPs de infraestrutura de produção/staging (RFC1918 específicos ou públicos)
REAL_IPS_PATTERN = re.compile(
    r"\b(?:https?://)?(?:192\.168\.20\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)

# Chaves de API e segredos estruturados
REAL_SECRET_PATTERNS = [
    re.compile(r"\bAIzaSy[A-Za-z0-9_-]{33}\b"),  # Google Cloud / Gemini API Key
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{32,}\b"),  # Anthropic API Key
    re.compile(r"\bsk-lf-[A-Za-z0-9_-]{20,}\b"),  # Langfuse Secret Key
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),  # GitHub Personal Access Token
    re.compile(r"\bgho_[A-Za-z0-9]{36}\b"),  # GitHub OAuth Access Token
    re.compile(r"\bsk-proj-[A-Za-z0-9_-]{40,}\b"),  # OpenAI Project Key
]

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    ".env",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "templates",
}

SCANNABLE_EXTENSIONS = {
    ".py",
    ".yaml",
    ".yml",
    ".json",
    ".toml",
    ".ini",
    ".ts",
    ".js",
    ".go",
    ".rb",
    ".sh",
}


@dataclass
class ConfigViolation:
    """Representa uma violação de configuração detectada pelo sensor."""

    file_path: Path
    line_number: int
    col_number: int
    code: str
    message: str

    def format_output(self) -> str:
        """Formata a violação no padrão consumível por format_feedback.sh."""
        return (
            f"{self.file_path}:{self.line_number}:{self.col_number}: "
            f"{self.code} {self.message}"
        )


def parse_gitignore_rules(root_dir: Path) -> list[str]:
    """Lê e compila regras ativas do arquivo .gitignore da raiz.

    Args:
        root_dir: Diretório raiz do repositório.

    Returns:
        Lista de padrões de arquivos a serem ignorados.
    """
    gitignore_file = root_dir / ".gitignore"
    if not gitignore_file.is_file():
        return []
    rules: list[str] = []
    try:
        content = gitignore_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            rules.append(stripped)
    except OSError:
        return []
    return rules


def get_git_tracked_files(root_dir: Path) -> set[str]:
    """Obtém caminhos relativos rastreados lendo o índice do Git de forma pura.

    Analisa o binário .git/index diretamente sem dependência de processos externos,
    garantindo execução thread-safe e em conformidade com o princípio de
    menor privilégio.

    Args:
        root_dir: Diretório raiz do repositório Git.

    Returns:
        Conjunto de caminhos relativos normalizados dos arquivos rastreados.
    """
    index_path = root_dir / ".git" / "index"
    if not index_path.is_file():
        return set()
    try:
        data = index_path.read_bytes()
        if len(data) < 12 or data[:4] != b"DIRC":
            return set()
        _, num_entries = struct.unpack(">II", data[4:12])
        pos = 12
        files: set[str] = set()
        for _ in range(num_entries):
            if pos + 62 > len(data):
                break
            pos += 62
            null_pos = data.find(b"\x00", pos)
            if null_pos == -1:
                break
            path_bytes = data[pos:null_pos]
            files.add(path_bytes.decode("utf-8", errors="replace"))
            entry_len = 62 + len(path_bytes) + 1
            padding = (8 - (entry_len % 8)) % 8
            pos = null_pos + 1 + padding
        return files
    except (OSError, struct.error, ValueError):
        return set()


def is_tracked_by_git(file_path: Path, root_dir: Path) -> bool:
    """Verifica se o arquivo está rastreado no repositório Git.

    Args:
        file_path: Caminho do arquivo a ser verificado.
        root_dir: Diretório raiz do repositório Git.

    Returns:
        True se o arquivo estiver rastreado no Git, False caso contrário.
    """
    try:
        rel_str = file_path.relative_to(root_dir).as_posix()
        tracked = get_git_tracked_files(root_dir)
        return rel_str in tracked
    except (ValueError, OSError):
        return False


def is_ignored_by_git(file_path: Path, root_dir: Path) -> bool:
    """Verifica se o arquivo está adequadamente ignorado no .gitignore.

    Analisa o arquivo .gitignore de forma pura em Python com fnmatch,
    sem invocar subprocessos externos ou depender de binários do sistema operacional.

    Args:
        file_path: Caminho do arquivo a ser verificado.
        root_dir: Diretório raiz do repositório Git.

    Returns:
        True se o arquivo for ignorado pelo Git, False caso contrário.
    """
    try:
        rel_path = file_path.relative_to(root_dir)
    except ValueError:
        return False

    rules = parse_gitignore_rules(root_dir)
    if not rules:
        return False

    path_str = rel_path.as_posix()
    file_name = file_path.name

    for rule in rules:
        clean_rule = rule.lstrip("/")
        if rule.endswith("/"):
            dir_name = clean_rule.rstrip("/")
            if dir_name in rel_path.parts:
                return True
        elif fnmatch.fnmatch(path_str, clean_rule) or fnmatch.fnmatch(
            file_name, clean_rule
        ):
            return True
        elif clean_rule.startswith("*") and fnmatch.fnmatch(file_name, clean_rule):
            return True

    return False


def build_forbidden_file_violation(
    match: Path,
    rel_path: Path,
    root_dir: Path,
    git_present: bool,
) -> ConfigViolation | None:
    """Cria uma violação CFG001 para um arquivo proibido se aplicável.

    Args:
        match: Caminho completo do arquivo encontrado.
        rel_path: Caminho relativo à raiz do repositório.
        root_dir: Diretório raiz do repositório.
        git_present: Indica se o diretório .git existe na raiz.

    Returns:
        Instância de ConfigViolation ou None se o arquivo estiver devidamente ignorado.
    """
    if not git_present:
        return ConfigViolation(
            file_path=rel_path,
            line_number=1,
            col_number=1,
            code="CFG001",
            message=(
                f"Arquivo proibido '{rel_path}' detectado no repositório. "
                "Padrão 12-Factor exige configuração via variáveis de ambiente."
            ),
        )

    if is_tracked_by_git(match, root_dir):
        return ConfigViolation(
            file_path=rel_path,
            line_number=1,
            col_number=1,
            code="CFG001",
            message=(
                f"Arquivo proibido '{rel_path}' rastreado no Git. "
                "Padrão 12-Factor exige variáveis de ambiente. "
                "Remova com 'git rm --cached' e ignore no .gitignore."
            ),
        )

    if not is_ignored_by_git(match, root_dir):
        return ConfigViolation(
            file_path=rel_path,
            line_number=1,
            col_number=1,
            code="CFG001",
            message=(
                f"Arquivo proibido '{rel_path}' não ignorado "
                "no .gitignore. Adicione ao .gitignore para não "
                "permitir envio de configuração para o git."
            ),
        )

    return None


def find_forbidden_pattern_matches(root_dir: Path, pattern: str) -> list[Path]:
    """Busca arquivos correspondentes a um padrão proibido na raiz ou árvore.

    Args:
        root_dir: Diretório raiz do repositório.
        pattern: Padrão glob de arquivo proibido.

    Returns:
        Lista de caminhos encontrados.
    """
    if "/" in pattern:
        return list(root_dir.glob(pattern))
    return list(root_dir.glob(pattern)) + list(root_dir.rglob(pattern))


def should_inspect_forbidden_candidate(
    match: Path,
    root_dir: Path,
    seen_paths: set[Path],
) -> Path | None:
    """Retorna o caminho relativo caso o arquivo candidato deva ser inspecionado.

    Args:
        match: Caminho completo encontrado pelo glob.
        root_dir: Diretório raiz do repositório.
        seen_paths: Conjunto mutável de caminhos relativos já processados.

    Returns:
        Caminho relativo se válido e inédito, ou None.
    """
    if not match.is_file():
        return None
    rel_path = match.relative_to(root_dir)
    if rel_path in seen_paths:
        return None
    if any(part in IGNORED_DIRS for part in rel_path.parts[:-1]):
        return None
    seen_paths.add(rel_path)
    return rel_path


def check_forbidden_files(root_dir: Path) -> list[ConfigViolation]:
    """Varre a raiz e subdiretórios procurando por arquivos proibidos de configuração.

    Args:
        root_dir: Diretório raiz a inspecionar.

    Returns:
        Lista de violações do tipo CFG001.
    """
    violations: list[ConfigViolation] = []
    seen_paths: set[Path] = set()
    git_present = (root_dir / ".git").exists()

    for pattern in FORBIDDEN_FILE_PATTERNS:
        for match in find_forbidden_pattern_matches(root_dir, pattern):
            rel_path = should_inspect_forbidden_candidate(match, root_dir, seen_paths)
            if rel_path is None:
                continue
            violation = build_forbidden_file_violation(
                match, rel_path, root_dir, git_present
            )
            if violation is not None:
                violations.append(violation)
    return violations


def is_test_file(rel_path: Path) -> bool:
    """Verifica se o arquivo pertence à suíte ou diretório de testes.

    Args:
        rel_path: Caminho relativo do arquivo.

    Returns:
        True se for arquivo de teste, False caso contrário.
    """
    parts = rel_path.parts
    if "tests" in parts or "test" in parts or "spec" in parts:
        return True
    fname = rel_path.name
    return fname.startswith("test_") or fname.endswith("_test.py")


def scan_line_for_config_violations(
    line: str,
    idx: int,
    rel_path: Path,
    in_test: bool,
) -> list[ConfigViolation]:
    """Inspeciona uma única linha em busca de segredos, domínios ou IPs corporativos.

    Args:
        line: Conteúdo textual da linha.
        idx: Número da linha (base 1).
        rel_path: Caminho relativo do arquivo.
        in_test: Indica se o arquivo faz parte da suíte de testes.

    Returns:
        Lista de ConfigViolation encontradas na linha.
    """
    line_violations: list[ConfigViolation] = []
    for secret_pattern in REAL_SECRET_PATTERNS:
        match = secret_pattern.search(line)
        if match:
            line_violations.append(
                ConfigViolation(
                    file_path=rel_path,
                    line_number=idx,
                    col_number=match.start() + 1,
                    code="CFG004",
                    message=(
                        "Chave de API secreta real hardcoded detectada. "
                        "Segredos devem ser injetados exclusivamente via "
                        "variáveis de ambiente."
                    ),
                )
            )

    domain_match = REAL_DOMAINS_PATTERN.search(line)
    if domain_match:
        matched_text = domain_match.group(0)
        code = "CFG003" if in_test else "CFG002"
        msg = (
            f"Host corporativo real '{matched_text}' em teste. "
            "Testes DEVEM usar configurações genéricas (ex: "
            "http://mock-service, http://localhost:8080) "
            "não rastreáveis a sistemas reais."
            if in_test
            else f"Domínio real '{matched_text}' hardcoded no código. "
            "Utilize variáveis de ambiente injetadas via ArgoCD/K8s."
        )
        line_violations.append(
            ConfigViolation(
                file_path=rel_path,
                line_number=idx,
                col_number=domain_match.start() + 1,
                code=code,
                message=msg,
            )
        )

    ip_match = REAL_IPS_PATTERN.search(line)
    if ip_match:
        matched_text = ip_match.group(0)
        code = "CFG003" if in_test else "CFG002"
        msg = (
            f"IP de infraestrutura real '{matched_text}' em teste. "
            "Testes DEVEM usar hosts genéricos (ex: 127.0.0.1)."
            if in_test
            else f"IP de infraestrutura real '{matched_text}' no código. "
            "Utilize variáveis de ambiente configuradas externamente."
        )
        line_violations.append(
            ConfigViolation(
                file_path=rel_path,
                line_number=idx,
                col_number=ip_match.start() + 1,
                code=code,
                message=msg,
            )
        )

    return line_violations


def scan_file_for_config_violations(
    file_path: Path, root_dir: Path
) -> list[ConfigViolation]:
    """Analisa o conteúdo de um arquivo individual em busca de configurações reais.

    Args:
        file_path: Caminho absoluto ou relativo do arquivo a ser lido.
        root_dir: Diretório raiz do repositório para cálculo do caminho relativo.

    Returns:
        Lista de violações detectadas no arquivo.
    """
    violations: list[ConfigViolation] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return violations

    rel_path = file_path.relative_to(root_dir)
    in_test = is_test_file(rel_path)

    for idx, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        violations.extend(scan_line_for_config_violations(line, idx, rel_path, in_test))

    return violations


def is_scannable_config_file(file_path: Path) -> bool:
    """Verifica se um arquivo deve ser inspecionado pelo sensor de configuração.

    Args:
        file_path: Caminho do arquivo candidato.

    Returns:
        True se a extensão for suportada e não for o próprio sensor/teste.
    """
    if file_path.suffix not in SCANNABLE_EXTENSIONS:
        return False
    return file_path.name not in {"config_sensor.py", "test_config_sensor.py"}


def run_config_sensor(root_dir: Path) -> list[ConfigViolation]:
    """Executa varredura completa de higiene de configuração no repositório.

    Args:
        root_dir: Diretório raiz do repositório a ser inspecionado.

    Returns:
        Lista de todas as violações encontradas.
    """
    violations: list[ConfigViolation] = []
    violations.extend(check_forbidden_files(root_dir))

    for current_root, dirs, files in os.walk(root_dir):
        dirs[:] = [
            d for d in dirs if d not in IGNORED_DIRS and not d.startswith(".git")
        ]
        curr_path = Path(current_root)
        for fname in files:
            file_path = curr_path / fname
            if not is_scannable_config_file(file_path):
                continue
            violations.extend(scan_file_for_config_violations(file_path, root_dir))

    return violations


def main() -> int:
    """Ponto de entrada para execução CLI do sensor de configuração.

    Returns:
        0 se não houver violações, 1 caso contrário.
    """
    target_dir = (
        Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd().resolve()
    )
    violations = run_config_sensor(target_dir)

    for violation in violations:
        print(violation.format_output())

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
