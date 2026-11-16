"""Módulo de baseline de tipagem estática (pyright) para o ecossistema Harness.

Re-exporta as operações canônicas do sensor de type baseline (SPEC-009E).
"""

from harness_state.sensors.type_baseline import (
    DEFAULT_BASELINE_PATH,
    Comparison,
    Diagnostic,
    DiagnosticKey,
    build_parser,
    compare,
    expand,
    format_diagnostic,
    load_baseline,
    main,
    parse_report,
    relative_path,
    save_baseline,
    shrink,
)

__all__ = [
    "DEFAULT_BASELINE_PATH",
    "Comparison",
    "Diagnostic",
    "DiagnosticKey",
    "build_parser",
    "compare",
    "expand",
    "format_diagnostic",
    "load_baseline",
    "main",
    "parse_report",
    "relative_path",
    "save_baseline",
    "shrink",
]
