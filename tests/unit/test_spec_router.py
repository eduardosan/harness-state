"""Testes do roteador estatico de specs Python Fluente (Fase 0)."""

from pathlib import Path

from harness_state.catalog.pipeline.sensors.spec_router import (
    RoutingResult,
    collect_fluent_python_guidelines,
    extract_added_lines,
    extract_normative_rules,
    filter_diff_by_suffix,
    route_code,
    route_diff,
)


def test_extract_added_lines_ignores_metadata_and_deletions() -> None:
    """Business Rule: apenas linhas adicionadas ou modificadas entram no roteamento."""
    diff_text = """\
--- a/src/app.py
+++ b/src/app.py
@@ -1,4 +1,5 @@
-import os
+import asyncio
+from dataclasses import dataclass
 def hello():
-    return 1
+    return 2
"""
    added = extract_added_lines(diff_text)
    assert "import asyncio" in added
    assert "from dataclasses import dataclass" in added
    assert "return 2" in added
    assert "import os" not in added
    assert "return 1" not in added
    assert "+++ b/src/app.py" not in added


def test_routes_dataclass_and_namedtuple_to_group_a() -> None:
    """Business Rule: definicao de dataclass ou NamedTuple ativa grupo A e PY-05."""
    code = """
    from dataclasses import dataclass

    @dataclass(slots=True)
    class Item:
        id: int
    """
    result: RoutingResult = route_code(code)
    assert "A" in result.groups
    assert "PY-05" in result.specs


def test_routes_dunder_methods_to_group_a() -> None:
    """Business Rule: metodos de representacao e contencao ativam grupo A e PY-01."""
    code = """
    class Deck:
        def __len__(self):
            return 52

        def __repr__(self):
            return "Deck()"
    """
    result: RoutingResult = route_code(code)
    assert "A" in result.groups
    assert "PY-01" in result.specs


def test_routes_decorators_and_functools_to_group_b() -> None:
    """Business Rule: decoradores e functools ativam grupo B e PY-07."""
    code = """
    import functools

    @functools.lru_cache
    def expensive():
        pass
    """
    result: RoutingResult = route_code(code)
    assert "B" in result.groups
    assert "PY-07" in result.specs


def test_routes_typevar_and_overload_to_group_b() -> None:
    """Business Rule: tipagem avancada e overloads ativam grupo B e PY-08."""
    code = """
    from typing import TypeVar, overload

    T = TypeVar("T")
    """
    result: RoutingResult = route_code(code)
    assert "B" in result.groups
    assert "PY-08" in result.specs


def test_routes_protocol_and_abc_to_group_c() -> None:
    """Business Rule: interfaces e protocolos ativam grupo C e PY-09."""
    code = """
    from typing import Protocol

    class Reader(Protocol):
        def read(self) -> bytes: ...
    """
    result: RoutingResult = route_code(code)
    assert "C" in result.groups
    assert "PY-09" in result.specs


def test_routes_operator_overloading_to_group_c() -> None:
    """Business Rule: sobrecarga de operadores aritmeticos ativa grupo C e PY-10."""
    code = """
    class Vector:
        def __add__(self, other):
            return NotImplemented
    """
    result: RoutingResult = route_code(code)
    assert "C" in result.groups
    assert "PY-10" in result.specs


def test_routes_async_and_concurrency_to_group_d() -> None:
    """Business Rule: codigo assincrono ativa grupo D e PY-12."""
    code = """
    import asyncio

    async def fetch():
        async with asyncio.TaskGroup() as tg:
            pass
    """
    result: RoutingResult = route_code(code)
    assert "D" in result.groups
    assert "PY-12" in result.specs


def test_routes_generators_and_context_managers_to_group_d() -> None:
    """Business Rule: geradores e with ativam grupo D e PY-11."""
    code = """
    def stream():
        with open("file.txt") as f:
            yield f.readline()
    """
    result: RoutingResult = route_code(code)
    assert "D" in result.groups
    assert "PY-11" in result.specs


