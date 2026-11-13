# SPEC-PY-04: Texto Unicode vs Bytes

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 4: "Texto Unicode versus sequências de bytes" (seções 4.2 a 4.10).

## 2. Regras normativas

1. **Princípio do "Sanduíche de Unicode" [Livro]:**
   - O código **MUST** aplicar rigorosamente o padrão do sanduíche de Unicode:
     - **Na entrada:** decodificar sequências de `bytes` para `str` no ponto mais cedo possível do fluxo de I/O (`bytes.decode('utf-8')`).
     - **No núcleo do processamento:** manipular exclusivamente objetos `str` nativos.
     - **Na saída:** codificar objetos `str` de volta para `bytes` no ponto mais tardio possível (`str.encode('utf-8')`).
2. **Declaração explícita obrigatória de codificação em arquivos de texto [Livro]:**
   - Todas as chamadas à função embutida `open()` ou métodos de leitura/escrita em modo texto (como `Path.read_text()` e `Path.write_text()`) **MUST** explicitar o parâmetro `encoding` (preferencialmente `encoding="utf-8"`).
   - O código **MUST NOT** depender da codificação padrão do sistema operacional (`locale.getpreferredencoding()`), garantindo total reprodutibilidade multiplataforma.
3. **Normalização de texto para comparação e busca [Livro]:**
   - Ao comparar, indexar ou buscar sequências de texto provenientes de fontes externas onde caracteres acentuados ou compatibilidades visuais importam, use `unicodedata.normalize("NFC", text)` (ou forma `"NFKC"`).
   - Não confie na igualdade estrita de strings (`==`) entre caracteres Unicode compostos e decompostos sem normalização prévia.
4. **Proibição de conversão implícita ou ingênua de bytes para string [Política]:**
   - É proibido invocar `str(bytes_obj)` sem decodificação explícita (`.decode(...)`), pois isso gera representações textuais indesejadas do literal de bytes (ex: `"b'dados'"`).
   - O uso de tratadores de erro como `errors="ignore"` ou `errors="replace"` **MUST NOT** ser feito às cegas; caso utilizado, deve conter um comentário justificando a estratégia de perda de dados.
5. **Ordenação correta de texto humano [Livro]:**
   - Para ordenação orientada a usuários finais com caracteres diacríticos e regras linguísticas locais, use ordenação baseada em módulo de colação (como `pyuca` ou `locale.strxfrm`), em vez da ordenação de pontos de código bruta de `sorted()`.

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Abertura de arquivo de texto sem codificação explícita
```python
# ERRADO: suscetivel a variacoes de plataforma (Windows cp1252 vs Linux UTF-8)
with open("data/report.txt", "r") as f:
    content = f.read()

text = Path("data/output.txt").read_text()
```

### Forma idiomática 3.1: Codificação explícita `utf-8` sempre declarada
```python
# CORRETO: comportamento deterministico e imune ao ambiente
with open("data/report.txt", "r", encoding="utf-8") as f:
    content = f.read()

text = Path("data/output.txt").read_text(encoding="utf-8")
```

---

### Anti-padrão 3.2: Comparação de strings Unicode sem normalização
```python
# ERRADO: 'café' com 'é' unico (NFC) falha na igualdade contra 'cafe\u0301' (NFD)
def has_matching_tag(tag: str, user_tag: str) -> bool:
    return tag == user_tag
```

### Forma idiomática 3.2: Comparação canônica com `unicodedata.normalize`
```python
# CORRETO: normalizacao garante equivalencia semantica
import unicodedata

def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFC", text)

def has_matching_tag(tag: str, user_tag: str) -> bool:
    return normalize_text(tag) == normalize_text(user_tag)
```

---

### Anti-padrão 3.3: Mistura descontrolada de bytes e texto (quebra do sanduíche)
```python
# ERRADO: converte bytes para representacao literal 'b"..."' e espalha bytes no dominio
def process_payload(raw_payload: bytes) -> str:
    preview = str(raw_payload)[:10]  # Vira "b'..." com prefixo b!
    return preview
```

### Forma idiomática 3.3: Sanduíche de Unicode com decodificação no limite
```python
# CORRETO: decodifica no limite do sistema e opera sobre texto puro
def process_payload(raw_payload: bytes) -> str:
    text = raw_payload.decode("utf-8")
    return text[:10]
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `PLW1514`: Identifica aberturas de arquivo com `open()` sem a especificação do argumento `encoding`.
- **Pyright Strict:**
  - O verificador de tipos em modo estrito impede a passagem inadvertida de `bytes` para funções que requerem `str` e vice-versa.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia referências a `encode`, `decode`, `unicodedata`, `encoding=` e `bytes` para o grupo `D` e spec `PY-04`.

## 5. Exceções

- Manipulação de arquivos binários nativos (`open(..., "rb")` ou `"wb"`), imagens, buffers criptográficos ou sockets de baixo nível operam legitimamente com `bytes` e não utilizam parâmetro de `encoding`.
