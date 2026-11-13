---
name: cicd-strictness
description: >
  Diretrizes mandatórias de fail-fast e integridade estrita para pipelines de CI/CD
  (GitHub Actions e Google Cloud Build). O pipeline deve falhar imediatamente a qualquer
  erro, sendo proibidas falhas silenciosas a menos que haja regra explícita de negócio documentada.
---

# Diretrizes de Integridade e Fail-Fast para CI/CD (GitHub Actions & Cloud Build)

> **Escopo de Aplicação:** Aplica-se exclusivamente ao criar, editar, analisar, refatorar ou depurar arquivos de automação e pipelines de CI/CD:
> - Workflows do GitHub Actions (`.github/workflows/*.yml`, `.github/workflows/*.yaml`)
> - Composite Actions (`action.yml`, `action.yaml`)
> - Configurações e passos do Google Cloud Build (`cloudbuild*.yaml`, `cloudbuild*.yml`, `cloudbuild/*.yaml`)

---

## 1. Fail-Fast Mandatório e Proibição de Falhas Silenciosas
- **Falha Imediata:** Todo pipeline de CI/CD deve falhar imediatamente e com código de saída não-zero (`exit code != 0`) sempre que um comando, step ou script falhar.
- **Proibição de Mascaramento de Erros:** É terminantemente proibido o uso de `|| true`, `|| :`, `|| echo ...` ou desativação indiscriminada de checagem (`set +e`) para silenciar comandos que retornam erro.
- **Fail-Fast em Scripts Shell:**
  - Em workflows do GitHub Actions (`run: |`), scripts bash multiline devem iniciar obrigatoriamente com `set -e` (e `set -o pipefail` quando houver pipes).
  - Em passos do Google Cloud Build executando shell (`entrypoint: 'bash'`, `args: ['-c', '...']`), o comando deve iniciar com `set -e` ou `set -eo pipefail`.
- **Proibição de `continue-on-error` Indiscriminado:** Não utilize `continue-on-error: true` para ignorar falhas de testes, linters, checagens de tipos, builds ou deploys.

---

## 2. Exceção Única: Regra Explícita de Negócio
- A supressão controlada, captura ou tratamento de erro (`|| ...`, verificações de existência condicional ou `continue-on-error: true`) só é permitida quando o comportamento representar uma **regra explícita de negócio** claramente justificada por design.
  - *Exemplo de Regra de Negócio Válida:* Uma verificação idempotente onde a ausência ou presença prévia de um recurso não constitui erro operacional, ou uma rotina compensatória de cleanup/rollback.
- **Documentação Obrigatória da Regra:** Todo e qualquer step, comando ou linha que trate ou tolere uma falha potencial DEVE conter um comentário explícito no formato:
  ```bash
  # Business Rule: <justificativa clara e contextual da regra de negócio que exige tolerar ou tratar este erro>
  ```
  Linhas com tratamento de erro sem a anotação `# Business Rule:` serão rejeitadas pelo sensor determinístico do harness.

---

## 3. Conformidade Estrita de Permissões
- Workflows reutilizáveis (`workflow_call`) não devem declarar `permissions` superiores às concedidas pelos workflows chamadores (`ci.yml` dos spokes).
- Pacotes que publicam release no GitHub (`gh release create`) exigem `contents: write` explicitamente concedido no chamador.

---

## 4. Validação Prévia Sintática
- Todo workflow YAML ou configuração de Cloud Build deve ser validado sintaticamente (`yaml.safe_load`) antes de ser submetido via commit ou PR.
