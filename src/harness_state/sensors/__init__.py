"""Sensores de coleta/validação do ecossistema Harness (Onda 1).

Implementações migradas do agentic-flywheel: AST (PYF), CI/CD (CICD),
complexidade cognitiva (complexipy), configuração (CFG) e governança de
prompts Langfuse (PRM), mais o baseline de tipos do pyright.
"""

from .cicd_sensor import CICDValidator
from .complexity_sensor import (
    DEFAULT_MAX_COMPLEXITY,
    IGNORED_DIRS,
    ComplexityViolation,
    run_complexity_sensor,
)
from .config_sensor import (
    FORBIDDEN_FILE_PATTERNS,
    REAL_DOMAINS_PATTERN,
    REAL_IPS_PATTERN,
    REAL_SECRET_PATTERNS,
    ConfigViolation,
    check_forbidden_files,
    run_config_sensor,
    scan_file_for_config_violations,
)
from .prompt_sensor import (
    PROMPT_RULES,
    PromptGovernanceSensor,
    PromptViolation,
)
from .type_baseline import (
    DEFAULT_BASELINE_PATH,
    TypeBaselineViolation,
)

__all__ = [
    "DEFAULT_BASELINE_PATH",
    "DEFAULT_MAX_COMPLEXITY",
    "FORBIDDEN_FILE_PATTERNS",
    "IGNORED_DIRS",
    "PROMPT_RULES",
    "REAL_DOMAINS_PATTERN",
    "REAL_IPS_PATTERN",
    "REAL_SECRET_PATTERNS",
    # CI/CD
    "CICDValidator",
    # Complexidade
    "ComplexityViolation",
    # Config
    "ConfigViolation",
    # Prompt
    "PromptGovernanceSensor",
    "PromptViolation",
    # Type Baseline
    "TypeBaselineViolation",
    "check_forbidden_files",
    "run_complexity_sensor",
    "run_config_sensor",
    "scan_file_for_config_violations",
]