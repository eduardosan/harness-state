---
name: tdd-workflow
description: >
  Regras obrigatórias de Test-Driven Development (TDD), estrutura de diretórios de testes e
  documentação de regras de negócio (`Business Rule:`).
---

# Test-Driven Development (TDD) & Qualidade

1. **Ciclo Red-Green-Refactor Obrigatório:**
   - Ao implementar uma spec ou corrigir um bug, escreva primeiro o teste automatizado que reproduz o cenário ou a falha antes de alterar o código de produção.
2. **Organização Estrita de Diretórios:**
   - Testes devem residir exclusivamente em `tests/unit/` ou `tests/integration/`.
   - É terminantemente proibido criar arquivos de teste soltos na raiz do projeto.
3. **Docstrings com Regra de Negócio (`Business Rule:`):**
   - Toda função de teste deve possuir uma docstring iniciando com o prefixo `Business Rule:` explicando explicitamente qual critério de aceitação ou regra de domínio está sendo verificado.
4. **Verificação em Loop Fechado (`just verify`):**
   - Execute `just verify` antes de considerar qualquer tarefa concluída.
