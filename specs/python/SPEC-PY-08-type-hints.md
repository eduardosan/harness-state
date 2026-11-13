# SPEC-PY-08: Dicas de Tipo e Anotações Estáticas

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 8: "Dicas de tipo em funções" (seções 8.2 a 8.7).
- Capítulo 15: "Mais sobre dicas de tipo" (seções 15.2 a 15.8: genéricos, variância, TypeVar e protocolos).
- Seções 17.12 ("Dicas de tipo para geradores") e 21.12 ("Dicas de tipo para corrotinas assíncronas").

## 2. Regras normativas

1. **Princípio da Tipagem Gradual e Fronteiras Públicas [Livro]:**
   - Todas as funções, métodos, atributos e constantes expostos publicamente em módulos **MUST** conter anotações de tipo completas e precisas.
   - Variáveis locais simples com inferência inequívoca não exigem anotação redundante, mantendo o código limpo.
2. **Princípio de Robustez: Abstrato na Entrada, Concreto na Saída [Livro]:**
   - Parâmetros de funções **MUST** usar os tipos mais abstratos possíveis da hierarquia de coleções (`collections.abc.Iterable`, `collections.abc.Sequence`, `collections.abc.Mapping`).
   - O retorno de funções **MUST** indicar o tipo concreto específico retornado (`list[str]`, `dict[str, int]`, `tuple[int, ...]`) ou `Iterator[T]` para geradores.
3. **Erradicação de `Any` não documentado e tipos opcionais explícitos [Política]:**
   - O uso do tipo `Any` é estritamente desencorajado. Quando for indispensável para interagir com bibliotecas externas legadas dinâmicas, ele **MUST** ser acompanhado de um comentário justificando o motivo da ausência de tipo estrito.
   - Parâmetros que aceitam valor nulo **MUST** expressar união com `None` de forma explícita (`T | None`), preferindo a sintaxe moderna da PEP 604 sobre `Optional[T]`.
4. **Sobrecarga de assinaturas com `@overload` [Livro]:**
   - Funções cujo tipo de retorno varia deterministicamente de acordo com o tipo ou valor de um argumento de entrada **MUST** declarar assinaturas com `@typing.overload` antes da implementação concreta.
5. **Esquemas estruturados para dados com `TypedDict` [Livro]:**
   - Para estruturas de dados de dicionário (como cargas úteis JSON de APIs e configurações de banco de dados), utilize `typing.TypedDict` com parâmetros tipados em vez de `dict[str, Any]`.
6. **Sintaxe moderna de tipos genéricos e conformidade com Python 3.12+ [Política]:**
   - Como o ecossistema opera sob Python 3.12+, é recomendado o uso da nova sintaxe de parâmetros de tipo (`def process[T](items: list[T]) -> T:` ou `class Repository[T]:`) ou a declaração explícita de `TypeVar` delimitados.
7. **Modo Strict no verificador estático obrigatório [Política]:**
   - Todos os repositórios-alvo **MUST** configurar o verificador de tipos `pyright` com `typeCheckingMode = "strict"`.
   - Projetos existentes com débitos técnicos legados utilizam o script de baseline incremental `type_baseline.py` para bloquear regressões e permitir amortização contínua.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Assinatura excessivamente restritiva na entrada
```python
# ERRADO: obriga o chamador a passar estritamente list, rejeitando tuplas ou sets
def calculate_total(amounts: list[float]) -> float:
    return sum(amounts)
```

### Forma idiomática 3.1: Tipo abstrato flexível na entrada
```python
# CORRETO: aceita qualquer iteravel de floats (list, tuple, generator, set)
from collections.abc import Iterable

def calculate_total(amounts: Iterable[float]) -> float:
    return sum(amounts)
```

---

### Anti-padrão 3.2: Uso permissivo de `dict[str, Any]` para dados estruturados
```python
# ERRADO: nenhum suporte de autocompletar ou verificacao de chaves
def register_user(data: dict[str, Any]) -> None:
    db.insert(data["user_id"], data["email"])
```

### Forma idiomática 3.2: Contrato inequívoco com `TypedDict`
```python
# CORRETO: campos e tipos estritamente validados pelo pyright
from typing import TypedDict

class UserPayload(TypedDict):
    user_id: int
    email: str
    is_active: bool

def register_user(data: UserPayload) -> None:
    db.insert(data["user_id"], data["email"])
```

---

### Anti-padrão 3.3: Ausência de `@overload` para retornos condicionados ao tipo
```python
# ERRADO: tipo de retorno vira Union generica, perdendo precisao no chamador
def parse_id(value: int | str) -> int | str:
    if isinstance(value, int):
        return value
    return str(value).strip()
```

### Forma idiomática 3.3: Assinaturas precisas com `@overload`
```python
# CORRETO: pyright infere o tipo exato baseado no argumento passado
from typing import overload

@overload
def parse_id(value: int) -> int: ...

@overload
def parse_id(value: str) -> str: ...

def parse_id(value: int | str) -> int | str:
    if isinstance(value, int):
        return value
    return str(value).strip()
```

## 4. Enforcement

- **Sensor Pyright (Strict):**
  - Execução contínua via `type_baseline.py check` no comando `just check`.
  - Reporta tipos não anotados, inferências ambíguas e acessos a atributos inexistentes.
- **Sensor Estático (Ruff):**
  - `ANN` (flake8-annotations): Verifica ausência de anotações em argumentos e retornos públicos.
  - `UP007`: Impõe o uso de `X | None` em vez de `Optional[X]`.
  - `PYI` (flake8-pyi): Recomendações modernas de tipagem estática.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia termos como `overload`, `TypedDict`, `TypeVar`, `Iterable[`, `Sequence[` e `typeCheckingMode` para o grupo `B` e spec `PY-08`.

## 5. Exceções

- Métodos mágicos de inicialização como `__init__` retornam implicitamente `None` e sua anotação `-> None` é opcional pelo Ruff em algumas configurações, mas recomendada.
