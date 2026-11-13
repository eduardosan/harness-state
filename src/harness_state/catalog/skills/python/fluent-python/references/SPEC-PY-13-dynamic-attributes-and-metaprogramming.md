# SPEC-PY-13: Atributos Dinâmicos, Descritores e Metaprogramação

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 22: "Atributos dinâmicos e propriedades" (seções 22.2 a 22.8).
- Capítulo 23: "Descritores de atributos" (seções 23.2 a 23.6).
- Capítulo 24: "Metaprogramação de classes" (seções 24.2 a 24.12).

## 2. Regras normativas

1. **Uso de `@property` para atributos calculados ou validados [Livro]:**
   - Propriedades com `@property` **MUST** ser usadas para criar interfaces com sintaxe de atributo público simples com computação sob demanda ou validação de escrita.
   - **MUST NOT** definir métodos de acesso procedurais prolixos como `get_x()` ou `set_x()` para atributos simples de objetos Python.
2. **Controle cirúrgico de `__getattr__` sem recursão infinita [Livro]:**
   - Use `__getattr__` exclusivamente como fallback para chaves ou atributos ausentes dinâmicos (como clientes de RPC ou adaptadores de JSON).
   - Métodos `__getattr__` ou `__setattr__` **MUST** delegar acessos normais e lançar `AttributeError` para atributos desconhecidos, prevenindo loops de recursão infinita ao acessar atributos de instância internos via `self.__dict__` ou `super().__getattr__`.
3. **Descritores reutilizáveis com `__set_name__` [Livro]:**
   - Quando uma lógica de validação ou gerenciamento de atributo for repetida em múltiplos campos ou classes de dados, ela **MUST** ser extraída para uma classe de **Descritor** implementando o protocolo de descritor (`__get__`, `__set__`).
   - Descritores **MUST** implementar o método de ciclo de vida `__set_name__(self, owner, name)` para capturar automaticamente o nome do atributo gerenciado sem exigir argumentos redundantes no construtor.
4. **Hierarquia de complexidade em metaprogramação [Livro]:**
   - Metaprogramação de classes **MUST** seguir rigorosamente a ordem crescente de complexidade e custo cognitivo, adotando sempre a alternativa mais simples que resolve o problema:
     1. **Decorador de classe (`@decorator`):** inspeciona ou enriquece a classe logo após sua construção.
     2. **Método especial `__init_subclass__`:** hook nativo para personalizar subclasses de uma classe base sem complexidade de metaclasse.
     3. **Metaclasse (`class Meta(type):`):** reservada estritamente para cenários onde as duas alternativas anteriores são comprovadamente insuficientes (como alteração profunda da criação do dicionário de atributos antes da instanciação da classe com `__prepare__`).
5. **Diferenciação clara entre tempo de importação e tempo de execução [Livro]:**
   - Metaprogramação roda no tempo de importação dos módulos. Módulos **MUST NOT** executar efeitos colaterais lentos (como chamadas de rede ou conexões pesadas) durante a definição de classes e metaclasses.
6. **Segurança de execução e proibição de `eval`/`exec` [Política]:**
   - O uso de `eval()` e `exec()` é **estritamente proibido** no código da aplicação.
   - Chamadas a `getattr()` e `setattr()` com nomes dinâmicos recebidos de entradas externas não confiáveis **MUST** validar os nomes contra uma lista de atributos permitidos antes do acesso.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Getters e setters triviais estilo Java
```python
# ERRADO: antipadrao burocratico e nao-pythonico
class Product:
    def __init__(self, price: float) -> None:
        self._price = price

    def get_price(self) -> float:
        return self._price

    def set_price(self, value: float) -> None:
        if value < 0:
            raise ValueError("Preço não pode ser negativo")
        self._price = value
```

### Forma idiomática 3.1: Interface natural com `@property`
```python
# CORRETO: acesso limpo como atributo e validacao protegida
class Product:
    __slots__ = ("_price",)

    def __init__(self, price: float) -> None:
        self._price = price

    @property
    def price(self) -> float:
        return self._price

    @price.setter
    def price(self, value: float) -> None:
        if value < 0:
            raise ValueError("Preço não pode ser negativo")
        self._price = value
```

---

### Anti-padrão 3.2: Criação de metaclasse para validação simples de subclasses
```python
# ERRADO: excesso de complexidade conceitual com metaclasse para algo trivial
class ValidatedMeta(type):
    def __init__(cls, name, bases, attr_dict):
        super().__init__(name, bases, attr_dict)
        if not hasattr(cls, "TABLE_NAME"):
            raise TypeError(f"Classe {name} precisa definir TABLE_NAME")
```

### Forma idiomática 3.2: Hook moderno e limpo com `__init_subclass__`
```python
# CORRETO: simples, sem metaclasse e compreensivel
class ModelBase:
    TABLE_NAME: str

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not hasattr(cls, "TABLE_NAME") or not cls.TABLE_NAME:
            raise TypeError(f"Subclasse {cls.__name__} deve definir TABLE_NAME")
```

---

### Anti-padrão 3.3: Validação repetitiva de campos em múltiplos atributos
```python
# ERRADO: logica de validacao duplicada em dezenas de properties
class Entity:
    @property
    def field_a(self) -> str:
        return self._field_a

    @field_a.setter
    def field_a(self, val: str) -> None:
        if not val.strip():
            raise ValueError("Não pode ser vazio")
        self._field_a = val

    @property
    def field_b(self) -> str:
        return self._field_b

    @field_b.setter
    def field_b(self, val: str) -> None:
        if not val.strip():
            raise ValueError("Não pode ser vazio")
        self._field_b = val
```

### Forma idiomática 3.3: Descritor reutilizável com `__set_name__`
```python
# CORRETO: encapsulamento unico e reutilizavel com autodeteccao do nome
class NonEmptyString:
    def __set_name__(self, owner: type[object], name: str) -> None:
        self.storage_name = f"_{name}"

    def __get__(self, instance: object, owner: type[object]) -> str:
        if instance is None:
            return ""
        return str(getattr(instance, self.storage_name, ""))

    def __set__(self, instance: object, value: str) -> None:
        if not value or not value.strip():
            raise ValueError(f"O atributo {self.storage_name[1:]} não pode ser vazio")
        setattr(instance, self.storage_name, value)


class Entity:
    title = NonEmptyString()
    code = NonEmptyString()
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `B009` e `B010`: Alerta sobre usos desnecessários de `getattr`/`setattr` com literais estáticos constantes (sugere acesso direto).
  - `S307`: Proíbe expressamente invocação de `eval()`.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia termos como `__getattr__`, `__set_name__`, `__init_subclass__`, `@property`, `class.*\(type\)` para o grupo `E` e spec `PY-13`.
- **Pyright Strict:**
  - Tipagem rigorosa dos métodos do protocolo de descritor (`__get__`, `__set__`).

## 5. Exceções

- Em frameworks de ORM complexos ou sistemas de serialização que gerenciam a ordem e mapeamento de campos no momento de montagem da classe (como Django Models ou Pydantic v1), o uso interno de metaclasses é legítimo.
