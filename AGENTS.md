# Guia para Agentes Autônomos (AGENTS.md)

Este documento estabelece as diretrizes obrigatórias e os padrões de operação para agentes de IA que atuam no repositório `harness-state`.

---

## 1. Visão Geral do Projeto

O **`harness-state`** é o cliente e CLI oficial de State Tracking para a plataforma de Spec-Driven Development (SDD) federada (`eduardosan`).

Sua função é gerenciar o ciclo de vida e a sincronização do estado de especificações globais (`SpecRun`), suas sub-tarefas distribuídas entre múltiplos repositórios (`SubTask`) e os estados de execução (`TaskState`) persistidos no barramento central Redis (hospedado no Proxmox).

---

## 2. Regras Inegociáveis de Arquitetura e Código Python

Todas as alterações em código Python devem seguir rigorosamente as regras abaixo:

### 2.1. Organização e Sintaxe
- **Proibido Funções Aninhadas (`No Nested Functions`)**: NUNCA declare uma função dentro de outra função (exceto para decorators estritos). Use funções no nível do módulo, métodos de classes ou laços de repetição.
- **Proibido Try-Except Aninhado (`No Nested Try-Excepts`)**: Nunca aninhe blocos `try...except`. Utilize apenas um bloco `try` por escopo lógico, tratando exceções em cadeias lineares de cláusulas `except`.
- **Proibido Try-Except em Imports (`No Try-Except on Imports`)**: Imports devem ser estáticos e declarados nas dependências. Caso um import condicional seja estritamente necessário, utilize `importlib.util.find_spec`.
- **Proibido Underscore Inicial Fora de Classes (`No Leading Underscores`)**: Variáveis de módulo e funções soltas NUNCA devem começar com `_`. O prefixo `_` é reservado exclusivamente para métodos e atributos privados no interior de classes.
- **Isort Obrigatório**: Todos os imports devem seguir a ordenação e formatação oficial do `isort`.
- **Sintaxe Moderna Python 3.13+**: Utilize anotações modernas PEP 585 e PEP 604 (`int | None` em vez de `Optional[int]`, `dict[str, Any]` em vez de `typing.Dict`, e `datetime.now(UTC)` da biblioteca padrão).

### 2.2. Estilo e Documentação
- **PEP 8 Estrito**: O código deve passar em todas as checagens de linter sem avisos.
- **Google Style Docstrings**: Todas as classes, módulos, métodos e funções devem conter docstrings completas no formato Google, documentando parâmetros (`Args:`), retornos (`Returns:`) e exceções (`Raises:`).

### 2.3. Testes e TDD
- **Testes Sempre em `tests/` (`No Scratch Tests in Root`)**: Jamais crie arquivos de teste soltos na raiz (ex: `test_foo.py`). Toda suíte deve residir em `tests/`.
- **TDD para Resolução de Bugs**: Ao corrigir qualquer bug, primeiro crie um teste que reproduza o erro e em seguida implemente a solução até o teste passar.
- **Docstrings de Teste com Regra de Negócio**: Toda função de teste deve iniciar sua docstring com o prefixo `Business Rule:` documentando a regra em validação. Exemplo:
  ```python
  def test_spec_initialization_status() -> None:
      """Business Rule: Uma nova spec deve iniciar com status IN_PROGRESS e tarefas vazias."""
      ...
  ```

---

## 3. Diretrizes de Git e Proteção de Branch

- **Proteção Total da Branch `main` (`Protect Main Branch`)**:
  - É **TERMINANTEMENTE PROIBIDO** commitar, fazer merge, rebase ou push diretamente na branch `main`.
  - Toda e qualquer alteração deve ser realizada exclusivamente em uma nova branch de trabalho (`feature/...`, `fix/...`, `chore/...`, `docs/...`).
- **Proibição de Criação de Tags (`No Tag Creation`)**:
  - É **TERMINANTEMENTE PROIBIDO** criar ou enviar tags git (`git tag`, `git push --tags`), pois tags disparam pipelines de release contínuo em produção.
- **Operações Permitidas**:
  - Criar branches: `git checkout -b <tipo>/<descricao>`
  - Fazer commits incrementais e semânticos: `git commit -m "<tipo>(<escopo>): <descricao>"`
  - Enviar branch remota: `git push -u origin <branch>`
  - Criar Pull Request via GitHub CLI:
    ```bash
    gh pr create --title "<tipo>(<escopo>): <descricao>" --body "<resumo estruturado do que foi implementado e testado>"
    ```

---

## 4. Ambiente de Desenvolvimento e Comandos

O projeto utiliza **`uv`** como gerenciador padrão de ambiente virtual e dependências.

### 4.1. Instalação e Sincronização
```bash
# Sincroniza o ambiente virtual local com todas as dependências (dev inclusas)
uv sync
```

### 4.2. Qualidade e Testes
```bash
# Executar suíte de testes unitários
uv run pytest

# Executar checagem de tipos estáticos
uv run pyright

# Executar linter de código
uv run ruff check .

# Executar verificação de ordenação de imports
uv run isort --check-only .

# Formatação e autocorreção automática
uv run ruff check --fix .
uv run isort .
```

### 4.3. Túnel SSH para o Redis Central (Proxmox)
Para testes ou comandos que dependam de comunicação com o Redis central (`192.168.20.5:6379`), utilize as metas do `Makefile`:
```bash
# Iniciar o túnel SSH em background
make tunnel

# Verificar se o túnel está ativo
make tunnel-check

# Encerrar o túnel SSH
make tunnel-stop
```

Variáveis de ambiente suportadas pelo cliente:
- `HARNESS_REDIS_HOST`: Host do Redis (padrão: `127.0.0.1` via túnel SSH).
- `HARNESS_REDIS_PORT`: Porta do Redis (padrão: `6379`).
- `HARNESS_REDIS_DB`: Índice do banco Redis (padrão: `0`).
- `HARNESS_REDIS_PASSWORD`: Senha de autenticação do Redis (opcional).

---

## 5. Arquitetura e Padrões Pythônicos ("Python Fluente")

Ao estender o pacote `harness_state`, preserve e aplique os princípios de design idiomático:

1. **Modelo de Dados Coeso**: Modelos que encapsulam dados relacionais (como `SpecRun` contendo tarefas) devem expor métodos especiais (`__len__`, `__getitem__`, `__contains__`, `__iter__`) e propriedades computadas (`is_complete`, `summary`), centralizando a lógica de domínio no próprio modelo em vez de dispersá-la em clientes externos.
2. **Gerenciamento de Recursos Assíncronos**: Clientes que mantêm conexões (`StateStore`) devem implementar o protocolo de context manager assíncrono (`async with StateStore() as store:`), garantindo o fechamento e descarte seguro de conexões (`aclose()`).
3. **Desacoplamento via Protocolos (`typing.Protocol`)**: A camada de persistência deve ter sua interface descrita em protocolos (`StateStoreProtocol`), permitindo implementações alternativas (como `InMemoryStateStore`) para isolar testes da infraestrutura de rede.
4. **Comandos de CLI Desacoplados**: A CLI Click deve atuar apenas como ponte de entrada, delegando a execução lógica para funções ou serviços assíncronos independentes de primeira classe, sem recorrer a funções aninhadas.
