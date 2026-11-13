# Spec: Diretrizes Globais de Elaboração e Governança de Especificações (SDD)

## Objetivo
Este documento define as regras absolutas de arquitetura, viabilidade técnica e governança para toda e qualquer especificação técnica (`SPEC-XXX`) criada, planejada, refinada ou aprovada no ecossistema federado. O não cumprimento destas regras resultará em impedimento ou reprovação no Gate de Especificações.

## 1. Viabilidade Técnica e Compatibilidade de SDKs (Mandatório)
- **Sem Alucinação de Paridade de Recursos:** É estritamente proibido assumir que APIs em tempo real (como Gemini Live API / Google ADK Live) possuem paridade de recursos ou interfaces idênticas a APIs síncronas ou REST (ex: Tool Calling arbitrário, upload de arquivos estruturados, schemas JSON estritos).
- **Seção Obrigatória de Viabilidade (3.1):** Qualquer especificação que proponha novos contratos ou utilize SDKs externos/APIs de tempo real DEVE conter a subseção `3.1. Viabilidade Técnica e Compatibilidade de SDKs / APIs Externas`.
- **Declaração Explícita de Limitações:** A spec deve listar:
  1. Versões mínimas de bibliotecas no `pyproject.toml` ou manifesto do módulo.
  2. Assinatura de métodos e modo de transporte (REST, gRPC, WebSocket bidirecional).
  3. Limitações de protocolo e restrições conhecidas do provedor (codecs, reconexão, contexto).
  4. Plano de Fallback Arquitetural caso a API externa não atenda aos requisitos em tempo de execução.

## 2. Protocolo de Spike (Onda 0)
- **Incerteza Tecnológica = Spike Primeiro:** Sempre que uma funcionalidade depender de biblioteca externa em estágio beta, experimental ou sem precedente validado no ecossistema, a spec DEVE iniciar por uma tarefa de Spike (`wave: 0`, `role: spike`).
- **Prova Executável de Conceito:** O Spike deve gerar um script mínimo ou teste de viabilidade em `tests/` comprovando que o SDK suporta a operação antes que as tarefas das ondas subsequentes comecem a codificar regras de negócio.

## 3. Governança de Prompts (SPEC-PROMPT-01)
- **Declaração de Prompts para Agentes de IA:** Se qualquer repositório alvo for um agente de IA (`role: ai-agent`) ou se a especificação alterar `prompts.py`, todos os prompts afetados DEVEM ser declarados no frontmatter YAML e documentados na Seção 3.5 em inglês estrito.
