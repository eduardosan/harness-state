"""Roteador estático de especificações Python Fluente (alias modular).

Re-exporta os símbolos canônicos de harness_state.spec_router sob o pacote
harness_state.spec conforme estruturado na SPEC-009B.
"""

from harness_state.spec_router import (
    SPEC_PATTERNS,
    RoutingResult,
    collect_fluent_python_guidelines,
    extract_added_lines,
    extract_normative_rules,
    filter_diff_by_suffix,
    find_spec_file_in_dir,
    get_spec_reference_dir,
    line_matches_diff_target_suffix,
    route_code,
    route_diff,
)

__all__ = [
    "SPEC_PATTERNS",
    "RoutingResult",
    "collect_fluent_python_guidelines",
    "extract_added_lines",
    "extract_normative_rules",
    "filter_diff_by_suffix",
    "find_spec_file_in_dir",
    "get_spec_reference_dir",
    "line_matches_diff_target_suffix",
    "route_code",
    "route_diff",
]
