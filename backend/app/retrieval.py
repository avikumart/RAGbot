from __future__ import annotations

import math
import re
import logging
from collections import Counter
from dataclasses import dataclass

from .reranker import RerankerService
from .store import Store
from .vector_service import VectorService


STOP_WORDS = {
    "about", "after", "also", "and", "are", "but", "can", "did", "does", "for", "from",
    "had", "has", "have", "her", "here", "him", "his", "how", "into", "its", "more",
    "our", "she", "tell", "than", "that", "the", "their", "them", "there", "these", "they",
    "this", "those", "was", "were", "what", "when", "where", "which", "who", "why", "will",
    "with", "would", "you", "your",
}
PRONOUN_TOKENS = {
    "he", "him", "his", "she", "her", "hers", "they", "them", "their", "theirs",
    "who", "whom", "whose", "it", "its",
}
FOLLOWUP_INDICATORS = {
    "what else", "tell me more", "anything else", "what about", "how about",
    "more details", "what other", "did they", "did he", "did she", "when did",
    "where did", "why did", "how did", "who was", "who is",
}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RankedChunk:
    chunk_id: int
    score: float


def tokenize(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9][a-z0-9'-]+", text.casefold())
        if len(token) > 2 and token not in STOP_WORDS
    ]


def identify_people(
    question: str,
    known_people: list[dict],
    explicit: str | None = None,
    history: list[dict] | None = None,
) -> list[str]:
    """Identifies person names mentioned in the question or prior conversational context."""
    if explicit:
        return [explicit]
    folded_question = question.casefold()
    exact = [person["name"] for person in known_people if person["normalized"] in folded_question]
    if exact:
        return exact

    question_tokens = set(tokenize(question))
    first_name_matches = [
        person["name"] for person in known_people
        if person["name"].split()[0].casefold() in question_tokens
    ]
    first_names = Counter(name.split()[0].casefold() for name in first_name_matches)
    matches = [
        name for name in first_name_matches
        if first_names[name.split()[0].casefold()] == 1
    ]
    if matches:
        return matches

    # Resolve from recent conversational history (most recent first)
    if history:
        for turn in reversed(history):
            content = turn.get("content", "").casefold()
            hist_exact = [
                person["name"] for person in known_people
                if person["normalized"] in content
            ]
            if hist_exact:
                return hist_exact
            hist_tokens = set(tokenize(content))
            hist_fn_matches = [
                person["name"] for person in known_people
                if person["name"].split()[0].casefold() in hist_tokens
            ]
            hist_fn = Counter(name.split()[0].casefold() for name in hist_fn_matches)
            hist_found = [
                name for name in hist_fn_matches
                if hist_fn[name.split()[0].casefold()] == 1
            ]
            if hist_found:
                return hist_found

    return []


def reformulate_query(
    question: str,
    history: list[dict] | None = None,
    known_people: list[dict] | None = None,
    explicit_person: str | None = None,
) -> tuple[str, list[str]]:
    """Synthesizes a standalone retrieval query and identifies contextually active people."""
    people = identify_people(
        question, known_people or [], explicit=explicit_person, history=history
    )

    if not history:
        return question, people

    folded_question = question.casefold()
    tokens = set(tokenize(question))

    has_pronoun = bool(tokens & PRONOUN_TOKENS)
    has_followup = any(phrase in folded_question for phrase in FOLLOWUP_INDICATORS)
    person_in_question = any(p.casefold() in folded_question for p in people)

    needs_reformulation = has_pronoun or has_followup or (people and not person_in_question)

    if not needs_reformulation:
        return question, people

    subject_prefix = " ".join(people) if people else ""
    context_keywords: list[str] = []
    if len(tokens) <= 3:
        for turn in reversed(history):
            if turn.get("role") == "user":
                prior_tokens = [
                    t for t in tokenize(turn.get("content", ""))
                    if t not in PRONOUN_TOKENS and t not in STOP_WORDS
                ]
                context_keywords = prior_tokens[:3]
                break

    context_str = " ".join(dict.fromkeys([subject_prefix, *context_keywords]).keys()).strip()
    if context_str:
        standalone = f"{context_str} {question}".strip()
        return standalone, people

    return question, people


