# SPEC-PY-02: Sequências e Compreensões

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 2: "Uma coleção de sequências" (seções 2.2 a 2.10).
- Capítulo 17: "Iteradores, geradores e clássicos" (seção 17.7: "Expressões geradoras").

## 2. Regras normativas

1. **Compreensões expressivas sobre `map`/`filter` com `lambda` [Livro]:**
   - Compreensões de lista (`listcomps`) e expressões geradoras (`genexps`) **MUST** ser preferidas no lugar de chamadas a `map()` ou `filter()` combinadas com funções `lambda` triviais.
   - Compreensões de lista **MUST** ser usadas exclusivamente para criar novas listas.
2. **Ausência de efeitos colaterais em compreensões [Política]:**
   - Compreensões **MUST NOT** ser usadas para executar efeitos colaterais ou mutações de estado (como invocar `print()`, mutar listas externas ou chamar métodos de I/O dentro da compreensão). Para efeitos colaterais, use laços `for` convencionais.
3. **Limite de complexidade e aninhamento [Política]:**
   - Compreensões **MUST NOT** conter mais de 2 níveis de laços `for` ou condições lógicas compostas complexas que prejudiquem a legibilidade. Expressões com 3 ou mais níveis devem ser divididas em laços `for` explícitos ou funções geradoras auxiliares.
4. **Desempacotamento paralelo e captura com estrela [Livro]:**
   - Código que extrai elementos de sequências ou tuplas **MUST** preferir o desempacotamento paralelo canônico (`a, b = seq` ou `head, *tail = seq`) em vez de indexações manuais repetitivas por índice numérico (`seq[0]`, `seq[1]`).
   - Padrões de correspondência estrutural (`match/case`) **MUST** ser considerados para desempacotamento e validação de estruturas aninhadas.
5. **Diferenciação consciente entre `sort()` no local e `sorted()` [Livro]:**
   - Métodos `list.sort()` alteram a lista no local e retornam `None`. A função built-in `sorted()` constrói e retorna uma nova lista ordenada. O desenvolvedor **MUST** escolher conscientemente entre os dois e **MUST NOT** atribuir o retorno de `seq.sort()`.
6. **Evitar armadilhas de multiplicação de referências mutáveis [Livro]:**
   - A sintaxe `[item] * n` **MUST NOT** ser usada quando `item` for um objeto mutável (ex: `[[0] * n] * m`), pois isso duplica referências ao mesmo objeto na memória em vez de instanciar novos objetos. Use compreensões com instâncias novas: `[[0] * n for _ in range(m)]`.
7. **Seleção da estrutura de dados correta além de `list` [Livro]:**
   - Quando a semântica envolver inserção/remoção frequente nas duas pontas, use `collections.deque`. Quando envolver arrays homogêneos numéricos grandes em memória contígua, use `array.array` ou `memoryview`. Quando a ordem for irrelevante e a busca for por pertinência rápida, use `set`.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Uso de `map`/`filter` com lambdas ilegíveis
```python
# ERRADO: sintaxe poluta com funcoes lambda e conversao obrigatoria para list
evens_squared = list(map(lambda x: x * x, filter(lambda x: x % 2 == 0, numbers)))
```

### Forma idiomática 3.1: Compreensão de lista legível
```python
# CORRETO: expressao direta, legivel e de melhor desempenho
evens_squared = [x * x for x in numbers if x % 2 == 0]
```

---

### Anti-padrão 3.2: Efeito colateral dentro de compreensão de lista
```python
# ERRADO: criacao de lista descartavel apenas para executar acao
[process_order(order) for order in pending_orders]
```

### Forma idiomática 3.2: Laço `for` padrão para efeitos colaterais
```python
# CORRETO: intencao clara de iteracao com efeito colateral
for order in pending_orders:
    process_order(order)
```

---

### Anti-padrão 3.3: Indexação manual repetitiva de tupla/sequência
```python
# ERRADO: acesso fragil por indices magicos
record = ("ORD-102", "Eduardo", 150.0, "BRL", "approved")
order_id = record[0]
client = record[1]
amount = record[2]
currency = record[3]
status = record[4]
```

### Forma idiomática 3.3: Desempacotamento paralelo idiomático
```python
# CORRETO: desempacotamento autodocumentado
order_id, client, amount, currency, status = record
```

---

### Anti-padrão 3.4: Multiplicação rasa de listas aninhadas
```python
# ERRADO: todas as 3 linhas apontam para a mesmica lista interna!
board = [[0] * 3] * 3
board[1][2] = 1  # Modifica a coluna 2 de TODAS as linhas!
```

### Forma idiomática 3.4: Compreensão gerando novas instâncias
```python
# CORRETO: cada linha e uma lista independente instanciada no loop
board = [[0] * 3 for _ in range(3)]
board[1][2] = 1
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `C4` (flake8-comprehensions): Identifica usos redundantes ou subótimos de geradores e coleções (`C400`, `C401`, `C408` etc.).
  - `PERF` (perflint): Detecta laços e conversões que podem ser simplificados.
  - `RUF005`: Recomenda o uso de desempacotamento em literais de lista/tupla no lugar de concatenações repetitivas.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia termos como `comprehension`, `sorted`, `sort(`, `deque`, `array(` e `memoryview` para o grupo `A` e spec `PY-02`.
- **Revisão por LLM:**
  - Avalia se compreensões foram usadas indevidamente para efeitos colaterais e se o aninhamento ultrapassa 2 níveis.

## 5. Exceções

- Chamadas a `map()` ou `filter()` são permitidas quando a função passada for uma função nomeada existente ou builtin de alto desempenho sem necessidade de `lambda` (ex: `list(map(str, ids))`).
