# harness-state

Cliente oficial de State Tracking para a Plataforma de Harness SDD Federada (`eduardosan`).

Permite sincronizar o progresso de especificações (`SPEC-ID`), tarefas multi-repositório e bloqueios de trabalho concorrente diretamente no Redis central do Proxmox.

## Instalação

```bash
uv tool install git+https://github.com/eduardosan/harness-state.git
```

## Conexão ao Redis

Como o Redis opera na rede privada interna do Proxmox (`192.168.20.5:6379`), você pode iniciar o túnel SSH em background diretamente pelo Makefile:

```bash
# Iniciar o túnel SSH em background
make tunnel

# Verificar se o túnel está ativo
make tunnel-check

# Encerrar o túnel
make tunnel-stop
```

O comando executado por baixo dos panos é:
```bash
ssh -p 8 -N -f -L 6379:192.168.20.5:6379 eduardo@pve2.for.mat.br
```

Por padrão, o `harness-state` conecta em `localhost:6379` sem senha.

## Instalação da CLI

Você pode instalar a CLI globalmente ou no ambiente virtual do projeto:

```bash
# Instalação global via uv tool (acessível no PATH de qualquer terminal)
make install-global

# Instalação local no venv (.venv)
make install-local
```

## Comandos Principais

```bash
# Gravar ou atualizar uma nova spec e suas sub-tarefas
harness-state plan --spec specs/SPEC-042.md

# Visualizar o status consolidado de uma spec
harness-state status SPEC-042

# Retomar o trabalho no ambiente atual (faz checkout da branch pendente)
harness-state resume SPEC-042
```
