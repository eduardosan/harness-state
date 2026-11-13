---
name: go-idioms
description: >
  Regras de engenharia, formatação, tratamento de erros e testes para módulos em Go.
---

# Go Engineering Rules

1. **Estilo e Formatação:**
   - Código formatado com `gofmt` / `goimports` e validado via `go vet ./...` e `golangci-lint`.
2. **Tratamento Explícito de Erros:**
   - Nunca ignore erros retornados. Envolva erros com contexto usando `fmt.Errorf("...: %w", err)`.
3. **Testes e Concorrência:**
   - Testes de unidade (`*_test.go`) utilizando table-driven tests e `go test -race ./...`.
