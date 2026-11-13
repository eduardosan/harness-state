# SPEC-PY-10: Sobrecarga de Operadores

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 16: "Sobrecarga de operadores" (seções 16.2 a 16.9).

## 2. Regras normativas

1. **Retorno de novas instâncias e imutabilidade dos operandos [Livro]:**
   - Operadores aritméticos binários padrão (como `+` via `__add__`, `-` via `__sub__`, `*` via `__mul__`, `@` via `__matmul__`) **MUST** construir e retornar uma nova instância do objeto resultante.
   - Operadores binários padrão **MUST NOT** mutar qualquer um dos operandos originais envolvidos na expressão.
2. **Retorno obrigatório de `NotImplemented` em tipos incompatíveis [Livro]:**
   - Quando um método especial de operador recebe um operando com tipo não suportado, ele **MUST** retornar o singleton `NotImplemented` e **MUST NOT** lançar exceção direta (`raise TypeError(...)`).
   - Retornar `NotImplemented` permite ao interpretador Python acionar a versão refletida do operador (`__radd__`, `__rsub__` etc.) no operando da direita antes de emitir um `TypeError` definitivo.
3. **Pares refletidos e operadores atribuídos aumentados [Livro]:**
   - Sempre que um operador for comutativo ou aceitar operandos de tipos heterogêneos na direita (como escalares numéricos multiplicando vetores), **MUST** implementar o par refletido correspondente (`__radd__`, `__rmul__`).
   - Para classes que representam objetos mutáveis (como contêineres e coleções modificáveis), considere implementar a versão aumentada in-place (`__iadd__`, `__imul__`), retornando explicitamente `self`.
4. **Comparações ricas coerentes [Livro]:**
   - Métodos de comparação rica (`__eq__`, `__lt__`, `__le__`, `__gt__`, `__ge__`) também **MUST** retornar `NotImplemented` para tipos não comparáveis.
   - Para definir ordenação completa a partir de `__eq__` e `__lt__`, utilize `@functools.total_ordering` apenas quando a sobrecarga for estritamente necessária e o impacto de desempenho nos dunders sintetizados for aceitável.
5. **Significado inequívoco e parcimônia [Livro]:**
   - **MUST NOT** sobrecarregar operadores para operações que não possuam significado matemático ou conceitual evidente no domínio (evite inventar dunders como usar `+` para mesclar usuários ou `-` para excluir registros). Para ações com efeitos colaterais ou semântica ad-hoc, use métodos com nomes verbais claros.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Lançar `TypeError` em operador aritmético
```python
# ERRADO: interrompe o fluxo e impede o operando da direita de tentar __radd__
class Vector:
    def __init__(self, x: float, y: float) -> None:
        self.x = x
        self.y = y

    def __add__(self, other: object) -> "Vector":
        if not isinstance(other, Vector):
            raise TypeError("Operando deve ser um Vector")
        return Vector(self.x + other.x, self.y + other.y)
```

### Forma idiomática 3.1: Retornar `NotImplemented` de forma colaborativa
```python
# CORRETO: colabora com o runtime retornando NotImplemented
class Vector:
    __slots__ = ("_x", "_y")

    def __init__(self, x: float, y: float) -> None:
        self._x = x
        self._y = y

    def __add__(self, other: object) -> "Vector":
        if not isinstance(other, Vector):
            return NotImplemented
        return Vector(self._x + other._x, self._y + other._y)

    def __radd__(self, other: object) -> "Vector":
        return self.__add__(other)
```

---

### Anti-padrão 3.2: Mutação indevida de operando em operador padrão
```python
# ERRADO: operador '+' altera o proprio objeto 'self'
class Counter:
    def __init__(self, count: int) -> None:
        self.count = count

    def __add__(self, other: object) -> "Counter":
        if isinstance(other, int):
            self.count += other  # Muta o objeto original!
            return self
        return NotImplemented
```

### Forma idiomática 3.2: Retorno de nova instância independente
```python
# CORRETO: operador '+' puro gera novo objeto sem efeitos colaterais
class Counter:
    __slots__ = ("_count",)

    def __init__(self, count: int) -> None:
        self._count = count

    @property
    def count(self) -> int:
        return self._count

    def __add__(self, other: object) -> "Counter":
        if isinstance(other, int):
            return Counter(self._count + other)
        if isinstance(other, Counter):
            return Counter(self._count + other._count)
        return NotImplemented
```

## 4. Enforcement

- **Sensor AST (`ast_sensor.py`):**
  - `PYF003`: Identifica e proíbe expressamente instruções `raise TypeError` dentro de métodos de sobrecarga de operadores aritméticos e de comparação (`__add__`, `__sub__`, `__mul__`, `__matmul__`, `__truediv__`, `__floordiv__`, `__mod__`, `__pow__`, `__eq__`, `__lt__` etc.), exigindo `return NotImplemented`.
- **Pyright Strict:**
  - Validação estrita de tipos de operandos e tipos de retorno `Self | NotImplementedType`.

## 5. Exceções

- Métodos aritméticos refletidos ou aumentados que recebem tipos estritamente desconhecidos devem igualmente retornar `NotImplemented`.
