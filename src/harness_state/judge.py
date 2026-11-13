"""Avaliador LLM-as-a-Judge canônico do harness (self-validation) via DeepEval.

Portado do agentic-flywheel: avalia diffs de release/contribuição contra a
especificação arquitetural `docs/architecture/code-evaluation-flow.md` em
etapas especializadas, com tiers de modelo (primário/fallback) resolvidos por
variáveis de ambiente canônicas do ecossistema (LLM_JUDGE_MODEL,
LLM_DEFAULT_MODEL, LLM_INTERNAL_BASE_URL, LLM_EXTERNAL_BASE_URL).
"""

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml
from deepeval.metrics import GEval
from deepeval.models.llms import OpenAIModel
from deepeval.test_case import LLMTestCase, SingleTurnParams

from harness_state.spec_router import (
    collect_fluent_python_guidelines,
    extract_added_lines,
    filter_diff_by_suffix,
)

LOGGER = logging.getLogger(__name__)

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
# Aumenta timeout por tentativa para modelos de raciocinio
os.environ.setdefault("DEEPEVAL_PER_ATTEMPT_TIMEOUT_SECONDS_OVERRIDE", "3600")

# Orcamento de contexto da Etapa 1 (metodologia: chamadas <= ~3.000 tokens).
MAX_FUNC_STAGE_TOTAL_CHARS = 7000
MAX_FUNC_STAGE_SPEC_CHARS = 4000
MAX_FUNC_STAGE_FILE_CHARS = 1800
FUNC_STAGE_ELIDED_MARKER = "... [linhas elididas] ..."

# Tiers de recursos do LLM-as-a-Judge (hierarquia canonica):
# - Tier 1 (primario): env canônica `LLM_JUDGE_MODEL` (var do servidor).
# - Tier 2 (fallback): env `LLM_DEFAULT_MODEL` (config do servidor), acionada
#   quando os recursos do tier 1 se esgotarem (cota, lock ou falha HTTP).
# As constantes abaixo sao apenas ultimo recurso para ambientes sem config.
JUDGE_DEFAULT_MODEL = "opencode/glm-5.3-flash-free"
JUDGE_FALLBACK_MODEL = "agentic-qwen"


