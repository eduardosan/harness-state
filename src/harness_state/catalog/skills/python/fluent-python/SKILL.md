---
name: fluent-python
description: >
  Diretrizes avançadas e regras de engenharia idiomática baseadas no livro Python Fluente (2ª ed.).
  Contempla as 13 especificações canônicas (SPEC-PY-01 a SPEC-PY-13) agrupadas nos 5 eixos temáticos (A a E):
  Data Model, Coleções, Funções/Decoradores, Tipagem Estrita, Protocolos/ABCs, Concorrência/Async e Metaprogramação.
  Use esta skill para projetar classes, estruturas de dados, métodos especiais, decoradores e fluxos assíncronos.
---

# Fluent Python Engineering Standards (SPEC-PY-00 a SPEC-PY-13)

Esta skill codifica o padrão oficial de Python Fluente para todos os módulos e microsserviços Python da organização.

## Visão Geral dos 5 Grupos Temáticos

| Grupo | Specs | Tema Principal | Arquivo de Referência |
|---|---|---|---|
| **A** | `PY-01`, `PY-02`, `PY-03`, `PY-05`, `PY-06` | Data Model, Sequências, Dicts/Sets, Dataclasses, Memória | `references/SPEC-PY-01-data-model.md`, `references/SPEC-PY-05-data-class-builders.md`, etc. |
| **B** | `PY-07`, `PY-08` | Funções, Closures, Decoradores e Dicas de Tipagem Estrita | `references/SPEC-PY-07-functions-and-decorators.md`, `references/SPEC-PY-08-type-hints.md` |
| **C** | `PY-09`, `PY-10` | Protocolos, ABCs, Herança e Sobrecarga de Operadores | `references/SPEC-PY-09-protocols-and-abcs.md`, `references/SPEC-PY-10-operator-overloading.md` |
| **D** | `PY-04`, `PY-11`, `PY-12` | Unicode/Bytes, Geradores, Context Managers (`with`) e Async | `references/SPEC-PY-04-text-and-bytes.md`, `references/SPEC-PY-11-iterators-generators-and-context.md`, `references/SPEC-PY-12-concurrency-and-async.md` |
| **E** | `PY-13` | Atributos Dinâmicos, Descritores e Metaprogramação | `references/SPEC-PY-13-dynamic-attributes-and-metaprogramming.md` |

---

## Regras de Ouro Inegociáveis por Grupo

### Grupo A: Modelo de Dados, Coleções e Registros
1. **Representação Inequívoca (`PY-01`):** Todas as classes de domínio devem implementar `__repr__` informativo para depuração e logs.
2. **Métodos Especiais Nativo (`PY-01`):** Use dunders (`__len__`, `__getitem__`, `__contains__`) em vez de métodos inventados como `get_size()` ou `has_item()`.
3. **Sem Herança de Built-ins (`PY-03` / `PYF002`):** NUNCA herde diretamente de `dict`, `list` ou `set`. Use `collections.UserDict`, `collections.UserList` ou composição.
4. **Data Classes Otimizadas (`PY-05`):** Prefira `@dataclass(slots=True, kw_only=True)` para agregados e DTOs, reduzindo overhead de memória.
5. **Sem Argumentos Default Mutáveis (`PY-06` / `PYF004`):** É expressamente proibido usar `def fn(items=[])` ou `def fn(params={})`. Utilize `None` e inicialize no corpo da função.

### Grupo B: Funções, Decoradores e Tipagem
1. **Sem Funções Aninhadas (`PY-07` / `PYF001`):** Funções dentro de funções são estritamente proibidas pela AST. A única exceção é o wrapper interno de um decorador simples com `@functools.wraps`. Decoradores parametrizados DEVEM ser classes com `__call__` ou `functools.partial`.
2. **Tipagem Estrita com Pyright (`PY-08`):** Todo código deve satisfazer a checagem de tipos estática sem o uso arbitrário de `Any`. Use `Protocol`, `TypeVar` ou genéricos explícitos.

### Grupo C: Protocolos, Interfaces e Operadores
1. **Tipagem Estrutural com `Protocol` (`PY-09`):** Prefira `typing.Protocol` com `@runtime_checkable` para interfaces sobre herança múltipla rígida de ABCs.
2. **Sobrecarga Segura de Operadores (`PY-10` / `PYF003`):** Métodos dunder de operadores (`__add__`, `__eq__`, etc.) que não reconhecem o tipo do operando recebido DEVEM retornar `NotImplemented`, NUNCA levantar `TypeError`.

### Grupo D: Textos, Iteradores e Concorrência Assíncrona
1. **Sanduíche Unicode (`PY-04`):** Decodifique bytes para `str` na borda de entrada; processe internamente 100% em `str` (NFC); codifique para `bytes` na saída.
2. **Geradores e `yield from` (`PY-11`):** Sub-geradores devem ser delegados via `yield from`, mantendo a assinatura limpa de iteração.
3. **Async Estruturado (`PY-12`):** Em Python 3.11+, use `asyncio.TaskGroup` para gerenciamento concorrente determinístico de tarefas assíncronas.

### Grupo E: Descritores e Metaprogramação
1. **Evite Metaclasses Quando Possível (`PY-13`):** Prefira `__init_subclass__` para validação e registro de subclasses em tempo de instanciação.

---

## Como Navegar nos Detalhes

Para consultar os anti-padrões e as soluções canônicas completas com exemplos de código, leia diretamente os arquivos da pasta `references/` correspondentes à área em desenvolvimento.
