# SPEC-PY-01: Modelo de Dados e Objeto Pythônico

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 1: "O modelo de dados de Python" (seções 1.2 a 1.5).
- Capítulo 11: "Um objeto pythônico" (seções 11.2 a 11.12).
- Capítulo 12: "Métodos especiais para sequências" (seções 12.2 a 12.8).

## 2. Regras normativas

1. **Representação canônica inequívoca [Livro]:**
   - Classes de domínio e objetos de serviço **MUST** implementar `__repr__`. A representação deve ser inequívoca, informativa para depuração e, sempre que prático, permitir recriar o objeto via `eval(repr(obj))`.
   - O método `__str__` **MUST** ser implementado apenas quando for necessária uma saída amigável e legível para usuários finais distinta do `__repr__`. Se `__str__` não for implementado, o Python recorre automaticamente ao `__repr__`.
2. **Adoção nativa do Python Data Model sobre métodos inventados [Livro]:**
   - Objetos que emulam coleções ou agregados **MUST** implementar os métodos especiais correspondentes (`__len__`, `__getitem__`, `__contains__`, `__bool__`).
   - É proibido criar métodos como `get_size()`, `size()`, `item_at(index)` ou `is_empty()` quando a semântica for de contêiner [Livro].
3. **Coerência entre igualdade e tabela hash [Livro]:**
   - Classes que implementam `__eq__` e são destinadas a serem usadas como elementos de conjuntos ou chaves de dicionários **MUST** implementar um `__hash__` coerente e imutável.
   - Objetos mutáveis que implementam `__eq__` **MUST** definir `__hash__ = None` para explicitar sua não-hasheabilidade.
4. **Construtores alternativos e métodos de classe [Livro]:**
   - Construtores alternativos (ex: desserialização a partir de JSON, bytes ou dicionários) **MUST** ser implementados como `@classmethod` que recebem `cls` como primeiro parâmetro.
   - O decorador `@staticmethod` **MUST NOT** ser usado para métodos que seriam melhor expressos como funções de módulo isoladas [Livro].
5. **Pattern matching e atributos com `__match_args__` [Livro]:**
   - Classes regulares que suportam casamento de padrões posicional **MUST** declarar a tupla de strings `__match_args__` listando a ordem dos atributos esperados nos blocos `match/case`.
6. **Otimização com `__slots__` [Livro]:**
   - Classes com muitas instâncias de curta duração ou alto volume de memória **MUST** considerar o uso de `__slots__` para restringir o dicionário dinâmico de atributos `__dict__` e reduzir o consumo de RAM.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Falta de `__repr__` e métodos de coleção inventados
```python
# ERRADO: sem representacao em logs e metodos ad-hoc
class Team:
    def __init__(self, members: list[str]):
        self.members = members

    def get_size(self) -> int:
        return len(self.members)

    def has_member(self, name: str) -> bool:
        return name in self.members
```

### Forma idiomática 3.1: Python Data Model com dunders
```python
# CORRETO: integra-se com len(team), "alice" in team, repr(team)
from collections.abc import Iterator

class Team:
    __slots__ = ("_members",)

    def __init__(self, members: list[str]) -> None:
        self._members = list(members)

    def __len__(self) -> int:
        return len(self._members)

    def __contains__(self, name: object) -> bool:
        return name in self._members

    def __iter__(self) -> Iterator[str]:
        return iter(self._members)

    def __repr__(self) -> str:
        return f"Team({self._members!r})"
```

---

### Anti-padrão 3.2: Implementar `__eq__` sem definir `__hash__`
```python
# ERRADO: classe define igualdade mas vira unhashable silenciosamente
class Point:
    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return (self.x, self.y) == (other.x, other.y)
```

### Forma idiomática 3.2: `__eq__` acompanhado de `__hash__` coerente
```python
# CORRETO: par coerente imutavel
class Point:
    __slots__ = ("_x", "_y")
    __match_args__ = ("x", "y")

    def __init__(self, x: int, y: int) -> None:
        self._x = x
        self._y = y

    @property
    def x(self) -> int:
        return self._x

    @property
    def y(self) -> int:
        return self._y

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Point):
            return NotImplemented
        return (self._x, self._y) == (other.x, other.y)

    def __hash__(self) -> int:
        return hash((self._x, self._y))

    def __repr__(self) -> str:
        return f"Point({self._x!r}, {self._y!r})"
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `PLW1641`: Alerta sobre classes que implementam `__eq__` sem implementar `__hash__`.
  - `B903`: Recomenda o uso de `@dataclass` ou namedtuple para classes que são meros contêineres de atributos.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia dunders do modelo de dados (`__repr__`, `__len__`, `__getitem__`, `__match_args__`, `__slots__`) para o grupo `A` e spec `PY-01`.
- **Pyright Strict:**
  - Anotações estritas de retorno em todos os métodos especiais.

## 5. Exceções

- Classes que herdam de `@dataclass` ou `NamedTuple` já recebem implementações automáticas e otimizadas de `__repr__`, `__eq__` e `__match_args__`.
