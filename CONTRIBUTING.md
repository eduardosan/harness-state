# Contribuindo com o harness-state

O `harness-state` é um projeto de código aberto distribuído sob a licença [GNU Affero General Public License v3 (AGPL-3.0)](./LICENSE).

Agradecemos o interesse em contribuir! Para garantir consistência arquitetural, rastreabilidade e segurança, todas as contribuições devem seguir as diretrizes abaixo.

---

## 1. Diretrizes de Código Python

- **PEP 8**: Todo código deve aderir rigorosamente ao guia de estilo PEP 8.
- **Google Style Docstrings**: Todas as classes, funções e módulos devem ser documentados com docstrings no formato Google Python Style Guide.
- **Estruturas Planas (Sem Funções Aninhadas)**: Funções nunca devem ser definidas dentro de outras funções (exceto decoradores estritos).
- **Tratamento de Exceções Plano**: Não utilize blocos `try...except` aninhados. Utilize exceções encadeadas e capture apenas exceções específicas.
- **Convenção de Nomes**: É proibido o uso de `_` (underscore) prefixado para funções soltas e variáveis de módulo. Underscore no início é restrito a métodos e atributos privados dentro de classes.
- **Ordenação de Imports**: Formatação e ordenação com `isort` (perfil Black).

---

## 2. Test-Driven Development (TDD) e Regras de Negócio

- **TDD Primeiro**: Antes de implementar novas funcionalidades ou correções de bugs, crie testes herméticos que reproduzam os cenários.
- **Docstrings de Regras de Negócio**: Toda função de teste deve iniciar sua docstring com o prefixo `Business Rule:` descrevendo explicitamente a regra validada.
- **Localização dos Testes**: Testes devem residir estritamente no diretório `tests/` (`tests/unit/` ou `tests/evals/`).

---

## 3. Segurança e Mascaramento de Dados Sensíveis (§7 SPEC-009)

Todo código e documentação versionados neste repositório são públicos. É terminantemente proibido commitar:
- Endereços IP reais de infraestrutura de servidores (utilize `{{SERVER_IP}}` ou `<SERVER_IP>`).
- Hostnames internos privados (utilize `{{INTERNAL_HOST}}` ou `<INTERNAL_HOST>`).
- Tokens ou segredos de API (utilize `{{GITHUB_TOKEN}}`, `{{OPENAI_API_KEY}}`).
- Portas não-padrão de infraestrutura (utilize `{{PORT}}` ou `<PORT>`).

Execute a auditoria de sanitização antes de submeter alterações:
```bash
uv run harness audit --mask-sensitive-data
```

---

## 4. Validação e Qualidade Local

O repositório possui receitas automatizadas no `justfile`:

```bash
# Executa pyright (0 erros em modo strict), ruff, isort e a suíte completa de testes
just verify
```

Nenhum Pull Request será aprovado se houver erros no Pyright ou no linter.

---

## 5. Fluxo de Git e Pull Requests

1. Crie uma branch a partir de `main` (`feat/...`, `fix/...`, `chore/...`).
2. Faça commits atômicos utilizando o padrão Conventional Commits.
3. Certifique-se de que `just verify` passe localmente.
4. Abra o Pull Request detalhando as alterações e aguarde a aprovação da esteira de CI.
