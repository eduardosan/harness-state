# Diretrizes Normativas de Análise de Causa Raiz (RCA) e Proibição de Mascaramento

> **Status:** Normativo / Mandatório  
> **Escopo:** Todos os agentes de IA, suítes de testes, fixes e avaliações do ecossistema.

---

## 1. Regra Fundamental: Proibição de Mascaramento

- Os LLMs em geral tendem a tentar impedir que erros aconteçam em vez de resolvê-los. **Esse comportamento é inaceitável e estritamente proibido.**
- **Se uma exceção ou falha ocorreu, é porque existe um desvio de comportamento ou de ambiente que precisa ser diagnosticado e corrigido na raiz.**
- É **terminantemente proibido** adicionar blocos de `try...except`, supressões silenciosas (`except: pass`), `|| true`, `|| echo ""` ou mocks artificiais em testes apenas para contornar um erro ou fazer uma pipeline passar.
- Tratar a exceção como prioridade em vez da causa raiz é considerado **falha grave de conformidade arquitetural**.

---

## 2. As 3 Etapas Canônicas de Investigação

### Etapa 1: Triagem de Esporadicidade vs. Causa Raiz
- Antes de qualquer correção, o agente deve analisar se o erro é:
  - **Esporádico e transiente:** Não possui causa determinística e comprovadamente não tem chances de se repetir.
  - **Falha estrutural ou de ambiente:** Possui qualquer probabilidade de se repetir em qualquer etapa do ciclo de vida.
- **Diretriz:** Se o erro é repetível, a condução de **RCA É MANDATÓRIA**.

### Etapa 2: Construção Obrigatória do Diagrama de Ishikawa (Espinha de Peixe)
O agente deve documentar e analisar as categorias fundamentais:
- **Método:** Processo, esteira de CI/CD, contratos de chamada.
- **Máquina/Ambiente:** Host, sistema operacional, containers, runners, binários de sistema instalados (`gcloud`, `uv`, `git`, etc.), PATH e variáveis de ambiente.
- **Mão de Obra/Agente:** Decisões prévias do modelo de IA, prompts e suposições.
- **Material/Dependências:** Bibliotecas, pacotes de sistema, versões do runtime.
- **Medição/Testes:** Sensores do harness, asserções de testes e reprodução TDD.
- **Meio Ambiente:** Diferenças entre ambiente local e ambiente cloud/self-hosted.

### Etapa 3: Auto-Julgamento com os 5 Porquês (5 Whys)
Antes de commitar ou propor qualquer alteração, o agente deve responder aos 5 Porquês:
- **Por que 1:** Por que o erro/falha ocorreu imediatamente?
- **Por que 2:** Por que essa falha se manifestou dessa forma?
- **Por que 3:** Por que a condição ou dependência esperada não estava presente?
- **Por que 4:** Por que os processos ou a infraestrutura permitiram essa ausência?
- **Por que 5:** Por que a causa raiz fundamental não foi prevenida na origem?

**Critério de Avaliação:**
Correções que atuam apenas no primeiro nível (ex: capturar exceção, silenciar erro ou mockar dependências reais de sistema) são **REJEITADAS AUTOMATICAMENTE**. A correção deve atuar na causa raiz estrutural.
