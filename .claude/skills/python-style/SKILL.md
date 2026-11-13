---
name: python-style
description: >
  Regras obrigatórias de arquitetura, estilo (PEP 8), docstrings (Google Style), ordenação de imports (`isort`),
  gerenciamento de pacotes (`uv`) e restrições de AST em Python.
---

# Python Best Practices & Harness Rules

1. **Organização de Código (Verificado por AST Sensor):**
   - **No Nested Functions:** NUNCA defina uma função dentro de outra função (exceto wrapper simples de decorator com `@functools.wraps`).
   - **No Nested Try-Excepts:** NUNCA aninhe blocos `try...except`. Apenas um `try` por escopo lógico.
   - **No Try-Except em Imports:** Módulos devem ser importados estaticamente no topo. Para imports opcionais, utilize `importlib.util.find_spec`.
   - **No Leading Underscore Fora de Classes:** Proibido usar `_` no início de variáveis ou funções de nível de módulo. O prefixo `_` é exclusivo para métodos e atributos privados dentro de classes.
   - **Complexidade Cognitiva (`complexipy`):** Funções devem manter complexidade cognitiva `<= 15`. Aplique as sugestões determinísticas enviadas pelo sensor `complexipy` (`C001` guard clauses, `C002` continue guards, `C003` extração para funções auxiliares de módulo ou métodos de classe — NUNCA funções aninhadas).
2. **Estilo e Documentação:**
   - **PEP 8 & Google Style Docstrings:** Todo módulo, classe, método e função deve ter docstring no padrão Google Python Style Guide.
   - **Isort:** Todos os imports devem estar formatados com `isort` (`profile = "black"`).
   - **Tipagem Estrita:** Código verificado com `pyright`. Evite argumentos default mutáveis.
3. **Gerenciador de Pacotes:**
   - Utilize exclusivamente `uv` (`uv sync`, `uv add`, `uv run`). Nunca use `pip install` global.
