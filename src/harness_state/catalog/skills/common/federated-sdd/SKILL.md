---
name: federated-sdd
description: >
  Orquestra o ciclo de vida de desenvolvimento federado guiado por especificações (Spec-Driven Development)
  integrado nativamente às metodologias do Superpowers (brainstorming, writing-plans, TDD, systematic-debugging).
  Use esta skill sempre que for conceber uma nova funcionalidade transversal, refinar requisitos com o usuário,
  executar o fan-out topológico ou sincronizar specs entre repositórios.
---

# Federated Spec-Driven Development (SDD) com Superpowers

Esta skill estabelece a ponte operacional e metodológica entre o **Superpowers** e a **Plataforma Federada SDD** (`agentic-flywheel`).

## 1. Princípios Inegociáveis

1. **Intenção Antes de Implementação:** Jamais altere código-fonte sem uma especificação formal aprovada (Gate 2).
2. **Spec Mestre no Spec-Hub (SSOT):** A especificação mestre transversal SEMPRE nasce e é mantida em `<project>-spec-hub/specs/SPEC-XXX.md`.
3. **Sub-specs Cirúrgicas nos Spokes:** Cada repositório spoke recebe exclusivamente a sua fatia de escopo, contratos H3 e critérios Gherkin em `<spoke>/specs/<spec_id>.md` via fan-out granular.
4. **Sincronização Reversa (Sync-Back):** Refinamentos ou alterações de regras realizados na sub-spec local do spoke devem ser reconciliados de volta na spec mestre do hub (`harness spec sync-hub`).
5. **Sensores Determinísticos:** Nenhuma branch é considerada pronta sem aprovação total no `just verify`.

## 2. Mapeamento do Fluxo Superpowers ➔ Federated SDD

### A. Fase de Concepção e Brainstorming (`superpowers:brainstorming`)
- Quando o usuário expressar uma nova necessidade ("Quero criar X", "Precisamos integrar Y"):
  - Invoque a metodologia de `brainstorming` para fazer perguntas socráticas e delimitar a intenção.
  - Ao convergir o design, **estruture o resultado diretamente como uma Spec Mestre** em `<project>-spec-hub/specs/SPEC-XXX.md`.
  - Garanta os metadados no frontmatter: `spec_id`, `product`, `capability`, `scope`, `target_repositories` (com ordenação de ondas `wave: 1` para SDKs/libs e `wave: 2` para agentes/consumidores).
  - Obtenha a aprovação formal do usuário antes de planejar a execução.
  - **Override de caminho (SSOT):** onde `brainstorming` indicaria gravar o
    design doc em `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`, grave
    a spec no SSOT federado: `<project>-spec-hub/specs/SPEC-XXX.md` (mestre) ou
    `<spoke>/specs/<spec_id>.md` (fan-out), com o frontmatter do
    `specs/SPEC-TEMPLATE.md`. Numere sequencialmente no formato
    `SPEC-XXX-<slug>.md` (zero-padded, tomando o próximo número disponível) e
    mantenha o `spec_id` do frontmatter igual ao identificador `SPEC-XXX`.

### B. Fase de Planejamento e Decomposição (`superpowers:writing-plans`)
- Em vez de gerar listas de tarefas informais soltas, execute o planejador topológico do flywheel:
  ```bash
  harness spec plan specs/SPEC-XXX.md
  ```
- O comando executa o **fan-out cirúrgico** (`harness spec fanout`), que distribui as sub-specs isoladas para a pasta `specs/` de cada spoke afetado no workspace.
- Registra as tarefas e dependências causais no State Tracker Redis.

### C. Fase de Execução e TDD (`superpowers:test-driven-development`)
- Entre no repositório da onda desbloqueada ativa (`wave: 1` primeiro).
- Crie a branch de trabalho a partir da sub-spec (`git checkout -b feat/spec-xxx-...`).
- Se precisar ajustar ou detalhar um contrato durante o desenvolvimento:
  ```bash
  harness spec sync-hub --repo-spec specs/SPEC-XXX.md
  ```
- Aplique TDD estrito sob as regras corporativas:
  - Escreva o teste primeiro em `tests/unit/`.
  - Documente o teste com o prefixo `Business Rule: <Regra de Negócio>`.
  - Implemente o código mínimo sem funções aninhadas, sem `try...except` aninhados e seguindo PEP 8 / `isort`.

### D. Fase de Diagnóstico e Verificação (`superpowers:systematic-debugging`)
- Valide o pacote com a esteira canônica de sensores determinísticos:
  ```bash
  just verify
  ```
- Se qualquer sensor falhar (`ruff`, `pyright`, `import-linter`, `pytest`), utilize o feedback prescritivo de `.harness/sensors/format_feedback.sh` para investigar a causa raiz sistematicamente antes de tentar correções pontuais.

### E. Fase de Entrega e Gate Transacional (`superpowers:requesting-code-review`)
- Com o `just verify` 100% verde, envie a branch e abra o Pull Request:
  ```bash
  git push -u origin feat/spec-xxx-...
  gh pr create --title "feat(<escopo>): implementar SPEC-XXX" --body "..."
  ```
- Notifique o State Tracker:
  ```bash
  harness update SPEC-XXX task-1 READY --pr <URL_DO_PR>
  ```
- O fechamento e merge transacional ocorrem após a validação de 100% no **Cross-Repo Harness Gate** (`flywheel gate`).