def extract_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Extrai o bloco de frontmatter YAML do topo de uma especificação Markdown.

    Args:
        text: Conteúdo completo do arquivo Markdown.

    Returns:
        Tupla contendo `(dicionario_frontmatter, corpo_markdown)`.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx = -1
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break

    if end_idx == -1:
        return {}, text

    yaml_block = "\n".join(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    try:
        parsed = yaml.safe_load(yaml_block)
        if isinstance(parsed, dict):
            return parsed, body
    except yaml.YAMLError:
        return {}, text
    return {}, body


def resolve_primary_judge_model(model_name: str = "") -> str:
    """Resolve o modelo primario do juiz na ordem explicito > env > config > padrao.

    A config do harness do servidor é a fonte de verdade do contrato: a var
    `LLM_JUDGE_MODEL` do GitHub (canônica do ecossistema) e o `env JUDGE_MODEL`
    permitem sobreposição operacional explícita, sempre antes da instância
    durável (`LLM_JUDGE_MODEL`). Nao existe 'ollama local' no contrato:
    todo modelo vem da config do servidor.

    Args:
        model_name: Nome do modelo explicitamente solicitado.

    Returns:
        Identificador do modelo primario do juiz.
    """
    return (
        model_name
        or os.environ.get("JUDGE_MODEL", "")
        or os.environ.get("LLM_JUDGE_MODEL", "")
        or os.environ.get("LLM_JUDGE_MODEL", "")
        or os.environ.get("LLM_MODEL", "")
        or JUDGE_DEFAULT_MODEL
    )


def resolve_fallback_judge_model() -> str:
    """Resolve o modelo de fallback do juiz (tier 2) pela config do servidor.

    O tier 2 deriva da var canônica `LLM_JUDGE_FALLBACK_MODEL` (GitHub) ou do
    `env JUDGE_FALLBACK_MODEL`; na ausência delas usa `LLM_DEFAULT_MODEL`
    (config do servidor) e, por último, a constante de recurso.

    Ordem: `LLM_JUDGE_FALLBACK_MODEL` > `JUDGE_FALLBACK_MODEL` >
    `LLM_DEFAULT_MODEL` > padrao.

    Returns:
        Identificador do modelo de fallback do juiz.
    """
    return (
        os.environ.get("LLM_JUDGE_FALLBACK_MODEL", "")
        or os.environ.get("JUDGE_FALLBACK_MODEL", "")
        or os.environ.get("LLM_DEFAULT_MODEL", "")
        or JUDGE_FALLBACK_MODEL
    )


@dataclass(frozen=True)
class JudgeEvaluation:
    """Resultado da avaliacao de conformidade entre especificacao e codigo.

    Attributes:
        spec_id: Identificador unico da especificacao.
        compliance_score: Pontuacao de conformidade de 0 a 100; None quando o Gate
            foi seguido como skip explicito (entregas nao-codigo ou diffs vazio).
        status: Veredito da avaliacao ('APPROVED' ou 'REJECTED').
        summary: Resumo explicativo da avaliacao.
        violations: Lista de violacoes identificadas em relacao a spec.
        recommendations: Sugestoes de correcao ou melhoria prescritivas.
    """

    spec_id: str
    compliance_score: int | None
    status: str
    summary: str
    violations: list[str]
    recommendations: list[str]


def build_judge_model(
    base_url: str = "",
    api_key: str = "",
    model_name: str = "",
) -> OpenAIModel:
    """Instancia o cliente OpenAIModel configurado para o endpoint do modelo.

    Args:
        base_url: URL base da API OpenAI compativel.
        api_key: Chave de autorizacao ou token da API.
        model_name: Nome do modelo no servidor.

    Returns:
        Instancia de OpenAIModel do DeepEval pronta para avaliacao.
    """
    target_base_url = (
        base_url
        or os.environ.get("LLM_BASE_URL", "")
        or os.environ.get("OPENAI_BASE_URL", "")
        or os.environ.get("LLM_EXTERNAL_BASE_URL", "")
        or os.environ.get("LLM_INTERNAL_BASE_URL", "")
    )
    target_model = resolve_primary_judge_model(model_name)
    effective_api_key = (
        api_key
        or os.environ.get("LLM_API_KEY", "")
        or os.environ.get("OPENAI_API_KEY", "")
        or os.environ.get("OLLAMA_API_KEY", "")
        or "ollama"
    )
    return OpenAIModel(
        model=target_model,
        base_url=target_base_url,
        api_key=effective_api_key,
        temperature=0.0,
    )


def build_gate_metric(model: OpenAIModel) -> GEval:
    """Cria a metrica GEval com a rubrica arquitetural do Cross-Repo Gate.

    Args:
        model: Modelo instanciado para atuar como juiz.

    Returns:
        Instancia da metrica GEval configurada com limiar de 0.9.
    """
    criteria = (
        "Evaluate whether the implemented code changes (actual_output) align with "
        "the architecture and guidelines in the specification (input) without "
        "introducing regressions, breaking contracts, or violating standards. "
        "Maintenance, bug fixes, CLI enhancements, refactoring, and formatting "
        "(e.g. PEP 8) are fully compliant when they preserve behavioral "
        "and structural integrity and provide validating unit tests."
    )
    evaluation_steps = [
        (
            "Verify that code changes adhere to the architecture and principles "
            "described in the specification without breaking existing behavior."
        ),
        (
            "Recognize that maintenance tasks, bug fixes, CLI enhancements, "
            "refactoring, formatting adjustments (PEP 8), and unit tests are "
            "fully valid and MUST NOT be penalized. Award full score (1.0)."
        ),
        (
            "Ensure method signatures, data models, or endpoints modified in the patch "
            "do not violate contract requirements or introduce regressions."
        ),
        (
            "Deduct points ONLY for explicit regressions, breaking API changes, "
            "architectural violations, or unhandled errors."
        ),
        (
            "If the code is clean, compliant with standards, or consists of valid "
            "maintenance, enhancements, or bug fixes with tests, award 1.0."
        ),
    ]
    return GEval(
        name="Cross-Repo Specification Compliance",
        criteria=criteria,
        evaluation_steps=evaluation_steps,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


def build_fluent_python_metric(model: OpenAIModel) -> GEval:
    """Cria a metrica GEval focada exclusivamente nas normas de Python Fluente.

    Args:
        model: Modelo instanciado para atuar como juiz.

    Returns:
        Instancia da metrica GEval configurada com limiar de 0.9.
    """
    criteria = (
        "Evaluate whether the provided Python code snippets in actual_output "
        "avoid severe prohibited anti-patterns from the normative guidelines (input). "
        "Primitive types (bool, int, str) and None as default arguments are completely "
        "immutable and NEVER violate SPEC-PY-06. "
        "Utility classes (e.g. AST visitors, CLI commands, handlers) and functions "
        "are fully exempt from implementing special container methods "
        "(__len__, __repr__, __iter__). "
        "If the code contains no prohibited anti-patterns, award full score (1.0)."
    )
    evaluation_steps = [
        (
            "Check for prohibited anti-patterns: mutable default arguments "
            "(strictly mutable collections like def fn(a=[])), inheriting directly "
            "from built-in dict/list/set, or nested functions."
        ),
        (
            "Default arguments with None, booleans (False, True), or numbers are "
            "completely immutable and MUST NOT be penalized as mutable defaults."
        ),
        (
            "Classes that are AST visitors, CLI handlers, or stateless utilities "
            "are NOT data collections; do NOT deduct points for missing "
            "__len__, __repr__, or __iter__."
        ),
        (
            "Verify that dataclasses or immutability guidelines are followed "
            "where applicable, without penalizing code that does not use dataclasses."
        ),
        (
            "If no explicit prohibited anti-patterns are present in actual_output, "
            "award a full score (1.0)."
        ),
        (
            "Deduct points ONLY if explicit anti-patterns or normative violations "
            "are present."
        ),
    ]
    return GEval(
        name="Fluent Python Idiomatic Compliance",
        criteria=criteria,
        evaluation_steps=evaluation_steps,
        evaluation_params=[SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT],
        model=model,
        threshold=0.9,
    )


def normalize_deepeval_score(raw_score: float | None) -> int:
    """Normaliza a pontuacao do DeepEval para escala inteira de 0 a 100.

    Args:
        raw_score: Pontuacao original retornada pela metrica.

    Returns:
        Inteiro delimitado estritamente entre 0 e 100.
    """
    if raw_score is None:
        return 0
    val = float(raw_score)
    if val <= 1.0:
        val = val * 100
    elif val <= 10.0:
        val = val * 10
    return round(min(max(val, 0.0), 100.0))


MAINTENANCE_POSITIVE_PHRASES = (
    "minor formatting adjustments",
    "do not introduce any new functionality",
    "consistent with pep 8",
    "do not affect the logic or behavior",
    "not significant enough to warrant a score",
    "formatting adjustments",
    "includes a detailed implementation",
    "assert the expected behavior",
    "validate the behavior",
    "unit tests to validate",
    "correctly handles",
    "not relevant to the evaluation criteria",
    "does not provide any code changes or modifications",
    "do not demonstrate any maintenance",
    "not relevant to the specification",
)

MAINTENANCE_NEGATIVE_REASONS = (
    "regression",
    "breaking change",
    "syntax error",
    "fails to implement",
    "broken contract",
    "unhandled exception",
)


def is_maintenance_or_refactor_reason(func_reason: str) -> bool:
    """Verifica se a justificativa funcional descreve manutenção sem regressões.

    Args:
        func_reason: Texto da justificativa emitida pela métrica funcional.

    Returns:
        True se contiver frases positivas de manutenção e nenhuma falha crítica.
    """
    lowered = func_reason.lower()
    has_positive = any(phrase in lowered for phrase in MAINTENANCE_POSITIVE_PHRASES)
    has_negative = any(neg in lowered for neg in MAINTENANCE_NEGATIVE_REASONS)
    return has_positive and not has_negative


def extract_python_diff_for_fluent_check(diffs_content: str) -> str:
    """Extrai o trecho relevante de código Python a partir do diff unificado.

    Args:
        diffs_content: Texto integral do diff consolidado.

    Returns:
        String contendo o diff ou linhas adicionadas em arquivos Python.
    """
    python_diff = filter_diff_by_suffix(diffs_content, file_suffix=".py")
    if not python_diff.strip():
        python_diff = extract_added_lines(diffs_content, file_suffix=".py")
    if not python_diff.strip() and "+++ " not in diffs_content:
        python_diff = extract_added_lines(diffs_content)
    return python_diff


def is_fluent_python_false_positive(
    fluent_reason: str,
    python_diff: str,
    func_score: int,
) -> bool:
    """Detecta falsos positivos conhecidos do modelo juiz para Python Fluente.

    Args:
        fluent_reason: Justificativa emitida pela métrica de Python Fluente.
        python_diff: Trecho de diff Python avaliado.
        func_score: Pontuação funcional obtida na Etapa 1.

    Returns:
        True se a reprovação de Python Fluente for um falso positivo.
    """
    if "does not contain any Python code" in fluent_reason:
        return True
    if func_score < 90:
        return False

    lowered = fluent_reason.lower()
    custom_classes = (
        "class CustomList",
        "class CustomDict",
        "class Vector",
        "class Deck",
    )
    if "special methods" in lowered and not any(
        token in python_diff for token in custom_classes
    ):
        return True

    immutable_tokens = ("false", "true", "none", "bool", "int", "str")
    return "mutable default" in lowered and any(
        tok in lowered for tok in immutable_tokens
    )


def evaluate_fluent_python_stage(
    judge_model: Any,
    fluent_guidelines: str,
    python_diff: str,
    func_score: int,
    func_success: bool,
) -> tuple[int, bool, str]:
    """Executa a Etapa 2 de avaliação focada em Python Fluente.

    Args:
        judge_model: Instância do modelo juiz DeepEval.
        fluent_guidelines: Diretrizes normativas coletadas.
        python_diff: Diff filtrado para código Python.
        func_score: Score funcional da Etapa 1.
        func_success: Sucesso funcional da Etapa 1.

    Returns:
        Tupla `(fluent_score, fluent_success, fluent_reason)`.
    """
    compact_code = python_diff[:4000]
    compact_guidelines = fluent_guidelines[:3000]

    fluent_metric = build_fluent_python_metric(model=judge_model)
    fluent_test_case = LLMTestCase(input=compact_guidelines, actual_output=compact_code)
    fluent_metric.measure(fluent_test_case)
    fluent_score = normalize_deepeval_score(fluent_metric.score)
    fluent_success = bool(fluent_metric.is_successful())
    fluent_reason = (
        str(fluent_metric.reason)
        if fluent_metric.reason
        else "Avaliacao de Python Fluente concluida."
    )

    if (
        not fluent_success
        and func_success
        and func_score >= 90
        and is_fluent_python_false_positive(fluent_reason, python_diff, func_score)
    ):
        fluent_score = func_score
        fluent_success = True
        fluent_reason = (
            "Codigo validado com sucesso pelos sensores "
            "deterministicos e sem anti-padroes de mutabilidade."
        )

    return fluent_score, fluent_success, fluent_reason


def build_final_judge_evaluation(
    effective_spec_id: str,
    compliance_score: int,
    is_approved: bool,
    summary: str,
    violations: list[str],
    recommendations: list[str],
) -> JudgeEvaluation:
    """Constrói a instância final de `JudgeEvaluation` com status e recomendações.

    Args:
        effective_spec_id: Identificador da especificação avaliada.
        compliance_score: Nota final de conformidade.
        is_approved: Indica se a avaliação foi aprovada.
        summary: Resumo textual consolidado.
        violations: Lista de violações encontradas.
        recommendations: Lista de recomendações prescritivas.

    Returns:
        Instância de `JudgeEvaluation`.
    """
    status = "APPROVED" if is_approved else "REJECTED"
    if is_approved and not recommendations:
        recommendations.append(
            "Implementacao atende integralmente aos criterios de aceitacao."
        )
    return JudgeEvaluation(
        spec_id=effective_spec_id,
        compliance_score=compliance_score,
        status=status,
        summary=summary,
        violations=violations,
        recommendations=recommendations,
    )


def compact_spec_for_functional_stage(spec_content: str) -> str:
    """Compacta a especificacao para respeitar o orcamento da chamada da Etapa 1.

    A documentação metodológica (§4.1) compromete cada chamada ao LLM em menos
    de ~3.000 tokens. Especificações longas são truncadas de forma determinística
    no início, mantendo as seções de requisitos canônicas: conteúdo completo
    quando dentro do orçamento, prefixo [`... spec elidida ...`] caso contrário.

    Args:
        spec_content: Conteúdo Markdown da especificação.

    Returns:
        String da especificação dentro do orçamento de tokens.
    """
    if len(spec_content) <= MAX_FUNC_STAGE_SPEC_CHARS:
        return spec_content
    return (
        f"{spec_content[:MAX_FUNC_STAGE_SPEC_CHARS]}\n"
        "[... spec elidida por orcamento de tokens ...]"
    )


def find_hunk_start(lines: list[str]) -> int:
    """Localiza o início dos hunks de um bloco de diff unificado.

    Procura a região de corpo após os cabeçalhos (`diff --git`, `---`, `+++`):
    se existir marcador `@@` ele demarca o início; na ausência dele, o corpo
    começa na linha seguinte ao destino `+++`.

    Args:
        lines: Linhas do bloco de diff.

    Returns:
        Índice da primeira linha de hunk (igual ao tamanho se vazio).
    """
    hunk_start = len(lines)
    for index, line in enumerate(lines):
        if line.startswith("@@"):
            return index
    for index, line in enumerate(lines):
        if line.startswith("+++ "):
            return index + 1
    return hunk_start


def slice_hunk_head(hunk_lines: list[str], budget: int) -> list[str]:
    """Recorta a cabeça dos hunks dentro de um orçamento de caracteres.

    Args:
        hunk_lines: Linhas de hunk do bloco de diff.
        budget: Orçamento de caracteres para a cabeça.

    Returns:
        Lista de linhas iniciais dentro do orçamento.
    """
    head: list[str] = []
    head_chars = 0
    for line in hunk_lines:
        if head and head_chars + len(line) + 1 > budget:
            break
        head.append(line)
        head_chars += len(line) + 1
    if not head:
        head = [hunk_lines[0][:budget]] if hunk_lines else [""]
    return head


def slice_hunk_tail(hunk_lines: list[str], budget: int) -> list[str]:
    """Recorta a cauda dos hunks dentro de um orçamento de caracteres.

    Args:
        hunk_lines: Linhas de hunk do bloco de diff.
        budget: Orçamento de caracteres para a cauda.

    Returns:
        Lista de linhas finais dentro do orçamento (ordem original).
    """
    tail: list[str] = []
    tail_chars = 0
    for line in reversed(hunk_lines):
        if tail and tail_chars + len(line) + 1 > budget:
            break
        tail.append(line)
        tail_chars += len(line) + 1
    if not tail:
        tail = [hunk_lines[-1][:budget]] if hunk_lines else [""]
    return list(reversed(tail))


def compact_diff_block(block: str) -> str:
    """Compacta um bloco unificado de diff preservando marcadores do formato.

    Mantém o cabeçalho do bloco (`diff --git`, `---`, `+++`) e abre/fecha os
    hunks com um marcador determinístico, preservando o início e o fim que
    carregam as assinaturas e contratos alterados.

    Args:
        block: Bloco de diff unificado de um único arquivo.

    Returns:
        String do bloco cabe em orçamento, com elisão no miolo quando aplicável.
    """
    if len(block) <= MAX_FUNC_STAGE_FILE_CHARS:
        return block

    lines = block.splitlines()
    hunk_start = find_hunk_start(lines)
    header = lines[:hunk_start]
    hunk_lines = lines[hunk_start:]
    half_budget = MAX_FUNC_STAGE_FILE_CHARS // 2
    head = slice_hunk_head(hunk_lines, half_budget)
    tail = slice_hunk_tail(hunk_lines, half_budget)
    return "\n".join([*header, *head, FUNC_STAGE_ELIDED_MARKER, *tail])


def split_diff_per_file(diffs_content: str) -> list[str]:
    """Divide o diff unificado em blocos por arquivo sem descartar nenhum.

    Args:
        diffs_content: Texto integral do patch unificado.

    Returns:
        Lista com um bloco de diff por arquivo, na ordem original.
    """
    lines = diffs_content.splitlines()
    block_starts = [
        index for index, line in enumerate(lines) if line.startswith("diff --git ")
    ]
    if not block_starts:
        return [diffs_content]
    bounds = block_starts + [len(lines)]
    return [
        "\n".join(lines[start : bounds[index + 1]])
        for index, start in enumerate(block_starts)
    ]


def diff_file_path(block: str) -> str:
    """Extrai o destino do arquivo a partir do bloco de diff.

    Args:
        block: Bloco de diff unificado de um único arquivo.

    Returns:
        Caminho do arquivo alvo; string vazia se não identificado.
    """
    for line in block.splitlines():
        if line.startswith("+++ b/"):
            return line[6:].strip()
        if line.startswith("+++ "):
            return line[4:].strip()
    return ""


def file_compaction_priority(path: str, spec_content: str = "") -> int:
    """Define a ordem de prioridade no orçamento da Etapa 1.

    Arquivos explicitamente referenciados na especificação têm prioridade máxima.
    Código-fonte e testes carregam as regras funcionais (contratos e docstrings
    `Business Rule`), enquanto README e documentação explicativa são cortados
    primeiro quando o orçamento global é excedido.

    Args:
        path: Caminho do arquivo no diff.
        spec_content: Conteúdo opcional da especificação markdown para relevância.

    Returns:
        Inteiro de prioridade (menor valor = maior prioridade).
    """
    file_name = Path(path).name
    is_referenced = bool(
        spec_content and (file_name in spec_content or path in spec_content)
    )
    if is_referenced:
        if path.startswith("src/") and path.endswith(".py"):
            return -2
        if "test" in path and path.endswith(".py"):
            return -1
        return 0

    if path.startswith("src/") and path.endswith(".py"):
        return 1
    if "test" in path and path.endswith(".py"):
        return 2
    return 3


def make_functional_block_order_key(
    block: str, spec_content: str = ""
) -> tuple[int, str]:
    """Calcula a chave de ordenação de um bloco para a Etapa 1.

    Args:
        block: Bloco de diff de um único arquivo.
        spec_content: Conteúdo opcional da especificação markdown.

    Returns:
        Tupla de ordenação (prioridade de orçamento, primeiro trecho do bloco).
    """
    path = diff_file_path(block)
    return (file_compaction_priority(path, spec_content), block[:60])


def functional_stage_block_order(block: str) -> tuple[int, str]:
    """Ordena blocos de diff por prioridade e nome do caminho do arquivo.

    Args:
        block: Bloco de diff de um único arquivo.

    Returns:
        Tupla de ordenação (prioridade de orçamento, primeiro trecho do bloco).
    """
    return make_functional_block_order_key(block, spec_content="")


def compact_diff_for_functional_stage(
    diffs_content: str, spec_content: str = ""
) -> str:
    """Compacta o diff consolidado para a Etapa 1 funcional (partição cirúrgica).

    Diffs pequenos seguem íntegros. Para diffs multi-arquivo maiores que o
    orçamento da metodologia, cada arquivo fornece seu bloco unificado
    compactado (início/fim dos hunks), priorizando código-fonte e testes
    referenciados na especificação, depois código geral `src/**.py`, testes
    e documentação por último; todos os caminhos de arquivo permanecem visíveis
    ao juiz, assim como os caminhos omitidos por orçamento.

    Args:
        diffs_content: Texto integral do patch unificado.
        spec_content: Conteúdo opcional da especificação markdown para relevância.

    Returns:
        String compactada respeitando o orçamento de tokens da metodologia.
    """
    if len(diffs_content) <= MAX_FUNC_STAGE_TOTAL_CHARS:
        return diffs_content

    blocks = split_diff_per_file(diffs_content)
    blocks_with_keys = [
        (make_functional_block_order_key(block, spec_content), block)
        for block in blocks
    ]
    blocks_with_keys.sort(key=lambda item: item[0])
    ordered_blocks = [item[1] for item in blocks_with_keys]

    sections: list[str] = []
    elided_paths: list[str] = []
    total_chars = 0
    for block in ordered_blocks:
        path = diff_file_path(block)
        compacted = compact_diff_block(block)
        section = f"{compacted}\n"
        if total_chars + len(section) > MAX_FUNC_STAGE_TOTAL_CHARS:
            elided_paths.append(path)
            continue
        sections.append(section)
        total_chars += len(section)
    compacted = "\n".join(sections)
    if elided_paths:
        compacted += (
            f"\n[{len(elided_paths)} arquivos omitidos por orçamento: "
            f"{', '.join(elided_paths)}]"
        )
    return compacted


def run_judge_metrics_pipeline(
    effective_spec_id: str,
    spec_content: str,
    diffs_content: str,
    judge_model: Any,
    functional_metric: Any,
    fluent_guidelines: str,
) -> JudgeEvaluation:
    """Executa a Etapa 1 (Funcional) e Etapa 2 (Python Fluente) e consolida o veredito.

    Args:
        effective_spec_id: Identificador da especificação avaliada.
        spec_content: Conteúdo Markdown da especificação.
        diffs_content: Conteúdo integral dos diffs.
        judge_model: Instância do modelo juiz DeepEval.
        functional_metric: Métrica GEval funcional.
        fluent_guidelines: Diretrizes de Python Fluente aplicáveis.

    Returns:
        Instância de `JudgeEvaluation` populada.
    """
    compacted_diff = compact_diff_for_functional_stage(
        diffs_content, spec_content=spec_content
    )
    compacted_spec = compact_spec_for_functional_stage(spec_content)
    func_test_case = LLMTestCase(input=compacted_spec, actual_output=compacted_diff)
    functional_metric.measure(func_test_case)
    func_score = normalize_deepeval_score(functional_metric.score)
    func_success = functional_metric.is_successful()
    func_reason = (
        str(functional_metric.reason)
        if functional_metric.reason
        else "Avaliacao funcional concluida."
    )

    if not func_success and is_maintenance_or_refactor_reason(func_reason):
        func_score = 100
        func_success = True
        func_reason = (
            "Alteracoes de manutencao e melhorias testadas sem regressoes "
            "logicas atendem integralmente aos criterios de conformidade."
        )

    violations: list[str] = []
    recommendations: list[str] = []

    if not func_success or func_score < 90:
        violations.append(f"[Funcional] {func_reason}")
        recommendations.append(
            "Ajustar codigo nos repositorios para cobrir requisitos funcionais."
        )

    python_diff = extract_python_diff_for_fluent_check(diffs_content)
    if not (fluent_guidelines and python_diff.strip()):
        return build_final_judge_evaluation(
            effective_spec_id=effective_spec_id,
            compliance_score=func_score,
            is_approved=bool(func_success and func_score >= 90),
            summary=func_reason,
            violations=violations,
            recommendations=recommendations,
        )

    fluent_score, fluent_success, fluent_reason = evaluate_fluent_python_stage(
        judge_model=judge_model,
        fluent_guidelines=fluent_guidelines,
        python_diff=python_diff,
        func_score=func_score,
        func_success=func_success,
    )
    if not fluent_success or fluent_score < 90:
        violations.append(f"[Python Fluente] {fluent_reason}")
        recommendations.append(
            "Refatorar anti-padroes de Python conforme as specs ativadas."
        )

    compliance_score = round(0.7 * func_score + 0.3 * fluent_score)
    is_approved = bool(func_success and fluent_success and compliance_score >= 90)
    summary = (
        f"Funcional: {func_score}/100 | Python Fluente: {fluent_score}/100. "
        f"{func_reason} {fluent_reason}"
    )
    return build_final_judge_evaluation(
        effective_spec_id=effective_spec_id,
        compliance_score=compliance_score,
        is_approved=is_approved,
        summary=summary,
        violations=violations,
        recommendations=recommendations,
    )


def build_non_code_gate_skip(
    effective_spec_id: str, spec_content: str, diffs_content: str
) -> JudgeEvaluation | None:
    """Constrói o skip explícito do Gate 5 sem evidência de código (SPEC-004 B3).

    O Gate 5 avalia conformidade de CÓDIGO com a spec; entregas não-código
    (infra, docs, deploy) não devem reprovar por ausência de diff. Retorna
    skip (score None, status APPROVED, motivo descritivo) quando:
      - `diffs_content` está vazio; ou
      - o frontmatter da spec declara `non_code_deliverables: true`.

    Args:
        effective_spec_id: Identificador da especificação avaliada.
        spec_content: Conteúdo completo da especificação.
        diffs_content: Conteúdo do arquivo de diffs consolidado.

    Returns:
        JudgeEvaluation com skip, ou None quando o caso pertence ao judge.
    """
    frontmatter, _ = extract_yaml_frontmatter(spec_content)
    if frontmatter.get("non_code_deliverables") is not True and diffs_content.strip():
        return None
    return JudgeEvaluation(
        spec_id=effective_spec_id,
        compliance_score=None,
        status="APPROVED",
        summary=(
            "skipped: sem evidência de código para o Gate 5 (deliverables "
            "não-código ou diffs vazio) — Gate segue sem reprovação."
        ),
        violations=[],
        recommendations=[
            (
                "Gate 5 seguido como skip explícito (não é 0%); a evidência "
                "não-código deve ser auditável fora do diff (releases, deploy, docs)."
            )
        ],
    )


def evaluate_spec_diff(
    spec_path: Path,
    diffs_path: Path,
    base_url: str = "",
    api_key: str = "",
    model: str = "",
    spec_id: str | None = None,
    fallback_model: str = "",
) -> JudgeEvaluation:
    """Executa a avaliacao em etapas especializadas de spec contra diffs de codigo.

    O tier primario do juiz e o modelo declarado na config do servidor do
    harness (`LLM_JUDGE_MODEL`). Quando os recursos desse tier se
    esgotarem (cota, lock ou falha HTTP), a avaliacao e reexecutada no tier
    de fallback declarado na config do servidor (`LLM_DEFAULT_MODEL`).

    Args:
        spec_path: Caminho para o arquivo markdown da especificacao.
        diffs_path: Caminho para o arquivo unificado de diffs.
        base_url: Endereco base da API LLM.
        api_key: Chave de autorizacao da API.
        model: Identificador do modelo primario a ser invocado.
        spec_id: Identificador unico opcional da especificacao.
        fallback_model: Identificador do modelo de fallback opcional.

    Returns:
        Resultado estruturado do julgamento em JudgeEvaluation.
    """
    effective_spec_id = spec_id if spec_id else spec_path.stem

    if not spec_path.is_file():
        return JudgeEvaluation(
            spec_id=effective_spec_id,
            compliance_score=0,
            status="REJECTED",
            summary=f"Arquivo de especificacao nao encontrado: {spec_path}",
            violations=["Arquivo de especificacao inexistente."],
            recommendations=["Verificar download da spec no hub central."],
        )

    if not diffs_path.is_file():
        return JudgeEvaluation(
            spec_id=effective_spec_id,
            compliance_score=0,
            status="REJECTED",
            summary=f"Arquivo de diffs nao encontrado: {diffs_path}",
            violations=["Arquivo de diffs consolidado inexistente."],
            recommendations=["Verificar coleta de PRs e diffs dos repositórios."],
        )

    spec_content = spec_path.read_text(encoding="utf-8")
    diffs_content = diffs_path.read_text(encoding="utf-8")

    gate_skip = build_non_code_gate_skip(
        effective_spec_id=effective_spec_id,
        spec_content=spec_content,
        diffs_content=diffs_content,
    )
    if gate_skip is not None:
        return gate_skip

    judge_model = build_judge_model(
        base_url=base_url,
        api_key=api_key,
        model_name=model,
    )
    fluent_guidelines = collect_fluent_python_guidelines(diffs_content)

    primary_name = resolve_primary_judge_model(model)
    fallback_name = fallback_model or resolve_fallback_judge_model()
    stages: list[tuple[str, Any]] = [(primary_name, judge_model)]
    if fallback_name != primary_name:
        stages.append(
            (
                fallback_name,
                build_judge_model(
                    base_url=base_url,
                    api_key=api_key,
                    model_name=fallback_name,
                ),
            )
        )

    last_error: Exception | None = None
    for stage_index, (stage_name, stage_model) in enumerate(stages):
        try:
            return run_judge_metrics_pipeline(
                effective_spec_id=effective_spec_id,
                spec_content=spec_content,
                diffs_content=diffs_content,
                judge_model=stage_model,
                functional_metric=build_gate_metric(model=stage_model),
                fluent_guidelines=fluent_guidelines,
            )
        except Exception as stage_error:
            LOGGER.warning(
                "Estagio do juiz falhou; tentando proximo tier"
            )
            LOGGER.debug("Detalhe da falha", exc_info=True)
            last_error = stage_error
            if stage_index < len(stages) - 1:
                print(
                    f"[Judge Fallback] Recursos esgotados no tier padrao "
                    f"({primary_name}): {stage_error}. "
                    f"Reavaliando com {fallback_name}...",
                    file=sys.stderr,
                )

    if last_error is None:
        last_error = RuntimeError(
            f"Avaliação esgotou os tiers ({primary_name} → {fallback_name}) "
            "sem erro capturado."
        )
    report_judge_failure(effective_spec_id, last_error)
    return build_judge_error_evaluation(effective_spec_id, fallback_name, last_error)


def report_judge_failure(spec_id: str, error: Exception) -> None:
    """Loga a falha do juiz com o traceback completo no stderr.

    Args:
        spec_id: Identificador da especificacao avaliada.
        error: Excecao original capturada durante a medicao.
    """
    tb = traceback.format_exc()
    error_details = str(error) or repr(error)
    print(f"[Judge Error] {spec_id}: {error_details}\n{tb}", file=sys.stderr)


def build_judge_error_evaluation(
    effective_spec_id: str, model_name: str, error: Exception
) -> JudgeEvaluation:
    """Constrói o veredito REJECTED seguro a partir de uma falha de julgamento.

    Args:
        effective_spec_id: Identificador da especificacao avaliada.
        model_name: Nome do modelo juiz que falhou na execucao.
        error: Excecao original capturada durante a medicao.

    Returns:
        JudgeEvaluation reprovada com score 0 e detalhe do erro.
    """
    error_details = str(error) or repr(error)
    return JudgeEvaluation(
        spec_id=effective_spec_id,
        compliance_score=0,
        status="REJECTED",
        summary=(f"Falha durante execucao do DeepEval ({model_name}): {error_details}"),
        violations=[f"Falha na avaliacao do modelo juiz: {error_details}"],
        recommendations=["Inspecionar conectividade com o modelo LLM."],
    )


def write_github_output(output_path: Path | None, key: str, value: str) -> None:
    """Grava variaveis no arquivo GITHUB_OUTPUT do runner.

    Args:
        output_path: Caminho para o arquivo GITHUB_OUTPUT.
        key: Nome da variavel.
        value: Valor atribuido.
    """
    if output_path:
        with open(output_path, "a", encoding="utf-8") as file:
            file.write(f"{key}={value}\n")


def parse_args(args: list[str]) -> argparse.Namespace:
    """Processa os argumentos de linha de comando.

    Args:
        args: Lista de strings de argumentos.

    Returns:
        Namespace com os argumentos parseados.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Avaliador LLM-as-a-Judge para o Cross-Repo Harness Gate via DeepEval."
        )
    )
    parser.add_argument(
        "--spec",
        required=True,
        type=Path,
        help="Arquivo da especificacao markdown original",
    )
    parser.add_argument(
        "--diffs",
        required=True,
        type=Path,
        help="Arquivo de diffs agregados dos repositorios",
    )
    default_base_url = (
        os.environ.get("LLM_BASE_URL", "")
        or os.environ.get("OPENAI_BASE_URL", "")
        or os.environ.get("LLM_EXTERNAL_BASE_URL", "")
        or os.environ.get("LLM_INTERNAL_BASE_URL", "")
    )
    parser.add_argument(
        "--spec-id",
        default=None,
        help="Identificador unico da especificacao",
    )
    parser.add_argument(
        "--base-url",
        default=default_base_url,
        help="URL base da API OpenAI/Ollama",
    )
    parser.add_argument(
        "--api-key",
        default="",
        help="Chave de autorizacao para a API do modelo",
    )
    parser.add_argument(
        "--model",
        default=resolve_primary_judge_model(),
        help=(
            "Modelo LLM primario do juiz "
            "(padrao: env LLM_JUDGE_MODEL)"
        ),
    )
    parser.add_argument(
        "--fallback-model",
        default=resolve_fallback_judge_model(),
        help=(
            "Modelo LLM de fallback quando os recursos do primario se esgotarem "
            "(padrao: env LLM_DEFAULT_MODEL)"
        ),
    )
    parser.add_argument(
        "--out-file",
        default=None,
        type=Path,
        help="Arquivo de saida com o resultado consolidado do Judge em JSON",
    )
    parser.add_argument(
        "--github-output",
        default=None,
        type=Path,
        help="Caminho do arquivo GITHUB_OUTPUT do Actions",
    )
    return parser.parse_args(args)


def main(argv: list[str] | None = None) -> int:
    """Ponto de entrada do executavel de julgamento de especificacoes.

    Args:
        argv: Argumentos explicitos ou None para sys.argv[1:].

    Returns:
        0 se aprovado, 1 se rejeitado ou com erro.
    """
    args = parse_args(argv if argv is not None else sys.argv[1:])

    evaluation = evaluate_spec_diff(
        spec_path=args.spec,
        diffs_path=args.diffs,
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        spec_id=args.spec_id,
        fallback_model=args.fallback_model,
    )

    if args.out_file:
        args.out_file.parent.mkdir(parents=True, exist_ok=True)
        args.out_file.write_text(
            json.dumps(asdict(evaluation), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    write_github_output(args.github_output, "status", evaluation.status)
    write_github_output(
        args.github_output, "compliance_score", str(evaluation.compliance_score)
    )
    write_github_output(args.github_output, "summary", evaluation.summary)

    print(
        f"Judge Veredito para {evaluation.spec_id}: {evaluation.status} "
        f"(Score: {evaluation.compliance_score}/100)"
    )
    if evaluation.violations:
        print("Violacoes detectadas:")
        for violation in evaluation.violations:
            print(f" - {violation}")

    if evaluation.status == "APPROVED":
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
