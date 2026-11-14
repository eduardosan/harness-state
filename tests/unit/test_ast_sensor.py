"""Testes do sensor AST das specs Python Fluente (SPEC-PY-00)."""

import textwrap
from pathlib import Path

import pytest

from harness_state.sensors.ast_sensor import AstSensor, check_source, main


def rules_of(source: str) -> list[str]:
    """Retorna os codigos de regra violados por um trecho de codigo.

    Args:
        source: Codigo Python a ser verificado (sera dedentado).

    Returns:
        Lista de codigos de regra na ordem em que foram encontrados.
    """
    violations = check_source(textwrap.dedent(source))
    return [violation.rule for violation in violations]


def test_nested_helper_function_is_flagged() -> None:
    """Business Rule: funcao dentro de funcao e proibida.

    Um helper definido dentro de outra funcao viola a regra global do harness.
    """
    source = """
    def outer():
        def helper():
            return 1
        return helper()
    """
    assert rules_of(source) == ["PYF001"]


def test_async_nested_function_is_flagged() -> None:
    """Business Rule: a proibicao vale tambem para funcoes assincronas."""
    source = """
    async def outer():
        async def helper():
            return 1
        return await helper()
    """
    assert rules_of(source) == ["PYF001"]


def test_decorator_wrapper_with_functools_wraps_is_allowed() -> None:
    """Business Rule: o wrapper de um decorador simples e a unica excecao.

    O wrapper deve usar `functools.wraps` para preservar os metadados.
    """
    source = """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    """
    assert rules_of(source) == []


def test_decorator_wrapper_with_bare_wraps_is_allowed() -> None:
    """Business Rule: `from functools import wraps` tambem e aceito."""
    source = """
    from functools import wraps

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    """
    assert rules_of(source) == []


def test_wrapper_without_wraps_is_flagged() -> None:
    """Business Rule: wrapper sem `functools.wraps` nao tem a excecao."""
    source = """
    def decorator(func):
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    """
    assert rules_of(source) == ["PYF001"]


def test_parametrized_decorator_with_three_levels_is_flagged() -> None:
    """Business Rule: decorador parametrizado deve ser classe com `__call__`.

    Tres niveis de funcao violam a regra tanto na funcao intermediaria quanto
    no wrapper mais interno.
    """
    source = """
    import functools

    def retry(times):
        def decorator(func):
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper
        return decorator
    """
    assert rules_of(source) == ["PYF001", "PYF001"]


def test_function_nested_inside_wrapper_is_flagged() -> None:
    """Business Rule: a excecao cobre so o wrapper, nao o que ha dentro dele."""
    source = """
    import functools

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            def helper():
                return 1
            return func(*args, **kwargs) + helper()
        return wrapper
    """
    assert rules_of(source) == ["PYF001"]


def test_methods_and_module_functions_are_not_flagged() -> None:
    """Business Rule: metodos e funcoes de modulo nao sao funcoes aninhadas."""
    source = """
    def top_level():
        return 1

    class Service:
        def run(self):
            return 1

        async def run_async(self):
            return 1
    """
    assert rules_of(source) == []


@pytest.mark.parametrize("base", ["dict", "list", "set"])
def test_subclassing_builtin_container_is_flagged(base: str) -> None:
    """Business Rule: nao se herda de dict, list ou set (Fluent Python 14.3).

    Os metodos embutidos em C ignoram as sobrescritas; usar UserDict/UserList.
    """
    source = f"""
    class Registry({base}):
        pass
    """
    assert rules_of(source) == ["PYF002"]


def test_user_collections_and_str_enum_are_allowed() -> None:
    """Business Rule: UserDict/UserList e a mistura `str` + `Enum` sao validas."""
    source = """
    import enum
    from collections import UserDict, UserList

    class Registry(UserDict):
        pass

    class Items(UserList):
        pass

    class Color(str, enum.Enum):
        RED = "red"
    """
    assert rules_of(source) == []


@pytest.mark.parametrize(
    "method", ["__add__", "__radd__", "__iadd__", "__eq__", "__lt__", "__matmul__"]
)
def test_raise_type_error_in_operator_is_flagged(method: str) -> None:
    """Business Rule: operador nao suportado deve retornar NotImplemented.

    Levantar TypeError impede o Python de tentar o operador refletido.
    """
    source = f"""
    class Vector:
        def {method}(self, other):
            raise TypeError("unsupported")
    """
    assert rules_of(source) == ["PYF003"]


def test_return_not_implemented_in_operator_is_allowed() -> None:
    """Business Rule: `return NotImplemented` e a forma correta."""
    source = """
    class Vector:
        def __add__(self, other):
            if not isinstance(other, Vector):
                return NotImplemented
            return self
    """
    assert rules_of(source) == []


def test_type_error_outside_operator_is_allowed() -> None:
    """Business Rule: TypeError em metodos comuns continua permitido."""
    source = """
    class Vector:
        def scale(self, factor):
            if not isinstance(factor, int):
                raise TypeError("factor must be int")
            return self
    """
    assert rules_of(source) == []


def test_violation_reports_line_number() -> None:
    """Business Rule: o feedback ao agente deve apontar a linha infratora."""
    source = textwrap.dedent(
        """
        def outer():
            def helper():
                return 1
            return helper()
        """
    )
    violations = check_source(source)
    assert len(violations) == 1
    assert violations[0].line == 3


