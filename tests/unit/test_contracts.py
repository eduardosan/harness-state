"""Testes unitários para o validador de contratos OpenAPI e cross-repo."""

from pathlib import Path

from harness_state.contracts import (
    cross_validate_spec_contracts,
    validate_openapi_spec,
)

SAMPLE_OPENAPI_SPEC = """
openapi: 3.1.0
info:
  title: CRM Health Check API
  version: 1.0.0
paths:
  /crm/health:
    get:
      summary: Retorna a saude do CRM
      responses:
        '200':
          description: Sucesso
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/HealthStatus'
components:
  schemas:
    HealthStatus:
      type: object
      required:
        - status
        - version
      properties:
        status:
          type: string
        version:
          type: string
"""

INVALID_OPENAPI_SPEC = """
openapi: 3.1.0
info:
  title: Incompleto
paths:
  /bad:
    get:
      responses:
        '200':
          schema_invalido: 123
"""


def test_validate_valid_openapi_spec(tmp_path: Path) -> None:
    """Business Rule: Deve validar com sucesso especificações OpenAPI 3.1 válidas."""
    spec_file = tmp_path / "openapi.yaml"
    spec_file.write_text(SAMPLE_OPENAPI_SPEC, encoding="utf-8")

    result = validate_openapi_spec(spec_file)

    assert result.valid is True
    assert len(result.errors) == 0
    assert "/crm/health" in result.endpoints
    assert "HealthStatus" in result.schemas


def test_validate_invalid_openapi_spec(tmp_path: Path) -> None:
    """Business Rule: Deve detectar ausência de campos obrigatórios no OpenAPI."""
    spec_file = tmp_path / "bad.yaml"
    spec_file.write_text(INVALID_OPENAPI_SPEC, encoding="utf-8")

    result = validate_openapi_spec(spec_file)

    assert result.valid is False
    assert len(result.errors) > 0


def test_cross_validate_spec_with_no_contracts() -> None:
    """Business Rule: Se a spec não contiver contratos OpenAPI, validação é neutra."""
    markdown_spec = "# Spec sem contratos\n\nApenas texto descritivo."
    diffs = "+ print('hello')"

    result = cross_validate_spec_contracts(markdown_spec, diffs)

    assert result.valid is True
    assert len(result.errors) == 0
    assert result.endpoints == []


def test_cross_validate_spec_with_embedded_contract() -> None:
    """Business Rule: Deve extrair e validar blocos OpenAPI embutidos no Markdown."""
    markdown_spec = f"""# SPEC-001
## 3. Modelo de Dados e Contratos
```yaml
{SAMPLE_OPENAPI_SPEC}
```
"""
    diffs = """
diff --git a/client.py b/client.py
+class HealthStatus:
+    status: str
+    version: str
"""

    result = cross_validate_spec_contracts(markdown_spec, diffs)

    assert result.valid is True
    assert "/crm/health" in result.endpoints
    assert "HealthStatus" in result.schemas
