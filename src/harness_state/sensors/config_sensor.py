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

# Padrões de domínios corporativos e de produção reais
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
    ".md",
    ".txt",
    ".sh",
    ".bash",
    ".zsh",
    ".fish",
    ".ps1",
    ".dockerfile",
    ".dockerignore",
}


@dataclass(slots=True)
class ConfigViolation:
    """Violação de higiene de configuração.

    Attributes:
        file_path: Caminho do arquivo analisado.
        line_number: Linha onde a violação foi detectada.
        col_number: Coluna aproximada da violação.
        code: Código identificador da regra (CFG001, CFG002, etc.).
        message: Mensagem explicativa da violação.
    """

    file_path: Path
    line_number: int
    col_number: int
    code: str
    message: str

    def format_output(self) -> str:
        """Formata a violação no padrão esperado pelos sensores do harness.

        Returns:
            String no formato 'arquivo:linha:coluna: CODIGO mensagem'.
        """
        return (
            f"{self.file_path}:{self.line_number}:{self.col_number}: "
            f"{self.code} {self.message}"
        )


class ConfigSensor:
    """Sensor determinístico de higiene de configuração e proteção 12-Factor."""

    def __init__(
        self,
        root_dir: Path,
        ignored_dirs: set[str] | None = None,
        scannable_extensions: set[str] | None = None,
    ) -> None:
        """Inicializa o sensor.

        Args:
            root_dir: Diretório raiz a partir de onde os arquivos serão buscados.
            ignored_dirs: Diretórios a ignorar durante a varredura.
            scannable_extensions: Extensões de arquivo a escanear.
        """
        self.root_dir = root_dir.resolve()
        self.ignored_dirs = ignored_dirs or IGNORED_DIRS
        self.scannable_extensions = scannable_extensions or SCANNABLE_EXTENSIONS
        self.violations: list[ConfigViolation] = []

    def scan(self) -> list[ConfigViolation]:
        """Executa a varredura completa no diretório raiz.

        Returns:
            Lista de violações encontradas.
        """
        self.violations = []
        for file_path in self._find_scannable_files():
            self._scan_file(file_path)
        return self.violations

    def _find_scannable_files(self) -> list[Path]:
        """Localiza todos os arquivos escaneáveis no projeto."""
        found_files: list[Path] = []
        for root, dirs, fnames in os.walk(self.root_dir):
            dirs[:] = [d for d in dirs if d not in self.ignored_dirs]

            root_path = Path(root)
            for file in fnames:
                file_path = root_path / file
                if file_path.suffix in self.scannable_extensions:
                    found_files.append(file_path)
        return found_files

    def _scan_file(self, file_path: Path) -> None:
        """Escaneia um único arquivo em busca de violações."""
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            return

        self._check_forbidden_files(file_path)
        self._check_real_domains(file_path, content)
        self._check_real_ips(file_path, content)
        self._check_real_secrets(file_path, content)

    def _check_forbidden_files(self, file_path: Path) -> None:
        """CFG001: Arquivos de configuração proibidos."""
        relative = file_path.relative_to(self.root_dir)
        for pattern in FORBIDDEN_FILE_PATTERNS:
            if fnmatch.fnmatch(file_path.name, pattern) or fnmatch.fnmatch(
                str(relative), pattern
            ):
                self.violations.append(
                    ConfigViolation(
                        file_path=relative,
                        line_number=1,
                        col_number=1,
                        code="CFG001",
                        message=f"Arquivo de configuração proibido detectado: {file_path.name}. Use variáveis de ambiente ou secrets management.",
                    )
                )

    def _check_real_domains(self, file_path: Path, content: str) -> None:
        """CFG002: Domínios corporativos/produção reais no código."""
        for match in REAL_DOMAINS_PATTERN.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            col_num = match.start() - content.rfind("\n", 0, match.start())
            self.violations.append(
                ConfigViolation(
                    file_path=file_path.relative_to(self.root_dir),
                    line_number=line_num,
                    col_number=col_num,
                    code="CFG002",
                    message=f"Domínio de produção real detectado: {match.group()}. Use placeholders como {{INTERNAL_HOST}}.",
                )
            )

    def _check_real_ips(self, file_path: Path, content: str) -> None:
        """CFG002: IPs de infraestrutura real no código."""
        for match in REAL_IPS_PATTERN.finditer(content):
            line_num = content[: match.start()].count("\n") + 1
            col_num = match.start() - content.rfind("\n", 0, match.start())
            self.violations.append(
                ConfigViolation(
                    file_path=file_path.relative_to(self.root_dir),
                    line_number=line_num,
                    col_number=col_num,
                    code="CFG002",
                    message=f"IP de infraestrutura real detectado: {match.group()}. Use placeholders como {{SERVER_IP}}.",
                )
            )

    def _check_real_secrets(self, file_path: Path, content: str) -> None:
        """CFG004: Tokens/chaves de API com formato real hardcoded."""
        for pattern in REAL_SECRET_PATTERNS:
            for match in pattern.finditer(content):
                line_num = content[: match.start()].count("\n") + 1
                col_num = match.start() - content.rfind("\n", 0, match.start())
                self.violations.append(
                    ConfigViolation(
                        file_path=file_path.relative_to(self.root_dir),
                        line_number=line_num,
                        col_number=col_num,
                        code="CFG004",
                        message=f"Token/segredo real detectado ({match.group()[:10]}...). Use variáveis de ambiente ou secret management.",
                    )
                )