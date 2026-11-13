---
name: ts-react
description: >
  Regras de engenharia para módulos em TypeScript, Node.js, React e Vite.
---

# TypeScript & Frontend Engineering Rules

1. **Tipagem Estrita (`tsc --noEmit`):**
   - Proibido uso de `any` implícito. Defina interfaces explícitas para props, payloads e estados.
2. **Qualidade e Testes:**
   - Valide sempre com `npm run lint`, `npm run test` e `npm run build` através do `just verify`.
