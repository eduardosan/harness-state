---
name: harness-judge-verification
description: >
  Executa a autoavaliação normativa do agente local (Coder Self-Judge) e auditoria pré-release
  (LLM-as-a-Judge consolidado). Valida o diff contra as 3 regras normativas (integridade de gates,
  proibição de mascaramento de erros e preservação de contratos públicos) via `just judge-local`
  ou `harness judge --local` antes da abertura de Pull Requests.
---

# Harness Judge Verification & Double Validation

Esta skill estabelece o protocolo operacional da **Validação Dupla** do ecossistema SDD:
1. **Local Self-Judge (Spoke Local):** O agente Coder audita o próprio git diff contra as 3 regras normativas antes de submeter PRs.
2. **Server-Side Sovereign Judge (Hub/Release):** Auditoria consolidada pré-release executada em voto único de alta precisão.

## 1. As 3 Regras Normativas do Judge

Todo código gerado ou modificado deve satisfazer integralmente as seguintes regras:

### Regra 1: Integridade de Testes e Gates (`Gate Integrity & Test Preservation`)
- **Proibição de Asserts Enfraquecidos:** É terminantemente proibido introduzir asserções tautológicas ou artificiais, como `assert True`, `assert 1`, `assert not False`.
- **Proibição de Skips Injustificados:** É proibido marcar testes com `@pytest.mark.skip` ou equivalentes para evitar falhas de regressão.
- **Proibição de Mascaramento em Comandos:** Comandos de verificação jamais devem suprimir erros com `|| true`, `set +e` ou redirecionamentos maliciosos.

### Regra 2: Proibição de Mascaramento de Exceções (`No Error Masking`)
- **Zero Mascaramento Silencioso:** É estritamente proibido o uso de `except: pass`, `except Exception: pass` ou qualquer bloco que capture exceções sem tratamento explícito, log estruturado ou re-raise.
- **RCA Antes da Correção:** Exceções capturadas devem indicar desvios reais a serem diagnosticados na causa raiz estrutural.

### Regra 3: Preservação de Contratos Públicos (`Public Contract Preservation`)
- **Estabilidade de API:** É proibido alterar ou remover classes, métodos, assinaturas ou interfaces públicas consolidadas sem um ciclo explícito de depreciação e compatibilidade retroativa.

## 2. Execução no Spoke Local (`just judge-local`)

Antes de finalizar qualquer tarefa ou abrir um Pull Request, o agente DEVE executar a verificação local:

```bash
just judge-local
# ou alternativamente:
uv run harness judge --local
```

### Artefato de Evidência
A execução bem-sucedida emite o arquivo `.harness/verification-summary.json` contendo:
- `spec_id`: Identificador da especificação/tarefa ativa.
- `passed`: `true` se todas as regras normativas foram atendidas.
- `rules_checked`: Detalhamento do status de cada uma das 3 regras.
- `violations`: Lista de violações detectadas (se houver).

Se houver qualquer violação, a execução falha com código 1 e o agente deve corrigir a causa raiz antes de prosseguir.

## 3. Auditoria Pré-Release Server-Side (`--fast`)

No momento da geração de uma nova release ou tag, a esteira executa o LLM-as-a-Judge canônico:
```bash
uv run python -m harness_state.judge --fast \
  --spec docs/architecture/code-evaluation-flow.md \
  --diffs release_artifacts/release_diff.patch \
  --spec-id "TAG-vX.Y.Z" \
  --out-file release_artifacts/evaluation_report.json
```
- O modo `--fast` consolida a avaliação em voto único (< 1 min), mantendo a precisão e reduzindo drasticamente a latência de lançamento.
- A aprovação soberana (`status == APPROVED`, score >= 80) é condição indispensável para a publicação da tag.
