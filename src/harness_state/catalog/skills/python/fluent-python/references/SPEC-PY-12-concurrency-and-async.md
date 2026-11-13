# SPEC-PY-12: Concorrência e Programação Assíncrona

## 1. Fonte
*Python Fluente, 2ª ed.*:
- Capítulo 19: "Modelos de concorrência em Python" (seções 19.2 a 19.7).
- Capítulo 20: "Concorrência com executores" (seções 20.2 a 20.5: `concurrent.futures`).
- Capítulo 21: "Programação assíncrona" (seções 21.2 a 21.13: `asyncio`).

## 2. Regras normativas

1. **Seleção consciente do modelo pelo tipo de gargalo [Livro]:**
   - Antes de implementar concorrência, o desenvolvedor **MUST** diagnosticar o tipo de gargalo:
     - **CPU-bound (cálculos pesados, compressão, processamento de imagens):** use multiprocessamento via `concurrent.futures.ProcessPoolExecutor` ou bibliotecas com bindings em C/Rust para contornar o Global Interpreter Lock (GIL).
     - **I/O-bound com chamadas síncronas bloqueantes (bancos relacionais legados, sistemas de arquivos locais):** use `concurrent.futures.ThreadPoolExecutor`.
     - **I/O-bound em alta escala (centenas/milhares de requisições de rede concorrentes):** use `asyncio` com sockets e bibliotecas cooperativas não-bloqueantes.
2. **Proibição absoluta de I/O bloqueante no event loop do `asyncio` [Livro]:**
   - Funções assíncronas `async def` executando no event loop do `asyncio` **MUST NOT** realizar chamadas bloqueantes de sistema (como `time.sleep()`, `open()`, `requests.get()` ou bibliotecas síncronas).
   - Use os equivalentes assíncronos (`asyncio.sleep()`, clientes HTTP assíncronos) ou delegue a execução de código síncrono para threads em segundo plano com `asyncio.to_thread()` ou `loop.run_in_executor()`.
3. **Concorrência estruturada com `asyncio.TaskGroup` [Livro]:**
   - No Python 3.11+, o disparo e sincronização de múltiplas tarefas assíncronas concorrentes **MUST** utilizar o gerenciador de contexto `asyncio.TaskGroup` em vez de `asyncio.gather()` legado.
   - O `TaskGroup` garante o princípio da concorrência estruturada: se qualquer subtarefa falhar, todas as outras tarefas irmãs são canceladas automaticamente e exceções são agregadas em um `ExceptionGroup`.
4. **Gerenciamento assíncrono de recursos com `async with` e iteração com `async for` [Livro]:**
   - Todo recurso que abre conexões, pools ou sessões de rede assíncronas **MUST** ser adquirido e fechado dentro de blocos `async with`.
   - Geradores assíncronos que produzem fluxos de eventos **MUST** ser consumidos através de laços `async for`.
5. **Ponto de entrada único e proibição de `asyncio.run()` aninhado [Política]:**
   - A função `asyncio.run()` **MUST** ser chamada exclusivamente no ponto de entrada principal do programa (função `main()` ou CLI).
   - É estritamente proibido invocar `asyncio.run()` ou manipular loops diretamente dentro de funções de biblioteca ou dentro de outras corrotinas já em execução.
6. **Timeouts explícitos em todas as operações de rede [Política]:**
   - Toda operação de rede ou I/O assíncrono **MUST** definir timeouts explícitos (seja através dos parâmetros das bibliotecas clientes ou envolvendo o bloco em `asyncio.timeout()`).

## 3. Anti-padrão → forma idiomática

### Anti-padrão 3.1: Chamada de I/O síncrono bloqueando o loop do asyncio
```python
# ERRADO: time.sleep e requests.get congelam todas as corrotinas do sistema
import asyncio
import time
import requests


async def fetch_status(url: str) -> int:
    time.sleep(1)  # Bloqueia a thread principal do event loop!
    response = requests.get(url)  # Chamada síncrona bloqueante
    return response.status_code
```

### Forma idiomática 3.1: Operações assíncronas puras ou delegação com `to_thread`
```python
# CORRETO: asyncio.sleep cooperativo e delegacao para thread se o cliente for sincrono
import asyncio
import requests


async def fetch_status(url: str) -> int:
    await asyncio.sleep(1)  # Nao bloqueia outras tarefas concorrentes
    # Se a biblioteca for síncrona, delega de forma segura:
    response = await asyncio.to_thread(requests.get, url, timeout=10.0)
    return response.status_code
```

---

### Anti-padrão 3.2: Uso de `asyncio.gather` sem cancelamento estruturado
```python
# ERRADO: se task_a falhar, task_b continua rodando em segundo plano (tarefa orfã)
import asyncio


async def fetch_all(urls: list[str]) -> list[str]:
    tasks = [fetch_page(u) for u in urls]
    results = await asyncio.gather(*tasks)
    return results
```

### Forma idiomática 3.2: Concorrência estruturada com `asyncio.TaskGroup`
```python
# CORRETO: TaskGroup cancela as demais tarefas em caso de falha de qualquer uma
import asyncio


async def fetch_all(urls: list[str]) -> list[str]:
    results: list[str] = []
    async with asyncio.TaskGroup() as tg:
        tasks = [tg.create_task(fetch_page(u)) for u in urls]

    return [t.result() for t in tasks]
```

---

### Anti-padrão 3.3: Operação de CPU intensa executada em Threads
```python
# ERRADO: Threads em Python competem pela GIL e nao aceleram tarefas de CPU
from concurrent.futures import ThreadPoolExecutor


def compute_hashes(data_chunks: list[bytes]) -> list[str]:
    with ThreadPoolExecutor() as executor:
        return list(executor.map(heavy_cpu_hash, data_chunks))
```

### Forma idiomática 3.3: ProcessPoolExecutor para paralelismo real de CPU
```python
# CORRETO: ProcessPoolExecutor cria processos isolados em nucleos distintos
from concurrent.futures import ProcessPoolExecutor


def compute_hashes(data_chunks: list[bytes]) -> list[str]:
    with ProcessPoolExecutor() as executor:
        return list(executor.map(heavy_cpu_hash, data_chunks))
```

## 4. Enforcement

- **Sensor Estático (Ruff):**
  - `ASYNC` (flake8-async): Detecta práticas perigosas em código assíncrono:
    - `ASYNC210`: Bloqueio síncrono de operações em funções `async`.
    - `ASYNC230`: Abertura de arquivos bloqueantes dentro de funções `async`.
    - `ASYNC251`: Chamadas a `time.sleep()` em funções `async` (sugere `asyncio.sleep`).
- **Testes de Concorrência:**
  - Validação de corrotinas através de `pytest-asyncio` com configuração de loop isolado.
- **Sensor AST & Roteador:**
  - `spec_router.py`: Roteia termos como `async def`, `await `, `TaskGroup`, `ProcessPoolExecutor`, `ThreadPoolExecutor` e `asyncio` para o grupo `D` e spec `PY-12`.

## 5. Exceções

- Scripts simples de manutenção em linha de comando que realizam tarefas sequenciais lineares podem utilizar laços síncronos convencionais sem necessidade de complexidade assíncrona.
