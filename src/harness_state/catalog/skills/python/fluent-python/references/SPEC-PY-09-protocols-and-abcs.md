# SPEC-PY-09: Protocolos, ABCs e Herança

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 13: "Interfaces, protocolos e ABCs" (seções 13.1 a 13.6).
- Capítulo 14: "Herança: o bom, o mau e o feio" (seções 14.2 a 14.7).

## 2. Regras normativas

1. **Os Quatro Estilos de Tipagem e Escolha Consciente [Livro]:**
   - Reconheça as 4 formas de tipagem do Python e escolha a mais simples que atenda à necessidade:
     - **Tipagem Pato (Duck typing):** contratos implícitos em tempo de execução sem anotações rígidas.
     - **Tipagem Ganso (Goose typing):** verificação em tempo de execução via `isinstance(obj, ABC)` usando as classes abstratas de `collections.abc`.
     - **Tipagem Estática:** anotações nominais rígidas (`class Dog(Animal):`).
     - **Tipagem Estática de Pato:** subtipagem estrutural através de `typing.Protocol`.
2. **Desacoplamento de dependências com `typing.Protocol` [Livro]:**
   - Para contratos de interface entre diferentes módulos ou subsistemas, **MUST** preferir `typing.Protocol` (subtipagem estrutural). O consumidor define a interface necessária e o produtor a implementa sem acoplamento de herança explícita.
   - Use o decorador `@typing.runtime_checkable` apenas quando for estritamente indispensável checar conformidade estrutural em tempo de execução via `isinstance`.
3. **Checagem de tipos em tempo de execução com `collections.abc` [Livro]:**
   - Ao inspecionar tipos em tempo de execução, **MUST** usar as ABCs de `collections.abc` (ex: `isinstance(x, collections.abc.Sequence)` ou `isinstance(x, collections.abc.Mapping)`) e **MUST NOT** checar tipos concretos como `isinstance(x, list)` ou `isinstance(x, dict)`.
4. **Criação criteriosa de novas ABCs [Livro]:**
   - Classes abstratas próprias herdando de `abc.ABC` só devem ser criadas quando houver múltiplos provedores concretos implementados ou se for fundamental impor um template method com `@abc.abstractmethod`.
5. **Proibição de herança direta de tipos embutidos nativos [Livro]:**
   - Classes de domínio **MUST NOT** herdar diretamente de tipos primitivos embutidos em C (`list`, `dict`, `set`, `str`).
   - Para estender coleções, utilize `collections.UserList`, `collections.UserDict`, `collections.UserString` ou componha uma lista/dicionário encapsulado.
6. **Regras de herança múltipla, `super()` e composição [Livro]:**
   - Toda invocação de métodos de superclasse **MUST** utilizar `super()` para respeitar a Ordem de Resolução de Métodos (MRO).
   - Herança múltipla deve ser reservada para classes Mixin leves e focadas, sem estado persistente próprio.
   - Aplique rigorosamente a máxima da engenharia de software: **"Favoreça composição sobre herança"**.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Acoplamento nominal rígido com herança de classe base
```python
# ERRADO: consumidor e produtor acoplados rigidamente a uma classe abstrata
from abc import ABC, abstractmethod


class Notifier(ABC):
    @abstractmethod
    def send(self, message: str) -> None: ...


class SlackService(Notifier):  # Acoplamento desnecessario
    def send(self, message: str) -> None:
        post_slack(message)
```

### Forma idiomática 3.1: Subtipagem estrutural elegante com `typing.Protocol`
```python
# CORRETO: quem precisa do servico define seu proprio protocolo desacoplado
from typing import Protocol


class MessageSender(Protocol):
    def send(self, message: str) -> None: ...


class SlackService:  # Implementa estruturalmente sem herdar
    def send(self, message: str) -> None:
        post_slack(message)


def notify_alert(sender: MessageSender, text: str) -> None:
    sender.send(text)
```

---

### Anti-padrão 3.2: Herança direta de `list` quebrando métodos nativos
```python
# ERRADO: metodos C como list.extend() ou slicing nao chamam append sobrescrito
class DistinctList(list[int]):
    def append(self, item: int) -> None:
        if item not in self:
            super().append(item)
```

### Forma idiomática 3.2: Especialização confiável com `collections.UserList`
```python
# CORRETO: UserList garante comportamento uniforme em todas as operacoes
from collections import UserList


class DistinctList(UserList[int]):
    def append(self, item: int) -> None:
        if item not in self.data:
            super().append(item)
```

---

### Anti-padrão 3.3: Verificação de tipo concreto fechada
```python
# ERRADO: rejeita tuplas, deques ou subclasses validas
def process_items(items: object) -> None:
    if not isinstance(items, list):
        raise TypeError("items must be a list")
```

### Forma idiomática 3.3: Tipagem Ganso aberta com `collections.abc.Sequence`
```python
# CORRETO: aceita qualquer sequencia valida do modelo de dados
from collections.abc import Sequence


def process_items(items: object) -> None:
    if not isinstance(items, Sequence):
        raise TypeError("items must be a Sequence")
```

## 4. Enforcement

- **Sensor AST (`ast_sensor.py`):**
  - `PYF002`: Proíbe classes que herdam diretamente de `dict`, `list` e `set`.
- **Sensor Estático (Ruff):**
  - `B024`: Identifica classes abstratas declaradas sem nenhum método abstrato `@abstractmethod`.
  - `B027`: Alerta sobre métodos vazios em classes abstratas sem o decorador `@abstractmethod`.
  - `PLR0904`: Alerta sobre número excessivo de métodos públicos derivados de hierarquias infladas.
- **Pyright Strict:**
  - Verificação estática automática da conformidade estrutural com instâncias de `Protocol`.

## 5. Exceções

- Classes que herdam de `collections.abc.Mapping` ou `collections.abc.MutableMapping` implementando os dunders abstratos necessários são expressamente encorajadas quando não se quer utilizar a base `UserDict`.
