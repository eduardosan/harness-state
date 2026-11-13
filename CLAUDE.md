<!-- SUPERPOWERS-HARNESS:START -->
# Superpowers & Federated SDD Workflow

Este repositório é gerenciado pelo **agentic-flywheel** e utiliza o **Superpowers**
como metodologia de engenharia e execução autônoma de agentes de IA.

## Regras de Execução para Agentes de IA:
1. **Invocação Obrigatória de Skills:** Ao iniciar qualquer tarefa, consulte
   `.claude/skills/using-superpowers/SKILL.md`. Invoque as skills pertinentes antes
   de agir ou responder.
2. **Ciclo de Desenvolvimento Federado:**
   - **Brainstorming:** Ao conceber novas funcionalidades, use
     `superpowers:brainstorming` estruturando a spec mestre em
     `<project>-spec-hub/specs/SPEC-XXX.md`.
   - **Planejamento & Fan-out:** Use `harness spec plan specs/SPEC-XXX.md` para
     decompor a spec mestre e gerar sub-specs cirúrgicas nos repositórios afetados
     (`<spoke>/specs/<spec_id>.md`).
   - **TDD:** Implemente sob TDD estrito com prefixo `Business Rule:` nos testes
     unitários (`tests/unit/`).
   - **Verificação Contínua:** Execute `just verify` antes de submeter PRs. O feedback
     prescritivo é gerado por `.harness/sensors/format_feedback.sh`.
   - **Sync-Back:** Sincronize qualquer ajuste na sub-spec local de volta ao hub via
     `harness spec sync-hub`.
3. **Análise de Bugs (RCA Mandatória):** Ao diagnosticar qualquer falha, erro de
   pipeline ou teste vermelho, **antes de qualquer alteração de código**, leia e
   aplique `specs/prompts/rca_guidelines.md` (quando presente no repositório):
   - **Proibição de Mascaramento:** é terminantemente proibido usar
     `try...except`, `except: pass`, `|| true` ou mocks artificiais apenas para
     fazer a pipeline passar — a exceção indica um desvio real a diagnosticar.
   - **Triagem de Esporadicidade:** verifique se a falha é transiente ou
     estrutural/repetível; RCA é obrigatória para falhas repetíveis.
   - **Diagrama de Ishikawa:** documente os eixos Método, Máquina/Ambiente,
     Mão de Obra/Agente, Material/Dependências, Medição/Testes e Meio Ambiente.
   - **5 Porquês:** rejeite correções que apenas resolvam o sintoma; a correção
     deve atuar na causa raiz estrutural.
4. **Local da Spec (SSOT):** Onde o fluxo `superpowers:brainstorming` indicaria
   gravar o design doc em `docs/superpowers/specs/`, grave no SSOT federado:
   `<project>-spec-hub/specs/SPEC-XXX.md` (spec mestre no hub) ou
   `<spoke>/specs/<spec_id>.md` (sub-spec no spoke), reutilizando o frontmatter
   de `specs/SPEC-TEMPLATE.md`. Numere sequencialmente no formato
   `SPEC-XXX-<slug>.md` (zero-padded, tomando o próximo número disponível) e
   mantenha o `spec_id` do frontmatter igual ao identificador `SPEC-XXX`.
5. **Infraestrutura Gerenciada (Acesso Remoto Restrito):** É TERMINANTEMENTE
   PROIBIDO conectar via SSH (incluindo bastion/jump), executar comandos de
   virtualização remota (`pct`/`qm`/`pvesh`), ou acessar remotamente
   servidores de virtualização e containers LXC gerenciados pelo ecossistema —
   os nomes de host, IPs e identificadores dessas máquinas vivam APENAS em
   arquivos de configuração locais (configs de Ansible e segredos de ambiente),
   nunca nas diretrizes — sem AUTORIZAÇÃO EXPLÍCITA DO OPERADOR, concedida
   manualmente por ele na conversa (autorização pontual, não reutilizável).
   Medições de capacidade/logs/processos nessas máquinas devem ser solicitadas
   ao operador, que executará os comandos manualmente e encaminhará a saída
   ao agente.
<!-- SUPERPOWERS-HARNESS:END -->
