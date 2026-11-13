---
spec_id: SPEC-001
title: "Título da Funcionalidade do Módulo"
product:
  - paralax-platform
capability: customer-relationship-management
scope: platform
bounded_context: "CRM (Supporting Subdomain)"
origin_module: module-name
target_repositories:
  - repo: paralax-ia/module-name
    wave: 1
    role: service
prompts:
  - name: module-name/agent_instruction
    target_repo: paralax-ia/module-name
    file: module_name/prompts.py
    symbol: INSTRUCTION
    description: "Instrução de prompt do agente ou componente LLM"
status: DRAFT
---

# SPEC-001: Título da Funcionalidade do Módulo

> **Product:** `paralax-platform`  
> **Business Capability:** `customer-relationship-management`  
> **Scope:** Platform  
> **Bounded Context:** CRM (Supporting Subdomain)

## 1. Contexto e Motivação
Descreva o problema de negócio resolvido por este módulo.

## 2. Escopo e Repositórios Afetados
- [ ] [Onda 1] `paralax-ia/module-name`: Descrição da entrega neste módulo.

## 3. Contratos de Interface
Descreva classes, métodos ou endpoints OpenAPI 3.1 adicionados/alterados.

### 3.1. Viabilidade Técnica e Compatibilidade de SDKs / APIs Externas
- **Dependências Externas / SDKs:** Liste pacotes e versões mínimas exigidas (ex: `google-genai>=1.0.0`, `google-adk>=0.2.0`).
- **Protocolo e Modo de Execução:** REST síncrono, streaming assíncrono, WebSocket bidirecional (Live API), etc.
- **Limitações Conhecidas e Paridade de Recursos:**
  - [ ] A API/SDK suporta chamadas de ferramentas (Function Calling) no modo especificado?
  - [ ] Existem restrições de formato de dados, codecs de áudio ou payloads (ex: PCM 16kHz, limites de turnos)?
  - [ ] O ciclo de vida da sessão, reconexão e contexto conversacional são suportados nativamente?
- **Estratégia de Spike (Onda 0):** Se a tecnologia for experimental, emergente (ex: Gemini Live API) ou não comprovada no ecossistema, defina uma subtarefa com `wave: 0` e `role: spike` contendo teste executável antes da implementação definitiva.
- **Plano de Fallback Arquitetural:** Estratégia de contingência caso a API externa apresente incompatibilidades técnicas em produção (ex: fallback de Live streaming para requisições assíncronas turn-by-turn).

### 3.5. Governança de Prompts (SPEC-PROMPT-01)
- **Prompt:** `module-name/agent_instruction`
- **Repositório:** `paralax-ia/module-name`
- **Arquivo Local / Fallback:** `module_name/prompts.py` (constante `INSTRUCTION`)
- **Papel:** Instrução de sistema do agente
- **Idioma:** Estritamente em inglês

## 4. Critérios de Aceitação (Gherkin)
- **Cenário 1: Comportamento esperado**
  - **Dado** um estado inicial válido
  - **Quando** a operação for executada
  - **Então** o contrato deve responder conforme especificado.

## 5. Plano de Rollout e Compatibilidade
Estratégia de versionamento SemVer e publicação.
