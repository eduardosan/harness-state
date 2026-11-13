# Spec: Diretrizes Globais de Engenharia Python

## Objetivo
Este documento define as regras absolutas de arquitetura, estilo e governança para todo e qualquer código Python escrito, refatorado ou depurado nestes repositórios. O não cumprimento destas regras resultará em falha nos *Sensor Gates* (CI/CD).

## 1. Organização e Estrutura de Código
- **Sem Funções Aninhadas:** NUNCA defina uma função dentro de outra função. A única exceção permitida é o `wrapper` interno de um decorador simples decorado com `@functools.wraps`. Decoradores parametrizados DEVEM ser implementados como classes com `__call__` (ou utilizar `functools.partial`). Qualquer outra função aninhada é rejeitada pelo sensor AST (`PYF001`).
- **Sem Try-Excepts Aninhados:** Nunca aninhe blocos `try...except`. Deve existir apenas um bloco `try` por escopo lógico, com as exceções tratadas em uma cadeia plana de cláusulas `except`.

## 2. Padrões de Estilo e Documentação
- **Conformidade PEP 8:** Todo o código Python deve aderir rigorosamente ao guia de estilo PEP 8.
- **Docstrings (Google Style):** Todas as classes, módulos e funções DEVEM ser documentados utilizando o formato Google Python Style Guide.
- **Sem Underscores Iniciais (Não-Membros):** O uso de `_` (underscore) no início do nome de variáveis e funções é estritamente proibido. Exceção feita APENAS para métodos e atributos privados dentro de classes. Variáveis de módulo e funções isoladas nunca devem usar o prefixo `_`.

## 3. Gestão de Imports
- **Sem Try-Except em Imports:** É proibido envolver imports em blocos `try...except`. Módulos devem ser importados estaticamente. Caso um import opcional/condicional seja estritamente necessário, utilize o padrão `importlib.util.find_spec`.
- **Ordenação (isort):** Todos os imports devem estar rigorosamente organizados e formatados de acordo com a ferramenta `isort`.

## 4. Testes e TDD (Test-Driven Development)
- **Localização Estrita de Testes:** Em nenhuma hipótese crie arquivos aleatórios de testes (como `test_adk.py`, `test_crm.py`) na raiz do projeto. Os testes devem SEMPRE ser colocados no diretório `tests/` e seguir a arquitetura do projeto.
- **Docstrings Orientadas a Negócio:** Os docstrings das funções de teste devem documentar explicitamente a regra de negócio sendo testada, obrigatoriamente utilizando o prefixo `Business Rule:` antes de descrever o cenário.
- **TDD em Correção de Bugs:** Ao resolver um erro (bug), o primeiro passo OBRIGATÓRIO é criar um teste no diretório `tests/` que reproduza a falha. Somente após isso, o código deve ser corrigido para fazer o teste passar.

## 5. Regras Canônicas de Python Fluente (SPEC-PY-00 a SPEC-PY-13)
- **Sem Herança de Tipos Embutidos:** Nunca herde diretamente de `dict`, `list` ou `set`. Utilize `collections.UserDict`, `collections.UserList` ou composição (`PYF002`).
- **Sobrecarga de Operadores Segura:** Operadores que não suportam o operando recebido DEVEM retornar `NotImplemented`, NUNCA levantar `TypeError` (`PYF003`).
- **Modelo de Dados & Registros:** Implemente `__repr__` em classes de domínio. Prefira `@dataclass(slots=True)` ou `NamedTuple` sobre dicionários anônimos sem esquema (`PY-01`, `PY-05`).
- **Tipagem Estática Estrita:** Todo código deve ser aprovado pelo `pyright` em modo strict (`typeCheckingMode = "strict"`). O uso de `Any` sem justificativa formal em comentário é proibido (`PY-08`).
- **Referências e Mutabilidade:** É estritamente proibido o uso de argumentos padrão mutáveis (`def fn(x=[])`). Utilize `None` (`PY-06`).