def test_main_returns_one_and_prints_ruff_style_lines(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: saida no formato do ruff para o format_feedback.sh.

    O parser do sensor ja entende `arquivo:linha:coluna: CODIGO mensagem`.
    """
    target = tmp_path / "bad.py"
    target.write_text("def outer():\n    def helper():\n        return 1\n")

    exit_code = main([str(target)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert f"{target}:2:5: PYF001 " in output


def test_main_returns_zero_for_clean_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: codigo conforme nao produz saida e retorna sucesso."""
    target = tmp_path / "good.py"
    target.write_text("def top_level():\n    return 1\n")

    exit_code = main([str(target)])

    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_main_reports_syntax_error_instead_of_crashing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: arquivo invalido gera feedback acionavel, nao traceback.

    O sensor nao pode derrubar o gate com uma excecao nao tratada.
    """
    target = tmp_path / "broken.py"
    target.write_text("def broken(:\n")

    exit_code = main([str(target)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert f"{target}:1:" in output
    assert "PYF000" in output


def test_main_scans_directory_recursively(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Business Rule: passar um diretorio varre todos os arquivos .py recursivamente."""
    sub = tmp_path / "pkg"
    sub.mkdir()
    target = sub / "nested.py"
    target.write_text("def outer():\n    def inner():\n        pass\n")

    exit_code = main([str(tmp_path)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "nested.py:2:5: PYF001" in output


def test_mutable_default_argument_is_flagged() -> None:
    """Business Rule: argumentos padrão mutáveis (list, dict, set) são proibidos.

    SPEC-PY-06: O uso de listas ou dicionários como padrão em assinaturas causa
    compartilhamento acidental de estado entre chamadas.
    """
    source = """
    def append_item(val, items=[]):
        items.append(val)
        return items
    """
    assert rules_of(source) == ["PYF004"]


def test_nested_try_except_is_flagged() -> None:
    """Business Rule: blocos try...except aninhados são estritamente proibidos.

    Garante apenas um bloco try por escopo lógico, com tratamento plano.
    """
    source = """
    def process_data(payload):
        try:
            try:
                val = int(payload)
            except ValueError:
                val = 0
        except Exception:
            val = -1
        return val
    """
    assert rules_of(source) == ["PYF005"]


def test_try_except_wrapping_import_is_flagged() -> None:
    """Business Rule: é proibido envolver imports em blocos try...except.

    Imports devem ser estáticos ou utilizar importlib.util.find_spec.
    """
    source = """
    try:
        import optional_module
    except ImportError:
        optional_module = None
    """
    assert rules_of(source) == ["PYF006"]


def test_leading_underscore_outside_class_is_flagged() -> None:
    """Business Rule: prefixo '_' é estritamente proibido fora de classes.

    Variáveis e funções de módulo não devem usar prefixo '_'.
    """
    source = """
    _global_var = 10

    def _helper_func():
        return 20
    """
    assert rules_of(source) == ["PYF007", "PYF007"]


def test_leading_underscore_inside_class_is_allowed() -> None:
    """Business Rule: atributos e metodos privados com '_' em classes sao validos."""
    source = """
    class Service:
        _instance = None

        def __init__(self):
            self._internal_state = 1

        def _private_method(self):
            return self._internal_state
    """
    assert rules_of(source) == []


def test_ast_sensor_special_methods_pythonic_behavior() -> None:
    """Business Rule: AstSensor implementa __repr__, __len__ e __iter__ (SPEC-PY-01)."""
    sensor = AstSensor()
    assert repr(sensor).startswith("AstSensor(violations_count=0")
    assert len(sensor) == 0
    assert list(sensor) == []

def test_dunder_names_no_modulo_nao_sao_flagrados() -> None:
    """Business Rule: nomes dunder ('__all__', '__version__') NUNCA violam PYF007.

    O prefixo '_' da regra é o de membros PRIVADOS; dunder conventions são
    protocolo Python. O sensor canônico do flywheel exclui `__x__` e a
    regressão aqui é `__all__` dos __init__.py do pacote (flagged indevido
    na portagem que perdeu a exceção).
    """
    source = """
    __all__ = ["alpha"]

    __version__: str = "1.0"

    __count__ = 3
    """
    assert rules_of(source) == []


def test_dunder_funcao_no_modulo_nao_e_flagrada() -> None:
    """Business Rule: `def __getattr__` no módulo é hook de protocolo, não '_' privado."""
    source = """
    def __getattr__(name: str):
        raise AttributeError(name)
    """
    assert rules_of(source) == []


def test_assign_local_com_underscore_dentro_de_funcao_nao_e_flagrado() -> None:
    """Business Rule: variável local com '_' dentro de função não é escopo de módulo.

    A regra proíbe prefixo privado em nomes de MÓDULO/classe; o sensor
    canônico do flywheel só avalia Assign/AnnAssign fora de função
    (`class_depth == 0 and not function_stack`).
    """
    source = """
    def load():
        _tmp = 1
        _annotated: int = 2
        return _tmp + _annotated
    """
    assert rules_of(source) == []


def test_funcao_aninhada_com_dunder_nome_nao_e_flagrada_pelo_prefixo() -> None:
    """Business Rule: dentro de classe, métodos dunder permanecem válidos."""
    source = """
    class Widget:
        def __init__(self):
            self._x = 1

        def __repr__(self):
            return "Widget"
    """
    assert rules_of(source) == []