def test_routes_unicode_and_bytes_to_group_d() -> None:
    """Business Rule: codificacao e decodificacao de bytes ativam grupo D e PY-04."""
    code = """
    def decode_payload(data: bytes) -> str:
        return data.decode("utf-8")
    """
    result: RoutingResult = route_code(code)
    assert "D" in result.groups
    assert "PY-04" in result.specs


def test_routes_metaprogramming_to_group_e() -> None:
    """Business Rule: descritores, property e metaclasses ativam grupo E e PY-13."""
    code = """
    class Model:
        @property
        def name(self) -> str:
            return "ok"

        def __init_subclass__(cls, **kwargs):
            super().__init_subclass__(**kwargs)
    """
    result: RoutingResult = route_code(code)
    assert "E" in result.groups
    assert "PY-13" in result.specs


def test_route_diff_routes_unified_diff_correctly() -> None:
    """Business Rule: route_diff processa saida completa do git diff."""
    diff_text = """\
diff --git a/src/service.py b/src/service.py
index 1111..2222 100644
--- a/src/service.py
+++ b/src/service.py
@@ -10,3 +10,5 @@
+async def handle_request():
+    return {"status": "ok"}
"""
    result: RoutingResult = route_diff(diff_text)
    assert "D" in result.groups
    assert "PY-12" in result.specs


def test_extract_normative_rules_extracts_section_two() -> None:
    """Business Rule: extract_normative_rules extrai exclusivamente a secao 2."""
    spec_md = """# SPEC-PY-01: Modelo de Dados

## 1. Fonte
Python Fluente 2a ed.

## 2. Regras normativas
1. Classes devem implementar __repr__.
2. Proibido get_size().

## 3. Anti-padrao
Anti-padroes aqui.
"""
    rules = extract_normative_rules(spec_md)
    assert "Classes devem implementar __repr__." in rules
    assert "Proibido get_size()." in rules
    assert "Python Fluente 2a ed." not in rules
    assert "Anti-padroes aqui." not in rules


def test_collect_fluent_python_guidelines_empty_for_non_python_diff() -> None:
    """Business Rule: diffs sem correspondencia de Python Fluente geram string vazia."""
    diff_text = """\
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-Hello
+World
"""
    guidelines = collect_fluent_python_guidelines(diff_text)
    assert guidelines == ""


def test_collect_fluent_python_guidelines_aggregates_rules_for_diff(
    tmp_path: Path,
) -> None:
    """Business Rule: collect_fluent_python_guidelines formata regras das specs."""
    mock_specs_dir = tmp_path / "specs"
    mock_specs_dir.mkdir()
    spec_content = (
        "# SPEC-PY-05: Dataclasses\n\n"
        "## 2. Regras normativas\n"
        "1. Usar slots=True por padrao.\n\n"
        "## 3. Anti-padrao"
    )
    (mock_specs_dir / "SPEC-PY-05-dataclasses.md").write_text(
        spec_content,
        encoding="utf-8",
    )
    diff_text = """\
--- a/model.py
+++ b/model.py
@@ -0,0 +1,4 @@
+from dataclasses import dataclass
+@dataclass
+class User:
+    name: str
"""
    guidelines = collect_fluent_python_guidelines(diff_text, specs_dir=mock_specs_dir)
    assert "SPEC-PY-05" in guidelines
    assert "Usar slots=True por padrao." in guidelines


def test_filter_diff_by_suffix_extracts_only_specified_extension() -> None:
    """Business Rule: filter_diff_by_suffix filtra apenas arquivos compativeis."""
    diff_text = """\
diff --git a/docs/README.md b/docs/README.md
index 111..222 100644
--- a/docs/README.md
+++ b/docs/README.md
@@ -1,1 +1,2 @@
 # Docs
+# Novo conteudo
diff --git a/src/app.py b/src/app.py
index 333..444 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1,1 +1,2 @@
 # App
+def main(): pass
"""
    filtered = filter_diff_by_suffix(diff_text, file_suffix=".py")
    assert "diff --git a/src/app.py" in filtered
    assert "def main(): pass" in filtered
    assert "diff --git a/docs/README.md" not in filtered
    assert "# Novo conteudo" not in filtered