def lexical_candidates(
    chunks: list[dict],
    question: str,
    people: list[str],
    limit: int,
    store: Store | None = None,
    document_ids: list[str] | None = None,
) -> list[RankedChunk]:
    if not chunks:
        return []

    if store is not None and getattr(store, "database_component", "") == "sqlite":
        fts_hits = store.search_fts(question + " " + " ".join(people), document_ids=document_ids, limit=limit)
        if fts_hits:
            chunk_by_id = {int(c["id"]): c for c in chunks}
            scored: list[RankedChunk] = []
            for item in fts_hits:
                cid = item["chunk_id"]
                if cid not in chunk_by_id:
                    continue
                score = item["score"]
                folded_content = chunk_by_id[cid]["content"].casefold()
                for person in people:
                    if person.casefold() in folded_content:
                        score += 4.0
                    elif person.split()[0].casefold() in folded_content:
                        score += 1.0
                scored.append(RankedChunk(cid, score))
            if scored:
                return sorted(scored, key=lambda item: (-item.score, item.chunk_id))[:limit]

    query_terms = tokenize(question + " " + " ".join(people))
    document_frequency: Counter[str] = Counter()
    tokenized_chunks: list[list[str]] = []
    for chunk in chunks:
        tokens = tokenize(chunk["content"])
        tokenized_chunks.append(tokens)
        document_frequency.update(set(tokens))

    average_length = sum(map(len, tokenized_chunks)) / max(len(tokenized_chunks), 1)
    scored: list[RankedChunk] = []
    for chunk, tokens in zip(chunks, tokenized_chunks, strict=True):
        frequencies = Counter(tokens)
        score = 0.0
        for term in set(query_terms):
            frequency = frequencies[term]
            if not frequency:
                continue
            inverse_frequency = math.log(
                1 + (len(chunks) - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5)
            )
            denominator = frequency + 1.2 * (0.25 + 0.75 * len(tokens) / max(average_length, 1))
            score += inverse_frequency * ((frequency * 2.2) / denominator)

        folded_content = chunk["content"].casefold()
        for person in people:
            if person.casefold() in folded_content:
                score += 4.0
            elif person.split()[0].casefold() in folded_content:
                score += 1.0
        if score > 0:
            scored.append(RankedChunk(int(chunk["id"]), score))
    return sorted(scored, key=lambda item: (-item.score, item.chunk_id))[:limit]


def reciprocal_rank_fusion(
    lexical: list[RankedChunk], vector: list[RankedChunk], rank_constant: int = 60
) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in (lexical, vector):
        for rank, candidate in enumerate(ranking, start=1):
            fused[candidate.chunk_id] = fused.get(candidate.chunk_id, 0.0) + 1.0 / (
                rank_constant + rank
            )
    return fused


