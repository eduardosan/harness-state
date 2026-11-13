# SPEC-PY-05: Fábricas de Classes de Dados

## 1. Fonte
*Python Fluente, 2ª ed.*, Capítulo 5: "Fábricas de classes de dados" (seções 5.2 a 5.8).

## 2. Regras normativas

1. **Escolha determinística da fábrica de dados [Livro]:**
   - Para estruturas imutáveis e leves com acesso posicional e por nome, o código **MUST** utilizar `typing.NamedTuple`.
   - Para entidades de dados com regras de validação, métodos ou campos derivados, o código **MUST** utilizar `@dataclasses.dataclass`.
   - Código novo **MUST NOT** utilizar dicionários heterogêneos desestruturados (`dict[str, Any]`) para representar entidades de domínio de negócio [Política].
2. **Otimização e proteção com slots e parâmetros nomeados [Política]:**
   - Novas classes decoradas com `@dataclass` **MUST** declarar `slots=True` e `kw_only=True` para otimização de memória e clareza na instanciação.
   - Entidades concebidas como *Value Objects* (imutáveis por definição) **MUST** declarar `frozen=True`.
3. **Inicialização de atributos mutáveis com `default_factory` [Livro]:**
   - Atributos de dataclasses que possuam coleções como valor inicial padrão **MUST** utilizar `field(default_factory=list)`, `field(default_factory=dict)` ou `field(default_factory=set)`.
   - É expressamente proibido declarar valores mutáveis diretos como padrão (`items: list[str] = []`).
4. **Validação e pós-inicialização explícita [Livro]:**
   - Quando campos dependem de cálculos derivados ou validações de invariantes de negócio na criação, a classe **MUST** implementar `__post_init__(self)`.
   - Parâmetros que existem apenas para parametrizar a construção e não devem virar atributos persistentes na instância **MUST** ser anotados com `dataclasses.InitVar`.
5. **Casamento de padrões compatível [Livro]:**
   - Dataclasses e `NamedTuple` geram `__match_args__` automaticamente. O código **MUST** aproveitar o *Pattern Matching* estrutural posicional (`match obj: case Item(id, name): ...`) para decomposição sem necessidade de acessos manuais encadeados.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Dicionários anônimos para representar entidades
```python
# ERRADO: sem contrato rigido, sem autocompletar, sujeito a erros de chave
def create_customer(data: dict) -> dict:
    return {"id": data["id"], "name": data["name"], "orders": []}
```

### Forma idiomática 3.1: `@dataclass` com `slots=True`, `kw_only=True` e `default_factory`
```python
# CORRETO: contrato explicito, seguro e otimizado
from dataclasses import dataclass, field


@dataclass(slots=True, kw_only=True)
class Customer:
    id: int
    name: str
    orders: list[str] = field(default_factory=list)
```

---

### Anti-padrão 3.2: Atributo mutável como valor padrão direto em dataclass
```python
# ERRADO: causa ValueError em execucao ou compartilha estado
from dataclasses import dataclass


@dataclass
class Group:
    name: str
    members: list[str] = []
```

### Forma idiomática 3.2: Uso de `field(default_factory=...)`
```python
# CORRETO: fabrica individual por instancia
from dataclasses import dataclass, field


@dataclass(slots=True, kw_only=True)
class Group:
    name: str
    members: list[str] = field(default_factory=list)
```

---

### Anti-padrão 3.3: Lógica complexa no construtor sobrescrevendo `__init__`
```python
# ERRADO: destrói a geração automática do __init__ do dataclass
@dataclass
class Coordinate:
    lat: float
    lon: float

    def __init__(self, lat: float, lon: float):
        if not (-90 <= lat <= 90):
            raise ValueError("Latitude invalida")
        self.lat = lat
        self.lon = lon
```

### Forma idiomática 3.3: Validação em `__post_init__`
```python
# CORRETO: preserva geracao de __init__, __repr__, __eq__ e valida
@dataclass(slots=True, kw_only=True, frozen=True)
class Coordinate:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not (-90 <= self.lat <= 90):
            raise ValueError(f"Latitude invalida: {self.lat}")
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `RUF008`: Mutável como default em dataclass.
  - `RUF009`: Chamada de função como default em dataclass.
  - `RUF012`: Anotação mutável em atributo de classe sem `ClassVar`.
  - `B006`: Argumentos padrão mutáveis.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia `@dataclass`, `NamedTuple` para grupo `A` e spec `PY-05`.
- **Pyright Strict:**
  - Validação estrita dos tipos de todos os campos declarados.

## 5. Exceções

- Tipos de dados interoperáveis com ORMs externos (SQLAlchemy, Pydantic, Django Models) seguem os construtores de classe de seus respectivos frameworks.
- Coleções genéricas temporárias dentro do escopo de um único algoritmo podem utilizar dicts/tuplas locais.
