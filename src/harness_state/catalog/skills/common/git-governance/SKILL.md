---
name: git-governance
description: >
  Governança de branches Git, proteção da branch `main`, proibição de tags e abertura de Pull Requests via GitHub CLI (`gh`).
---

# Governança Git e Pull Requests

1. **Proteção Absoluta da Branch `main`:**
   - É terminantemente proibido commitar, fazer merge, rebase ou push diretamente na branch `main`.
   - Toda modificação deve ocorrer em uma branch de trabalho (`feat/...`, `fix/...`, `chore/...`, `docs/...`).
2. **Proibição de Criação de Tags:**
   - Agentes nunca devem executar `git tag` ou `git push --tags`.
3. **Abertura de Pull Request (`gh pr create`):**
   - Após validar com `just verify`, envie a branch e abra o Pull Request referenciando o identificador `SPEC-XXX` (ou deixe o `harness spec run` automatizar o push e abertura do PR).
