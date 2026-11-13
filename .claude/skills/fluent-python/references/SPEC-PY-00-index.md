# SPEC-PY-00: Índice e molde das specs Python Fluente

## Objetivo
Define o formato comum das specs `SPEC-PY-01` a `SPEC-PY-13`, derivadas do livro *Python Fluente, 2ª ed.* (https://pythonfluente.com/2/), e o agrupamento usado na revisão por LLM. Estas specs complementam, e não substituem, [python_guidelines.md](../prompts/python_guidelines.md).

## 1. Molde obrigatório de cada spec

Cada arquivo `SPEC-PY-NN-<tema>.md` DEVE conter, nesta ordem:

1. **Fonte:** capítulos e seções do livro que originam a spec.
2. **Regras normativas:** lista de regras com MUST / MUST NOT. Cada regra DEVE ter uma origem:
   - `[Livro]`: recomendação explícita do texto.
   - `[Política]`: decisão do harness, inspirada no livro mas não afirmada por ele.
3. **Anti-padrão → forma idiomática:** pelo menos um par de exemplos curtos por regra relevante. Servem de entrada para os evals.
4. **Enforcement:** sensor determinístico (`ruff`, `pyright`, AST) e/ou revisão por LLM, citando os códigos das regras.
5. **Exceções:** quando a regra não se aplica.

## 2. Catálogo e grupos de revisão

A revisão por LLM é feita em no máximo 5 chamadas agrupadas por tema (A a E). Cada chamada recebe apenas as specs do grupo cujos sinais apareceram no diff.

| Grupo | Spec | Tema | Capítulos do livro |
| :--- | :--- | :--- | :--- |
| A | PY-01 | Modelo de dados e objeto pythônico | 1, 11, 12 |
| A | PY-02 | Sequências e compreensões | 2, 17.7 |
| A | PY-03 | Dicionários e conjuntos | 3 |
| A | PY-05 | Fábricas de classes de dados | 5 |
| A | PY-06 | Referências, mutabilidade e memória | 6 |
| B | PY-07 | Funções, clausuras e decoradores | 7, 9, 10 |
| B | PY-08 | Dicas de tipo | 8, 15, 17.12, 21.12 |
| C | PY-09 | Protocolos, ABCs e herança | 13, 14 |
| C | PY-10 | Sobrecarga de operadores | 16 |
| D | PY-04 | Texto Unicode vs bytes | 4 |
| D | PY-11 | Iteradores, geradores, `with`, `match` e `else` | 17, 18 |
| D | PY-12 | Concorrência e programação assíncrona | 19, 20, 21 |
| E | PY-13 | Atributos dinâmicos, descritores e metaclasses | 22, 23, 24 |

## 3. Decisões globais

- **Versão mínima:** Python 3.12+.
- **Tipagem:** `pyright` em modo `strict` obrigatório em todos os repositórios-alvo. Repositórios existentes adotam um baseline de erros: só regressões bloqueiam, e o baseline só pode encolher.
- **Funções aninhadas:** a regra global continua proibindo funções dentro de funções, com uma única exceção: o `wrapper` interno de um decorador simples, que DEVE usar `functools.wraps`. Decorador parametrizado DEVE ser uma classe com `__call__` (ou usar `functools.partial`).

## 4. Status

| Spec | Status | Fase |
| :--- | :--- | :--- |
| PY-00 | Publicada | Fase 0 |
| PY-01 | Publicada | Fase 1 |
| PY-05 | Publicada | Fase 1 |
| PY-06 | Publicada | Fase 1 |
| PY-02 | Publicada | Fase 2 |
| PY-03 | Publicada | Fase 2 |
| PY-04 | Publicada | Fase 2 |
| PY-11 | Publicada | Fase 2 |
| PY-07 | Publicada | Fase 3 |
| PY-08 | Publicada | Fase 3 |
| PY-09 | Publicada | Fase 3 |
| PY-10 | Publicada | Fase 3 |
| PY-12 | Publicada | Fase 4 |
| PY-13 | Publicada | Fase 4 |
