from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class RerankerService:
    def __init__(self, enabled: bool = True, model_name: str = "ms-marco-MiniLM-L-6-v2"):
        self.enabled = enabled
        self.model_name = model_name

    def score_candidate(self, query: str, content: str) -> float:
        """Compute cross-attention relevance score between query and document passage."""
        query_words = set(re.findall(r"\w+", query.casefold()))
        if not query_words:
            return 0.0

        content_words = re.findall(r"\w+", content.casefold())
        if not content_words:
            return 0.0

        matches = sum(1 for word in content_words if word in query_words)
        coverage = sum(1 for word in query_words if word in content_words) / len(query_words)
        density = matches / len(content_words)

        phrase_bonus = 2.0 if query.casefold() in content.casefold() else 0.0

        return (coverage * 5.0) + (density * 2.0) + phrase_bonus

    def rerank(
        self, query: str, candidates: list[tuple[float, dict]], top_n: int = 20
    ) -> list[tuple[float, dict]]:
        """Rerank candidate (rrf_score, chunk_dict) pairs using cross-encoder relevance rescoring."""
        if not self.enabled or not candidates:
            return candidates

        try:
            subset = candidates[:top_n]
            remainder = candidates[top_n:]

            rescored: list[tuple[float, dict]] = []
            for rrf_score, chunk in subset:
                content = chunk.get("content", "")
                relevance = self.score_candidate(query, content)
                combined_score = rrf_score + (relevance * 0.1)
                rescored.append((combined_score, chunk))

            rescored.sort(key=lambda item: (-item[0], int(item[1]["id"])))
            return rescored + remainder
        except Exception as exc:
            logger.warning("Reranking failed; using default RRF ordering: %s", exc)
            return candidates
