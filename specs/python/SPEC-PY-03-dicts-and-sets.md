# SPEC-PY-03: Dicionários e Conjuntos

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 3: "Dicionários e conjuntos" (seções 3.2 a 3.12).

## 2. Regras normativas

1. **Sintaxe moderna de fusão e mesclagem de dicionários [Livro]:**
   - Para combinar ou mesclar dicionários, prefira os operadores de união `|` e `|=` (introduzidos no Python 3.9) ou desempacotamento `{**a, **b}` em vez de invocar repetidamente `.update()` em dicionários intermediários descartáveis.
   - Compreensões de dicionário (`{k: v for ...}`) e de conjunto (`{v for ...}`) **MUST** ser preferidas para construir mapeamentos transformados.
2. **Tratamento de chaves ausentes idiomático [Livro]:**
   - Ao atualizar coleções ou listas dentro de um dicionário sob chaves potencialmente inexistentes, use `dict.setdefault()`, `collections.defaultdict` ou o método especial `__missing__()` em subclasses de mapeamento.
   - **MUST NOT** realizar checagem duplicada com `if key in d: ... else: ...` seguida de atribuição redundante (`SIM401`).
3. **Subclasse de mapeamento personalizada via `UserDict` [Livro]:**
   - Classes personalizadas que especializam comportamento de dicionários **MUST** herdar de `collections.UserDict` e **MUST NOT** herdar diretamente de `dict`. Herdar de `dict` quebra o polimorfismo interno em métodos como `update()`, `setdefault()` e `__init__()`.
4. **Proteção de mapeamentos imutáveis com `MappingProxyType` [Livro]:**
   - Quando um módulo ou classe expõe uma visão somente leitura de um dicionário interno, ele **MUST** envolver a estrutura com `types.MappingProxyType` em vez de retornar o dicionário mutável original ou criar cópias completas constantes.
5. **Operações matemáticas de conjuntos e visões de dicionário [Livro]:**
   - As visões retornadas por `dict.keys()`, `dict.items()` operam como conjuntos e suportam operadores de união (`|`), interseção (`&`) e diferença (`-`). Use essas operações diretamente em vez de converter desnecessariamente para `set()` ou iterar em laços manuais.
6. **Integridade de iteração e independência de ordem [Política]:**
   - O código **MUST NOT** adicionar ou remover chaves de um dicionário ou conjunto durante a iteração sobre ele. Para mutações durante filtragens, itere sobre uma cópia de chaves (`list(d.keys())`) ou crie um novo dicionário via compreensão.
   - O código **MUST NOT** assumir qualquer garantia de ordenação para instâncias de `set` ou `frozenset`.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Tratamento manual e ineficiente de chaves ausentes
```python
# ERRADO: duas buscas de chave na tabela hash e codigo prolixo
groups: dict[str, list[str]] = {}
for category, item in entries:
    if category in groups:
        groups[category].append(item)
    else:
        groups[category] = [item]
```

### Forma idiomática 3.1: Uso de `setdefault` ou `defaultdict`
```python
# CORRETO: uma unica busca de chave na hash table
groups: dict[str, list[str]] = {}
for category, item in entries:
    groups.setdefault(category, []).append(item)

# OU utilizando collections.defaultdict:
from collections import defaultdict

grouped: defaultdict[str, list[str]] = defaultdict(list)
for category, item in entries:
    grouped[category].append(item)
```

---

### Anti-padrão 3.2: Herança direta da classe nativa `dict`
```python
# ERRADO: dunder __getitem__ e ignorado por metodos C internos como dict.update
class NormalizedDict(dict[str, str]):
    def __getitem__(self, key: str) -> str:
        return super().__getitem__(key.lower())
```

### Forma idiomática 3.2: Especialização limpa com `collections.UserDict`
```python
# CORRETO: UserDict garante polimorfismo correto em todos os metodos
from collections import UserDict

class NormalizedDict(UserDict[str, str]):
    def __getitem__(self, key: str) -> str:
        return str(super().__getitem__(key.lower()))

    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(key.lower(), value)

    def __contains__(self, key: object) -> bool:
        if isinstance(key, str):
            return super().__contains__(key.lower())
        return False
```

---

### Anti-padrão 3.3: Exposição de dicionário mutável interno
```python
# ERRADO: cliente externo pode mutar o dicionario e corromper o estado
class ServiceRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, str] = {}

    def get_services(self) -> dict[str, str]:
        return self._registry
```

### Forma idiomática 3.3: Exposição de visão imutável com `MappingProxyType`
```python
# CORRETO: visualizacao dinâmica somente-leitura sem custo de copia
from types import MappingProxyType

class ServiceRegistry:
    def __init__(self) -> None:
        self._registry: dict[str, str] = {}
        self.services = MappingProxyType(self._registry)

    def register(self, name: str, url: str) -> None:
        self._registry[name] = url
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `SIM401`: Detecta o padrão manual `if key in d: ... else: ...` recomendando `dict.get` ou `dict.setdefault`.
  - `SIM118`: Recomenda o uso de `key in d` em vez de `key in d.keys()`.
  - `C4` (flake8-comprehensions): Detecta geradores e compreensões de dicionários e conjuntos redundantes.
- **Sensor AST (`ast_sensor.py`):**
  - `PYF002`: Proíbe expressamente herança direta de `dict`, `list` e `set`.
- **Pyright Strict:**
  - Garante tipagem estrita de chaves e valores em mapeamentos e conjuntos.

## 5. Exceções

- Herança direta de tipos especiais com garantia de interface ABC ou classes abstratas (`collections.abc.Mapping`, `collections.abc.MutableMapping`) é incentivada quando não se deseja a base de armazenamento em memória de `UserDict`.
