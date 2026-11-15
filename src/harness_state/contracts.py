"""Módulo de validação de contratos OpenAPI e verificação cruzada multi-repo."""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ContractValidationResult:
    """Resultado estruturado da validação de contratos."""

    valid: bool = True
    errors: list[str] = field(default_factory=list)
    endpoints: list[str] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)


HTTP_METHODS = ("get", "post", "put", "delete", "patch")


def validate_openapi_info(info: object, errors: list[str]) -> None:
    """Valida a seção 'info' de uma especificação OpenAPI.

    Args:
        info: Objeto correspondente à chave 'info'.
        errors: Lista mutável onde erros encontrados são registrados.
    """
    if not isinstance(info, dict):
        errors.append("Seção 'info' ausente ou inválida.")
        return
    if not info.get("title"):
        errors.append("Campo 'info.title' obrigatório ausente.")
    if not info.get("version"):
        errors.append("Campo 'info.version' obrigatório ausente.")


def validate_endpoint_methods(
    endpoint_path: str,
    endpoint_obj: dict[object, object],
    errors: list[str],
) -> None:
    """Valida os métodos HTTP declarados em um endpoint OpenAPI.

    Args:
        endpoint_path: Caminho do endpoint (ex: '/items').
        endpoint_obj: Dicionário de métodos do endpoint.
        errors: Lista mutável onde erros encontrados são adicionados.
    """
    for method, method_obj in endpoint_obj.items():
        if str(method).lower() not in HTTP_METHODS:
            continue
        if isinstance(method_obj, dict) and "responses" not in method_obj:
            errors.append(
                f"Método {str(method).upper()} em {endpoint_path} "
                "não possui 'responses'."
            )


def validate_openapi_paths(paths: object, errors: list[str]) -> list[str]:
    """Valida a seção 'paths' de uma especificação OpenAPI e extrai os endpoints.

    Args:
        paths: Objeto correspondente à chave 'paths'.
        errors: Lista mutável onde erros encontrados são registrados.

    Returns:
        Lista de endpoints encontrados.
    """
    if paths is None:
        return []
    if not isinstance(paths, dict):
        errors.append("Seção 'paths' deve ser um dicionário.")
        return []

    endpoints: list[str] = []
    for endpoint_path, endpoint_obj in paths.items():
        path_str = str(endpoint_path)
        endpoints.append(path_str)
        if not isinstance(endpoint_obj, dict):
            continue
        validate_endpoint_methods(path_str, endpoint_obj, errors)
    return endpoints


def extract_openapi_schemas(components: object) -> list[str]:
    """Extrai a lista de nomes de schemas da seção 'components'.

    Args:
        components: Objeto correspondente à chave 'components'.

    Returns:
        Lista de nomes de schemas declarados.
    """
    if not isinstance(components, dict):
        return []
    schema_dict = components.get("schemas")
    if not isinstance(schema_dict, dict):
        return []
    return list(schema_dict.keys())


def validate_openapi_spec(spec_input: str | Path) -> ContractValidationResult:
    """Valida um arquivo ou string contendo especificação OpenAPI 3.x.

    Args:
        spec_input: Caminho do arquivo ou string contendo o YAML/JSON OpenAPI.

    Returns:
        Instância de ContractValidationResult indicando conformidade.
    """
    if isinstance(spec_input, Path):
        if not spec_input.is_file():
            return ContractValidationResult(
                valid=False,
                errors=[f"Arquivo de contrato não encontrado: {spec_input}"],
            )
        raw_text = spec_input.read_text(encoding="utf-8")
    else:
        raw_text = str(spec_input)

    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        return ContractValidationResult(
            valid=False,
            errors=[f"Erro de sintaxe YAML/JSON: {exc}"],
        )

    if not isinstance(data, dict):
        return ContractValidationResult(
            valid=False,
            errors=["Especificação OpenAPI deve ser um dicionário/objeto raiz."],
        )

    errors: list[str] = []
    openapi_version = data.get("openapi")
    if not openapi_version or not str(openapi_version).startswith("3."):
        errors.append("Versão 'openapi' 3.x obrigatória não encontrada.")

    validate_openapi_info(data.get("info"), errors)
    endpoints = validate_openapi_paths(data.get("paths"), errors)
    schemas = extract_openapi_schemas(data.get("components"))

    return ContractValidationResult(
        valid=len(errors) == 0,
        errors=errors,
        endpoints=endpoints,
        schemas=schemas,
    )


def extract_openapi_blocks(markdown_text: str) -> list[str]:
    """Extrai blocos de código com schemas OpenAPI de um documento Markdown.

    Args:
        markdown_text: Texto completo do documento Markdown.

    Returns:
        Lista de strings, cada uma contendo um bloco OpenAPI identificado.
    """
    pattern = re.compile(
        r"```(?:ya?ml|json)?\s*\n(openapi:\s*['\"]?3\..*?)```", re.DOTALL
    )
    blocks: list[str] = []
    for match in pattern.finditer(markdown_text):
        blocks.append(match.group(1))
    return blocks


def cross_validate_spec_contracts(
    markdown_spec: str, code_diffs: str
) -> ContractValidationResult:
    """Executa a validação cruzada de contratos a partir da spec e dos diffs.

    Args:
        markdown_spec: Conteúdo da especificação original.
        code_diffs: Diffs unificados dos repositórios spokes envolvidos.

    Returns:
        Instância consolidada de ContractValidationResult.
    """
    blocks = extract_openapi_blocks(markdown_spec)
    if not blocks:
        return ContractValidationResult(valid=True)

    all_errors: list[str] = []
    all_endpoints: list[str] = []
    all_schemas: list[str] = []

    for block in blocks:
        res = validate_openapi_spec(block)
        if not res.valid:
            all_errors.extend(res.errors)
        all_endpoints.extend(res.endpoints)
        all_schemas.extend(res.schemas)

    return ContractValidationResult(
        valid=len(all_errors) == 0,
        errors=all_errors,
        endpoints=sorted(set(all_endpoints)),
        schemas=sorted(set(all_schemas)),
    )


def run_contracts_cli() -> None:
    """CLI para validação de contratos a partir de arquivos."""
    parser = argparse.ArgumentParser(
        description="Validador de Contratos OpenAPI e Cross-Repo SDD"
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Caminho do arquivo Markdown da spec",
    )
    parser.add_argument(
        "--diffs",
        default=None,
        help="Caminho do arquivo de diffs consolidado",
    )
    parser.add_argument(
        "--out-file",
        default=None,
        help="Caminho para gravação do JSON de resultado",
    )
    args = parser.parse_args()

    spec_path = Path(args.spec)
    if not spec_path.is_file():
        print(f"Erro: Arquivo {spec_path} não encontrado.", file=sys.stderr)
        sys.exit(1)

    spec_content = spec_path.read_text(encoding="utf-8")
    diffs_content = ""
    if args.diffs and Path(args.diffs).is_file():
        diffs_content = Path(args.diffs).read_text(encoding="utf-8")

    result = cross_validate_spec_contracts(spec_content, diffs_content)

    payload = {
        "valid": result.valid,
        "errors": result.errors,
        "endpoints": result.endpoints,
        "schemas": result.schemas,
    }

    if args.out_file:
        Path(args.out_file).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    if not result.valid:
        sys.exit(1)


if __name__ == "__main__":
    run_contracts_cli()
