from __future__ import annotations

import math
import re
import logging
from collections import Counter
from dataclasses import dataclass

from .entity_resolution import get_person_aliases, resolve_query_entities
from .reranker import RerankerService
from .store import Store
from .vector_service import VectorService


def format_graph_context(edges: list[dict]) -> str:
    """Format the extracted relationship subgraph into structured context:
    [Entity A] --(relation)--> [Entity B]
    """
    if not edges:
        return ""
    lines = []
    seen = set()
    for edge in edges:
        s = edge["source_entity"]
        r = edge["relation"]
        t = edge["target_entity"]
        line = f"[{s}] --({r})--> [{t}]"
        if line not in seen:
            seen.add(line)
            lines.append(line)
    return "\n".join(lines)


class RetrievalResult(tuple):
    """3-tuple of (people, sources, retrieval_mode) with accessible .graph_context attribute."""

    def __new__(
        cls,
        people: list[str],
        sources: list[dict],
        retrieval_mode: str,
        graph_context: str = "",
    ):
        return super().__new__(cls, (people, sources, retrieval_mode))

    def __init__(
        self,
        people: list[str],
        sources: list[dict],
        retrieval_mode: str,
        graph_context: str = "",
    ):
        self.people = people
        self.sources = sources
        self.retrieval_mode = retrieval_mode
        self.graph_context = graph_context


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
        aliases = get_person_aliases(explicit, known_people)
        return list(dict.fromkeys([explicit, *aliases]))

    folded_question = question.casefold()
    matched_people: list[str] = []
    for person in known_people:
        p_name = person["name"].casefold()
        p_norm = person.get("normalized", "").casefold()
        aliases = [a.casefold() for a in person.get("aliases", [])]
        if p_norm in folded_question or p_name in folded_question or any(a in folded_question for a in aliases):
            matched_people.extend([person["name"], *person.get("aliases", [])])

    if matched_people:
        return list(dict.fromkeys(matched_people))

    question_tokens = set(tokenize(question))
    first_name_matches = []
    for person in known_people:
        firsts = {person["name"].split()[0].casefold()}
        for a in person.get("aliases", []):
            firsts.add(a.split()[0].casefold())
        if firsts & question_tokens:
            first_name_matches.append(person)

    if len(first_name_matches) == 1:
        p = first_name_matches[0]
        return list(dict.fromkeys([p["name"], *p.get("aliases", [])]))

    # Resolve from recent conversational history (most recent first)
    if history:
        for turn in reversed(history):
            content = turn.get("content", "").casefold()
            hist_matches: list[str] = []
            for person in known_people:
                p_name = person["name"].casefold()
                p_norm = person.get("normalized", "").casefold()
                aliases = [a.casefold() for a in person.get("aliases", [])]
                if p_norm in content or p_name in content or any(a in content for a in aliases):
                    hist_matches.extend([person["name"], *person.get("aliases", [])])
            if hist_matches:
                return list(dict.fromkeys(hist_matches))

            hist_tokens = set(tokenize(content))
            hist_fn_matches = []
            for person in known_people:
                firsts = {person["name"].split()[0].casefold()}
                for a in person.get("aliases", []):
                    firsts.add(a.split()[0].casefold())
                if firsts & hist_tokens:
                    hist_fn_matches.append(person)
            if len(hist_fn_matches) == 1:
                p = hist_fn_matches[0]
                return list(dict.fromkeys([p["name"], *p.get("aliases", [])]))

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

    subject_prefix = people[0] if people else ""
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
    owner_id: str | None = None,
) -> list[RankedChunk]:
    if not chunks:
        return []

    if store is not None and getattr(store, "database_component", "") == "sqlite":
        fts_hits = store.search_fts(
            question + " " + " ".join(people),
            document_ids=document_ids,
            limit=limit,
            owner_id=owner_id,
        )
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
    owner_id: str | None = None,
    graphrag_enabled: bool = True,
    graphrag_depth: int = 2,
    return_graph_context: bool = False,
) -> tuple[list[str], list[dict], str] | tuple[list[str], list[dict], str, str]:
    chunks = store.get_chunks(document_ids, owner_id=owner_id)
    known_people = store.list_people(document_ids, owner_id=owner_id)
    standalone_query, people = reformulate_query(
        question, history=history, known_people=known_people, explicit_person=explicit_person
    )
    if not chunks:
        res = RetrievalResult(people, [], "lexical", graph_context="")
        return (people, [], "lexical", "") if return_graph_context else res

    # GraphRAG multi-hop neighborhood expansion & bridging node extraction
    graph_context = ""
    bridging_nodes: list[str] = []
    bridging_chunk_ids: set[int] = set()
    target_entities: list[str] = []

    if graphrag_enabled and store is not None:
        try:
            scoped_entities = store.get_scoped_entities(document_ids, owner_id=owner_id)
            target_entities = resolve_query_entities(
                standalone_query, known_entities=scoped_entities, known_people=known_people
            )
            seeds = target_entities or people
            if seeds:
                subgraph = store.traverse_subgraph(
                    seed_entities=seeds,
                    document_ids=document_ids,
                    owner_id=owner_id,
                    max_depth=graphrag_depth,
                )
                edges = subgraph.get("edges", [])
                bridging_nodes = subgraph.get("bridging_nodes", [])
                bridging_chunk_ids = set(subgraph.get("bridging_chunk_ids", []))
                graph_context = format_graph_context(edges)
        except Exception as exc:
            logger.warning("GraphRAG traversal failed: %s", exc)

    lexical = lexical_candidates(
        chunks,
        standalone_query,
        people,
        lexical_limit,
        store=store,
        document_ids=document_ids,
        owner_id=owner_id,
    )
    vector: list[RankedChunk] = []
    retrieval_mode = "lexical"
    if vector_service and vector_service.enabled:
        try:
            raw_vector = vector_service.search(
                standalone_query, document_ids, vector_limit, owner_id=owner_id
            )
            # Qdrant is derived state: only candidates still present in scoped PostgreSQL
            # rows are eligible for answers and citations.
            valid = {
                int(chunk["id"]): chunk
                for chunk in store.get_chunks_by_ids(
                    [candidate.chunk_id for candidate in raw_vector],
                    document_ids,
                    owner_id=owner_id,
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

    # Relational Chunk Boosting:
    if bridging_nodes:
        for cid in bridging_chunk_ids:
            if cid in chunk_by_id and cid not in fused:
                fused[cid] = 0.02

        for chunk_id in list(fused):
            content = chunk_by_id.get(chunk_id, {}).get("content", "").casefold()
            for person in people:
                if person.casefold() in content:
                    fused[chunk_id] += 0.04
                elif person.split()[0].casefold() in content:
                    fused[chunk_id] += 0.01

            for bridge in bridging_nodes:
                if bridge.casefold() in content:
                    fused[chunk_id] += 0.04
                elif bridge.split()[0].casefold() in content:
                    fused[chunk_id] += 0.01
    else:
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
        res = RetrievalResult(people, [], retrieval_mode, graph_context=graph_context)
        return (people, [], retrieval_mode, graph_context) if return_graph_context else res
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
    res = RetrievalResult(people, sources, retrieval_mode, graph_context=graph_context)
    if return_graph_context:
        return people, sources, retrieval_mode, graph_context
    return res


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


def synthesize_answer(
    question: str,
    people: list[str],
    sources: list[dict],
    graph_context: str | None = None,
) -> str:
    if not sources and not (graph_context and graph_context.strip()):
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
        base_answer = f"Here’s what I found about {subject}:\n\n{claims[0]}"
    elif len(claims) > 1:
        bullets = "\n".join(f"- {claim}" for claim in claims)
        base_answer = f"Here’s what I found about {subject}:\n\n{bullets}"
    else:
        base_answer = f"Here’s what I found about {subject}:"

    if not claims and graph_context and graph_context.strip():
        graph_bullets = "\n".join(f"- {line}" for line in graph_context.strip().splitlines()[:5])
        return f"{base_answer}\n\n{graph_bullets}"

    return base_answer
