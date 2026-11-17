# Documentação de Arquitetura do `harness-state`

Esta pasta centraliza os documentos normativos de arquitetura e engenharia do ecossistema de desenvolvimento orientado por especificações (Spec-Driven Development — SDD).

---

## Índice de Documentos

| Documento | Foco Arquitetural |
|---|---|
| [`federated-sdd-platform.md`](./federated-sdd-platform.md) | **Plataforma de Harness SDD Federada**: Visão geral de produtos, business capabilities, topologia hub-and-spoke, decomposição cirúrgica de specs (fan-out) e simetria canônica local/remota. |
| [`bug-lifecycle-sdd-flow.md`](./bug-lifecycle-sdd-flow.md) | **Ciclo de Resolução de Bugs Guiado por SDD**: Fluxo bottom-up com leitura de logs via WIF, curadoria de evidências na Issue (SSOT), reprodução Fail-First (TDD Red), análise de causa raiz (RCA) e ondas topológicas. |
| [`code-evaluation-flow.md`](./code-evaluation-flow.md) | **Staged Code Evaluation & Cross-Repo Gate**: Pipeline canônico de avaliação de código, desacoplamento em sensores AST determinísticos e avaliação funcional por LLM-as-a-Judge (`judge.py`). |

---

## Documentos Relacionados

- [Referência da CLI `harness`](../cli.md)
- [Fluxo de State Tracking](../flow.md)
- [Diretrizes de Contribuição e Estilo](../../CONTRIBUTING.md)
