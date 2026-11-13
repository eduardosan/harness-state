# SPEC-PY-11: Iteradores, Geradores, Context Managers e Controle de Fluxo

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 17: "Iteradores, geradores e clássicos" (seções 17.2 a 17.13).
- Capítulo 18: "com, como e blocos else" (seções 18.2 a 18.5).

## 2. Regras normativas

1. **Separação inequívoca entre Iterável e Iterador [Livro]:**
   - Um **iterável** implementa `__iter__()` retornando uma nova instância de iterador a cada chamada (permitindo múltiplas passagens).
   - Um **iterador** implementa `__next__()` e `__iter__()` retornando a si mesmo (exaurindo-se após uma passagem).
   - **MUST NOT** combinar a lógica de contêiner iterável e o estado de exaustão de iterador em um mesmo objeto (evite `Sentence` que implementa `__next__` sobre si mesma).
2. **Geradores e delegação com `yield from` [Livro]:**
   - Funções geradoras e expressões geradoras **MUST** ser preferidas para produzir sequências grandes, infinitas ou sob demanda, evitando a materialização desnecessária de listas completas em memória.
   - Use `yield from subgen` para encadear ou delegar iteração entre geradores, simplificando loops aninhados e preservando canais bidirecionais de comunicação de corrotinas/subgeradores.
3. **Aproveitamento das funções embutidas de redução e `itertools` [Livro]:**
   - Prefira reduções eficientes embutidas (`all()`, `any()`, `sum()`, `min()`, `max()`) e utilitários da biblioteca padrão (`itertools.islice`, `itertools.chain`, `itertools.groupby`) em vez de construir contadores ou laços imperativos manuais equivalentes.
4. **Gerenciamento de contexto obrigatório com `with` [Livro]:**
   - Todo recurso externo que aloque manipuladores de arquivos, conexões de banco de dados, locks ou sessões de rede **MUST** ser utilizado dentro de um bloco `with` (ou `async with`).
   - Para criar context managers personalizados utilitários, use o decorador `@contextlib.contextmanager` e estruture a inicialização e limpeza ao redor de um bloco `try...finally`.
5. **Semântica correta e consciente de blocos `else` [Livro]:**
   - Blocos `else` em laços `for` e `while` só devem ser usados quando a regra expressar claramente "executar somente se o loop concluiu sem interrupção por `break`".
   - Blocos `else` em cláusulas `try/except` **MUST** ser usados para colocar o código que só deve rodar se nenhuma exceção ocorreu, mantendo o bloco `try` com escopo mínimo.
6. **Casamento de padrões estruturais (`match/case`) com propósito [Livro]:**
   - O comando `match/case` **MUST** ser usado primariamente para desestruturação, validação de formatos e casamento por tipos de objetos/sequências.
   - **MUST NOT** usar `match/case` como mero substituto trivial de um `if/elif/else` que testa apenas uma condição booleana simples.
7. **Escopo mínimo em blocos de exceção [Política]:**
   - O bloco `try` **MUST** envolver unicamente a linha ou instrução sujeita à falha esperada. Blocos `try` aninhados continuam estritamente proibidos pelo harness.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Materialização desnecessária de coleções grandes em memória
```python
# ERRADO: carrega milhoes de linhas na memoria como lista completa
def load_valid_ids(filepath: str) -> list[int]:
    results = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            val = line.strip()
            if val.isdigit():
                results.append(int(val))
    return results
```

### Forma idiomática 3.1: Função geradora com consumo preguiçoso
```python
# CORRETO: produz elementos sob demanda sem sobrecarregar a memoria
from collections.abc import Iterator


def generate_valid_ids(filepath: str) -> Iterator[int]:
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            val = line.strip()
            if val.isdigit():
                yield int(val)
```

---

### Anti-padrão 3.2: Gerenciador de contexto manual prolixo via classe
```python
# ERRADO: implementacao burocratica de dunders para um recurso simples
class TemporaryDirectoryManager:
    def __enter__(self) -> str:
        self.path = create_temp_dir()
        return self.path

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        remove_dir(self.path)
```

### Forma idiomática 3.2: Gerenciador de contexto elegante com `@contextlib.contextmanager`
```python
# CORRETO: expressao concisa com gerador e bloco try-finally
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def temporary_directory() -> Iterator[str]:
    path = create_temp_dir()
    try:
        yield path
    finally:
        remove_dir(path)
```

---

### Anti-padrão 3.3: Inclusão excessiva de lógica protegida em bloco `try`
```python
# ERRADO: encobre excecoes de codigo que nao deveria estar protegido
def read_and_record(filepath: str, client_id: str) -> None:
    try:
        data = parse_file(filepath)
        validated = validate(data)
        record_database(client_id, validated)
    except FileNotFoundError:
        log_missing(filepath)
```

### Forma idiomática 3.3: Escopo cirúrgico com `else`
```python
# CORRETO: apenas o parse_file fica no try; o restante roda no else
def read_and_record(filepath: str, client_id: str) -> None:
    try:
        data = parse_file(filepath)
    except FileNotFoundError:
        log_missing(filepath)
    else:
        validated = validate(data)
        record_database(client_id, validated)
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `SIM115`: Exige o uso de gerenciador de contexto `with` ao abrir arquivos.
  - `SIM117`: Sugere combinar múltiplos blocos `with` contíguos em uma única cláusula.
  - `PERF102`: Identifica iterações em dicionários que podem ser simplificadas.
  - `B007`: Alerta sobre variáveis de loop não utilizadas.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia construções contendo `yield`, `yield from`, `__iter__`, `@contextmanager`, `match ` e `case ` para o grupo `D` e spec `PY-11`.
- **Revisão por LLM:**
  - Verifica ausência de loops infinitos em iteradores e validação de escopo mínimo em blocos `try`.

## 5. Exceções

- Para coleções pequenas que precisam ser indexadas repetidamente por posição ou acessadas por tamanho (`len()`), listas concretas retornadas diretamente continuam apropriadas.