def hybrid_retrieve(
    store: Store,
    question: str,
    document_ids: list[str] | None,
    explicit_person: str | None,
    top_k: int,
    vector_service: VectorService | None = None,
    lexical_limit: int = 20,
    vector_limit: int = 20,
    reranker: RerankerService | None = None,
    history: list[dict] | None = None,
) -> tuple[list[str], list[dict], str]:
    chunks = store.get_chunks(document_ids)
    known_people = store.list_people(document_ids)
    standalone_query, people = reformulate_query(
        question, history=history, known_people=known_people, explicit_person=explicit_person
    )
    if not chunks:
        return people, [], "lexical"

    lexical = lexical_candidates(
        chunks, standalone_query, people, lexical_limit, store=store, document_ids=document_ids
    )
    vector: list[RankedChunk] = []
    retrieval_mode = "lexical"
    if vector_service and vector_service.enabled:
        try:
            raw_vector = vector_service.search(standalone_query, document_ids, vector_limit)
            # Qdrant is derived state: only candidates still present in scoped PostgreSQL
            # rows are eligible for answers and citations.
            valid = {
                int(chunk["id"]): chunk
                for chunk in store.get_chunks_by_ids(
                    [candidate.chunk_id for candidate in raw_vector], document_ids
                )
            }
            vector = [
                RankedChunk(candidate.chunk_id, candidate.score)
                for candidate in raw_vector
                if candidate.chunk_id in valid
                and valid[candidate.chunk_id]["document_id"] == candidate.document_id
            ]
            retrieval_mode = "hybrid"
        except Exception as exc:
            retrieval_mode = "lexical-fallback"
            logger.warning("Vector retrieval unavailable; using lexical retrieval: %s", exc)

    fused = reciprocal_rank_fusion(lexical, vector)
    chunk_by_id = {int(chunk["id"]): chunk for chunk in chunks}
    for chunk_id in list(fused):
        content = chunk_by_id.get(chunk_id, {}).get("content", "").casefold()
        for person in people:
            if person.casefold() in content:
                fused[chunk_id] += 0.04
            elif person.split()[0].casefold() in content:
                fused[chunk_id] += 0.01

    fused_candidates = sorted(
        ((score, chunk_by_id[chunk_id]) for chunk_id, score in fused.items() if chunk_id in chunk_by_id),
        key=lambda item: (-item[0], int(item[1]["id"])),
    )
    if reranker is not None:
        fused_candidates = reranker.rerank(standalone_query, fused_candidates)
    chosen = fused_candidates[:top_k]
    if not chosen:
        return people, [], retrieval_mode
    maximum = chosen[0][0]
    sources = [
        {
            "index": index,
            "document_id": chunk["document_id"],
            "filename": chunk["filename"],
            "page": chunk["page"],
            "excerpt": chunk["content"][:560],
            "score": round(score / maximum, 3),
        }
        for index, (score, chunk) in enumerate(chosen, start=1)
    ]
    return people, sources, retrieval_mode


def retrieve(
    store: Store,
    question: str,
    document_ids: list[str] | None,
    explicit_person: str | None,
    top_k: int,
) -> tuple[list[str], list[dict]]:
    """Backward-compatible lexical-only entry point."""
    people, sources, _ = hybrid_retrieve(
        store, question, document_ids, explicit_person, top_k
    )
    return people, sources


def _best_sentence(excerpt: str, query_terms: set[str], people: list[str]) -> str:
    sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", excerpt) if sentence.strip()]
    if not sentences:
        return excerpt.strip()

    def rank(sentence: str) -> tuple[int, int]:
        folded = sentence.casefold()
        person_hits = sum(1 for person in people if person.casefold() in folded)
        overlap = len(query_terms & set(tokenize(sentence)))
        return person_hits, overlap

    return max(sentences, key=rank)


def synthesize_answer(question: str, people: list[str], sources: list[dict]) -> str:
    if not sources:
        person_phrase = f" about {', '.join(people)}" if people else ""
        return (
            f"I couldn’t find grounded evidence{person_phrase} in the selected documents. "
            "Try another name, include more context, or search across all documents."
        )

    query_terms = set(tokenize(question))
    claims: list[str] = []
    seen: set[str] = set()
    for source in sources:
        sentence = _best_sentence(source["excerpt"], query_terms, people)
        key = sentence.casefold()
        if key in seen:
            continue
        seen.add(key)
        claims.append(f"{sentence} [{source['index']}]")
        if len(claims) == 3:
            break

    subject = ", ".join(people) if people else "the people in your documents"
    if len(claims) == 1:
        return f"Here’s what I found about {subject}:\n\n{claims[0]}"
    bullets = "\n".join(f"- {claim}" for claim in claims)
    return f"Here’s what I found about {subject}:\n\n{bullets}"
