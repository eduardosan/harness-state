# harness-state

Cliente oficial de State Tracking para a Plataforma de Harness SDD Federada (`eduardosan`).

Permite sincronizar o progresso de especificações (`SPEC-ID`), tarefas multi-repositório e bloqueios de trabalho concorrente diretamente no Redis central do Proxmox.

## Instalação

```bash
uv tool install git+https://github.com/eduardosan/harness-state.git
```

## Conexão ao Redis

Como o Redis opera na rede privada interna do Proxmox (`192.168.20.5:6379`), execute o túnel SSH na porta 8 antes de usar o CLI localmente:

```bash
ssh -p 8 -N -L 6379:192.168.20.5:6379 eduardo@pve2.for.mat.br
```

Por padrão, o `harness-state` conecta em `localhost:6379` sem senha.

## Comandos Principais

```bash
# Gravar ou atualizar uma nova spec e suas sub-tarefas
harness-state plan --spec specs/SPEC-042.md

# Visualizar o status consolidado de uma spec
harness-state status SPEC-042

# Retomar o trabalho no ambiente atual (faz checkout da branch pendente)
harness-state resume SPEC-042
```
