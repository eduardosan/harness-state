# SPEC-PY-07: Funções, Clausuras e Decoradores

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 7: "Funções como objetos de primeira classe" (seções 7.2 a 7.8).
- Capítulo 9: "Decoradores e clausuras" (seções 9.2 a 9.10).
- Capítulo 10: "Padrões de projeto com funções de primeira classe" (seções 10.2 a 10.4).

## 2. Regras normativas

1. **Uso de utilitários funcionais em vez de lambdas triviais [Livro]:**
   - Prefira operadores do módulo `operator` (`itemgetter`, `attrgetter`, `methodcaller`) no lugar de funções `lambda` anônimas simples para extração de atributos ou chaves de ordenação.
   - Use `functools.partial` para fixar argumentos posicionais ou nomeados e produzir novas funções reutilizáveis.
2. **Assinaturas explícitas com parâmetros somente nomeados ou posicionais [Livro]:**
   - APIs públicas **MUST** utilizar parâmetros somente nomeados (`*`) quando existirem flags booleanas, configurações opcionais ou opções com significados ambíguos na chamada.
   - Parâmetros somente posicionais (`/`) devem ser usados quando o nome do argumento for irrelevante ou passível de conflito com `**kwargs`.
3. **Preservação obrigatória de metadados com `functools.wraps` [Livro]:**
   - Todo decorador de função **MUST** aplicar `@functools.wraps(func)` na função empacotadora interna (`wrapper`). Isso preserva `__name__`, `__doc__`, anotações de tipo e a cadeia de introspecção `__wrapped__`.
4. **Despacho genérico com `singledispatch` sobre cadeias de `isinstance` [Livro]:**
   - Quando uma função precisa variar sua implementação com base no tipo do primeiro argumento, prefira `@functools.singledispatch` no lugar de extensas cadeias condicionais `if isinstance(...) / elif isinstance(...)`.
5. **Memoização consciente e armadilhas de cache em métodos [Livro]:**
   - Use `@functools.cache` ou `@functools.lru_cache(maxsize=...)` para funções puras e determinísticas.
   - **MUST NOT** aplicar `@lru_cache` diretamente a métodos de instância normais sem gerenciar o ciclo de vida da instância, pois a referência retém a instância na memória indefinidamente gerando vazamento de recursos (prefira `@functools.cached_property` para propriedades imutáveis de instâncias).
6. **Padrão Estratégia e Comando com funções de primeira classe [Livro]:**
   - Prefira passar funções simples diretamente como estratégias ou comandos em vez de criar hierarquias artificiais de classes de objeto único contendo apenas um método `execute()`.
7. **Exceção estrita da política de funções aninhadas para decoradores [Política]:**
   - Em conformidade estrita com as regras do harness:
     - Funções aninhadas continuam terminantemente proibidas no código em geral.
     - **A única exceção admitida** é a função empacotadora interna (`wrapper`) de um decorador simples de dois níveis, e ela **MUST** ter `@functools.wraps(func)`.
     - Decoradores **parametrizados** (que recebem argumentos de configuração) **MUST NOT** criar três níveis aninhados de funções (`def dec(arg): def inner(fn): def wrapper(*a): ...`). Eles **MUST** ser implementados como classes com `__call__` ou usar `functools.partial`.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Lambda prolixo para ordenação por atributo
```python
# ERRADO: sintaxe verbosa de lambda com acesso a atributo
users_sorted = sorted(users, key=lambda user: user.registration_date)
```

### Forma idiomática 3.1: Operador `attrgetter` expressivo e otimizado
```python
# CORRETO: expressao direta, reutilizavel e implementada em C
from operator import attrgetter

users_sorted = sorted(users, key=attrgetter("registration_date"))
```

---

### Anti-padrão 3.2: Três níveis de funções aninhadas em decorador parametrizado
```python
# ERRADO: violacao grave de arquitetura com triplo aninhamento de funcoes
def retry(attempts: int):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for _ in range(attempts):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    pass
            return None
        return wrapper
    return decorator
```

### Forma idiomática 3.2: Classe de decorador com `__call__` e sem aninhamentos múltiplos
```python
# CORRETO: decorador parametrizado como classe limpa
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

class Retry:
    def __init__(self, attempts: int) -> None:
        self.attempts = attempts

    def __call__(self, func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None
            for _ in range(self.attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_error = exc
            if last_error is not None:
                raise last_error
            return None

        return wrapper  # type: ignore[return-value]
```

---

### Anti-padrão 3.3: Cadeia procedural de `if isinstance` para formatação
```python
# ERRADO: dificil de estender e viola o principio aberto/fechado
def format_data(val: object) -> str:
    if isinstance(val, int):
        return f"int: {val:,}"
    elif isinstance(val, float):
        return f"float: {val:.2f}"
    elif isinstance(val, list):
        return f"list[{len(val)}]"
    return str(val)
```

### Forma idiomática 3.3: Despacho limpo e modular com `singledispatch`
```python
# CORRETO: extensivel e desacoplado
from functools import singledispatch

@singledispatch
def format_data(val: object) -> str:
    return str(val)

@format_data.register
def _(val: int) -> str:
    return f"int: {val:,}"

@format_data.register
def _(val: float) -> str:
    return f"float: {val:.2f}"

@format_data.register
def _(val: list) -> str:
    return f"list[{len(val)}]"
```

## 4. Enforcement

- **Sensor AST (`ast_sensor.py`):**
  - `PYF001`: Detecta funções aninhadas. Permite unicamente um `wrapper` interno decorado com `@wraps` ou `@functools.wraps`. Decoradores com 3 níveis de função disparam violação.
- **Sensor Estático (Ruff):**
  - `E731`: Proíbe atribuição de expressão `lambda` a variáveis (exige `def`).
  - `B019`: Alerta sobre uso perigoso de `lru_cache` ou `cache` em métodos de instância.
  - `FURB118`: Sugere substituição de lambdas triviais por `operator.itemgetter` ou `operator.attrgetter`.
- **Pyright Strict:**
  - Tipagem rigorosa de callables com `Callable[..., T]` e `ParamSpec` quando aplicável.

## 5. Exceções

- Decoradores simples de dois níveis sem argumentos continuam permitidos a definir a função interna `wrapper` isolada, desde que devidamente decorada com `@wraps`.
