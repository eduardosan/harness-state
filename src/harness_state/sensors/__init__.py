"""Sensores de coleta/validação do ecossistema Harness (Onda 1).

Este módulo contém apenas as **definições** dos sensores (dataclasses, validadores).
A **execução server-side** (ExecutionSensor, RunnerHealthSensor) permanece no flywheel.
"""

from .complexity_sensor import (
    ComplexityViolation,
    ComplexitySensor,
    DEFAULT_MAX_COMPLEXITY,
    IGNORED_DIRS,
)

from .config_sensor import (
    ConfigViolation,
    ConfigSensor,
    FORBIDDEN_FILE_PATTERNS,
    REAL_DOMAINS_PATTERN,
    REAL_IPS_PATTERN,
    REAL_SECRET_PATTERNS,
)

from .prompt_sensor import (
    PromptViolation,
    PromptSensor,
    PROMPT_RULES,
)

from .type_baseline import (
    TypeBaselineViolation,
    TypeBaselineSensor,
    DEFAULT_BASELINE_PATH,
)

__all__ = [
    # Complexity
    "ComplexityViolation",
    "ComplexitySensor",
    "DEFAULT_MAX_COMPLEXITY",
    "IGNORED_DIRS",
    # Config
    "ConfigViolation",
    "ConfigSensor",
    "FORBIDDEN_FILE_PATTERNS",
    "REAL_DOMAINS_PATTERN",
    "REAL_IPS_PATTERN",
    "REAL_SECRET_PATTERNS",
    # Prompt
    "PromptViolation",
    "PromptSensor",
    "PROMPT_RULES",
    # Type Baseline
    "TypeBaselineViolation",
    "TypeBaselineSensor",
    "DEFAULT_BASELINE_PATH",
]