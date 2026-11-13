---
name: sdd-workflow
description: >
  Fluxo de Spec-Driven Development (SDD) Federado e Orquestrador Semi-Automatizado (`harness spec run`).
  Use esta skill sempre que for criar ou atualizar uma especificação na pasta `specs/` do módulo,
  planejar ondas de execução ou avançar a esteira local/remota.
---

# Spec-Driven Development (SDD) no Módulo

1. **Hospedagem da Spec no Módulo de Origem (`specs/SPEC-XXX.md`):**
   - Toda funcionalidade ou evolução de contrato deste módulo nasce e é mantida em `specs/SPEC-XXX-nome.md` na raiz deste pacote.
   - O repositório `<project>-spec-hub` guarda apenas a organização de Produtos (`products/*.yaml`), Business Capabilities (`capabilities/*/capability.yaml`) e o `manifest.yaml`.
2. **Frontmatter Obrigatório da Spec:**
   - Declare sempre `spec_id`, `title`, `product`, `capability`, `scope` (`platform` ou `product-specific`), `origin_module` e `target_repositories` (com `wave: 1` para SDKs/libs e `wave: 2` para aplicações/agentes).
3. **Orquestrador Semi-Automatizado (`harness spec run`):**
   - Nunca tente executar passos isolados de memória. Utilize o motor de esteira:
     - `harness init`: Baixa ou atualiza as skills da linguagem e o pipeline de verificação (`justfile` + `.harness/sensors/`).
     - `harness spec run specs/SPEC-XXX.md`: Executa a esteira guiada por estado (planejamento no Redis, preparação da branch da onda ativa, validação com `just verify`, abertura de PR, atualização de estado e sincronização com o `spec-hub`).
