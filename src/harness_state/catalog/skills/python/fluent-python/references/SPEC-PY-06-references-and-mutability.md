# SPEC-PY-06: Referências, Mutabilidade e Memória

## 1. Fonte
*Python Fluente, 2ª ed.*, Capítulo 6: "Referências, mutabilidade, e memória" (seções 6.2 a 6.7).

## 2. Regras normativas

1. **Parâmetros com valor padrão mutável são terminantemente proibidos [Livro]:**
   - Funções **MUST NOT** utilizar objetos mutáveis (`list`, `dict`, `set`, instâncias mutáveis) como valor padrão de parâmetros.
   - Funções **MUST** utilizar `None` como valor sentinela padrão e inicializar a coleção no corpo da função caso o argumento seja `None`.
2. **Comparação de identidade restrita a singletons [Livro]:**
   - O operador `is` **MUST** ser utilizado exclusivamente para checar identidade contra singletons conhecidos (`None`, `NotImplemented`, `Ellipsis`).
   - Comparações de valor entre inteiros, strings, floats ou coleções **MUST** utilizar `==` ou `!=`.
3. **Semântica de cópia explícita [Livro]:**
   - Cópias superficiais (*shallow copy*) **MUST** ser criadas via construtor do tipo (`list(seq)`, `dict(d)`) ou `copy.copy()`.
   - Quando o objeto contiver estruturas aninhadas mutáveis que não devam ser compartilhadas, o código **MUST** utilizar `copy.deepcopy()`.
4. **Proteção contra mutação inesperada de argumentos [Livro]:**
   - Funções que recebem coleções mutáveis **MUST NOT** modificá-las no lugar (*in-place*) a menos que essa seja a responsabilidade explicitamente documentada no nome ou docstring da função.
   - Caso a função precise apenas ler ou transformar os itens, ela **MUST** criar uma cópia defensiva ou consumir iteradores de forma pura.
5. **Ciclo de vida e desalocação de recursos [Livro]:**
   - Código **MUST NOT** depender do método especial `__del__` ou de `del obj` para liberar recursos críticos (conexões, descritores de arquivo, locks).
   - A liberação de recursos **MUST** ser garantida através de gerenciadores de contexto (`with` / `async with`).

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Argumento padrão mutável acumula estado entre chamadas
```python
# ERRADO: a lista [] e criada uma unica vez e compartilhada
def append_item(value: int, items: list[int] = []) -> list[int]:
    items.append(value)
    return items
```

### Forma idiomática 3.1: Valor padrão sentinela `None`
```python
# CORRETO: cada chamada sem argumento cria uma nova lista
def append_item(value: int, items: list[int] | None = None) -> list[int]:
    actual_items = list(items) if items is not None else []
    actual_items.append(value)
    return actual_items
```

---

### Anti-padrão 3.2: Uso de `is` para igualdade de valor
```python
# ERRADO: 'is' checa se apontam para o mesmo endereco de memoria
if status is "ACTIVE":
    process()
```

### Forma idiomática 3.2: Uso de `==` para igualdade e `is` apenas para singletons
```python
# CORRETO: igualdade de conteudo com ==; identidade com is None
if status == "ACTIVE" and extra_flag is not None:
    process()
```

---

### Anti-padrão 3.3: Mutação indesejada de coleção passada por referência
```python
# ERRADO: altera a lista do chamador sem aviso
def sanitize_tags(tags: list[str]) -> list[str]:
    for i, tag in enumerate(tags):
        tags[i] = tag.strip().lower()
    return tags
```

### Forma idiomática 3.3: Criação de nova coleção sem efeitos colaterais
```python
# CORRETO: cria uma nova colecao pura
def sanitize_tags(tags: list[str]) -> list[str]:
    return [tag.strip().lower() for tag in tags]
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `B006`: Detecta argumentos padrão mutáveis em funções.
  - `B008`: Detecta chamadas de funções em valores padrão.
  - `F632`: Detecta o uso de `is`/`is not` com literais (strings, ints, etc.).
  - `E711`, `E712`: Checagem idiomática contra `None` e booleanos.
- **Sensor AST:**
  - `spec_router.py`: Roteia diffs contendo `copy.`, `is None`, argumentos padrão para o grupo `A` e spec `PY-06`.
- **Avaliação Semântica (DeepEval):**
  - Métrica de pureza funcional e ausência de efeitos colaterais ocultos.

## 5. Exceções

- Métodos cujo propósito exclusivo seja alterar a instância interna (ex: métodos `append()`, `extend()`, `update()`) podem mutar `self`.
- Métodos de fábricas internas ou singletons globais do domínio podem verificar identidade via `is` contra a instância única documentada.
