"""Motor de descoberta prévia de especificações existentes (SPEC-011)."""

import re
from pathlib import Path

from harness_state.models import SpecMatch
from harness_state.spec.lifecycle import extract_yaml_frontmatter

SPEC_ID_REGEX = re.compile(r"SPEC-(\d+)", re.IGNORECASE)
TOKEN_REGEX = re.compile(r"\b[a-zA-Z0-9_-]{3,}\b")

STOP_WORDS = {
    "para", "com", "de", "do", "da", "dos", "das", "em", "no", "na", "nos",
    "nas", "um", "uma", "uns", "umas", "por", "que", "como", "mais", "mas",
    "suportar", "melhorar", "adicionar", "criar", "fazer", "novo", "nova",
    "formato", "tipo", "modo", "suporte", "padrao", "ajustar", "alterar",
    "the", "and", "for", "with", "that", "this", "from", "into", "add",
    "create", "support", "improve", "update", "atualizar",
}


def extract_keywords(text: str) -> set[str]:
    """Extrai conjunto de tokens normalizados em minúsculas com 3 ou mais caracteres, sem stop words.

    Args:
        text: Texto de entrada para extração de palavras-chave.

    Returns:
        Conjunto de tokens em minúsculas sem palavras vazias.
    """
    tokens = {match.group(0).lower() for match in TOKEN_REGEX.finditer(text)}
    filtered = {t for t in tokens if t not in STOP_WORDS}
    return filtered or tokens


def compute_token_overlap(query_tokens: set[str], target_tokens: set[str]) -> float:
    """Calcula o índice de sobreposição de tokens entre a consulta e o texto alvo.

    Args:
        query_tokens: Conjunto de tokens da consulta do operador.
        target_tokens: Conjunto de tokens do documento inspecionado.

    Returns:
        Score fracionário de sobreposição entre 0.0 e 1.0.
    """
    if not query_tokens or not target_tokens:
        return 0.0
    intersection = query_tokens.intersection(target_tokens)
    return len(intersection) / len(query_tokens)


class SpecDiscoveryEngine:
    """Motor de descoberta prévia de especificações existentes durante o comando plan."""

    def __init__(self, specs_dir: Path) -> None:
        """Inicializa o motor com o diretório de especificações alvo.

        Args:
            specs_dir: Caminho para o diretório de especificações (ex: spec-hub/specs).
        """
        self.specs_dir = specs_dir

    def discover_related_specs(
        self,
        query_title_or_prompt: str,
        target_capability: str | None = None,
        threshold: float = 0.6,
    ) -> list[SpecMatch]:
        """Inspeciona o repositório de specs e avalia correlação semântica e estrutural.

        Args:
            query_title_or_prompt: Título proposto ou instrução informada no plan.
            target_capability: Identificador opcional da Business Capability alvo.
            threshold: Limiar mínimo de corte para considerar correspondência relevante.

        Returns:
            Lista de instâncias de SpecMatch ordenadas da maior para a menor similaridade.
        """
        if not self.specs_dir.is_dir() or not query_title_or_prompt.strip():
            return []

        query_tokens = extract_keywords(query_title_or_prompt)
        query_lower = query_title_or_prompt.lower()
        matches: list[SpecMatch] = []

        for spec_file in sorted(self.specs_dir.iterdir()):
            if not spec_file.is_file() or not spec_file.name.endswith(".md"):
                continue
            if spec_file.name == "SPEC-TEMPLATE.md":
                continue

            match = self._evaluate_spec_file(
                spec_file=spec_file,
                query_lower=query_lower,
                query_tokens=query_tokens,
                target_capability=target_capability,
                threshold=threshold,
            )
            if match is not None:
                matches.append(match)

        matches.sort(key=lambda m: m.similarity_score, reverse=True)
        return matches

    def _evaluate_spec_file(
        self,
        spec_file: Path,
        query_lower: str,
        query_tokens: set[str],
        target_capability: str | None,
        threshold: float,
    ) -> SpecMatch | None:
        """Avalia a similaridade de um arquivo de especificação individual com a consulta.

        Args:
            spec_file: Arquivo Markdown da especificação.
            query_lower: Consulta em minúsculas para correspondência exata de ID.
            query_tokens: Tokens extraídos da consulta.
            target_capability: Business Capability informada ou None.
            threshold: Limiar mínimo de score aceito.

        Returns:
            Instância de SpecMatch se o score atingir o limiar, ou None.
        """
        content = spec_file.read_text(encoding="utf-8")
        frontmatter, body = extract_yaml_frontmatter(content)
        if not frontmatter or not isinstance(frontmatter, dict):
            return None

        spec_id = str(frontmatter.get("spec_id") or "")
        if not spec_id or spec_id == "SPEC-XXX":
            return None

        title = str(frontmatter.get("title") or spec_file.stem)
        capability = str(frontmatter.get("capability") or "")
        bounded_context = str(frontmatter.get("bounded_context") or "")

        score = self._calculate_similarity_score(
            spec_id=spec_id,
            title=title,
            capability=capability,
            bounded_context=bounded_context,
            body=body,
            query_lower=query_lower,
            query_tokens=query_tokens,
            target_capability=target_capability,
        )

        if score < threshold:
            return None

        action = "evolve" if score >= 0.5 else "new_spec"
        summary = f"Correspondência com {spec_id} ({title}) no contexto {bounded_context}"

        return SpecMatch(
            spec_id=spec_id,
            title=title,
            file_path=str(spec_file),
            similarity_score=round(min(score, 1.0), 3),
            matched_capability=capability,
            relevance_summary=summary,
            recommended_action=action,
        )

    def _calculate_similarity_score(
        self,
        spec_id: str,
        title: str,
        capability: str,
        bounded_context: str,
        body: str,
        query_lower: str,
        query_tokens: set[str],
        target_capability: str | None,
    ) -> float:
        """Calcula o score de similaridade ponderado entre campos da spec e a consulta.

        Args:
            spec_id: Identificador da spec (ex: SPEC-008).
            title: Título da especificação.
            capability: Business Capability declarada.
            bounded_context: Bounded context declarado.
            body: Corpo em Markdown da especificação.
            query_lower: String da query em minúsculas.
            query_tokens: Conjunto de tokens da consulta.
            target_capability: Capability alvo informada pelo chamador.

        Returns:
            Valor float ponderado de 0.0 a 1.0.
        """
        if spec_id.lower() in query_lower:
            return 1.0

        title_tokens = extract_keywords(title)
        bc_tokens = extract_keywords(bounded_context)
        body_tokens = extract_keywords(body[:3000])

        all_doc_tokens = title_tokens | bc_tokens | body_tokens
        doc_overlap = compute_token_overlap(query_tokens, all_doc_tokens)
        title_overlap = compute_token_overlap(query_tokens, title_tokens)
        bc_overlap = compute_token_overlap(query_tokens, bc_tokens)

        base_score = (doc_overlap * 0.5) + (title_overlap * 0.3) + (bc_overlap * 0.2)
        relevance_boost = 0.15 if (title_overlap >= 0.5 or bc_overlap >= 0.5) else 0.0

        capability_boost = 0.0
        if target_capability and target_capability.strip().lower() == capability.strip().lower():
            capability_boost = 0.2
        elif capability and compute_token_overlap(query_tokens, extract_keywords(capability)) > 0:
            capability_boost = 0.1

        weighted_score = base_score + relevance_boost + capability_boost
        return min(weighted_score, 1.0)
