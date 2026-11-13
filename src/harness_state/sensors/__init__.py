"""Sensores de coleta/validação do ecossistema Harness (Onda 1).

Este módulo contém apenas as **definições** dos sensores (dataclasses, validadores).
A **execução server-side** (ExecutionSensor, RunnerHealthSensor) permanece no flywheel.
"""

from .complexity_sensor import (
    DEFAULT_MAX_COMPLEXITY,
    IGNORED_DIRS,
    ComplexitySensor,
    ComplexityViolation,
)
from .config_sensor import (
    FORBIDDEN_FILE_PATTERNS,
    REAL_DOMAINS_PATTERN,
    REAL_IPS_PATTERN,
    REAL_SECRET_PATTERNS,
    ConfigSensor,
    ConfigViolation,
)
from .prompt_sensor import (
    PROMPT_RULES,
    PromptSensor,
    PromptViolation,
)
from .type_baseline import (
    DEFAULT_BASELINE_PATH,
    TypeBaselineSensor,
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
    "ComplexitySensor",
    # Complexity
    "ComplexityViolation",
    "ConfigSensor",
    # Config
    "ConfigViolation",
    "PromptSensor",
    # Prompt
    "PromptViolation",
    "TypeBaselineSensor",
    # Type Baseline
    "TypeBaselineViolation",
]