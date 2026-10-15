from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any, Iterable

from fastapi import HTTPException

from .config import Settings
from .entity_resolution import get_person_aliases
from .llm import LLMService, SYSTEM_PROMPT, format_source_context
from .reranker import RerankerService
from .retrieval import STOP_WORDS, tokenize
from .store import Store
from .vector_service import VectorService

logger = logging.getLogger(__name__)

BIOGRAPHY_TERMS = {
    "title", "role", "position", "career", "education", "tenure", "background",
    "joined", "graduated", "university", "college", "school", "degree", "phd",
    "architect", "engineer", "manager", "director", "founder", "founded",
    "ceo", "cto", "vp", "lead", "head", "appointed", "promoted", "served",
}

RELATIONSHIP_TERMS = {
    "reports", "reporting", "manager", "collaborator", "collaborates", "collaborated",
    "team", "colleague", "colleagues", "partner", "partners", "works", "worked",
    "working", "oversees", "managed", "advises", "advised", "direct", "peer",
}

PROJECT_TERMS = {
    "project", "initiative", "accomplishment", "milestone", "deliverable",
    "outcome", "launched", "launched in", "developed", "built", "shipped",
    "delivered", "designed", "created", "spearheaded", "led", "achievement",
    "release", "platform", "system",
}

QUOTE_VERBS = {
    "said", "stated", "quoted", "remarked", "noted", "expressed", "emphasized",
    "observed", "argued", "maintained", "believes", "believed", "advocates",
    "advocated", "wrote", "commented", "concluded", "pointed", "suggested",
}


def _split_sentences(text: str) -> list[str]:
    """Splits text into clean, non-trivial sentences."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return [s for s in sentences if len(s) >= 12]


class DossierSourceManager:
    """Manages unique verified sources and assigns monotonic citation indices [1]..[N]."""

    def __init__(self) -> None:
        self.sources: list[dict] = []
        self._chunk_id_to_index: dict[int, int] = {}

    def get_or_add_source(self, chunk: dict, score: float = 1.0) -> int:
        chunk_id = int(chunk["id"])
        if chunk_id in self._chunk_id_to_index:
            return self._chunk_id_to_index[chunk_id]

        index = len(self.sources) + 1
        self._chunk_id_to_index[chunk_id] = index
        self.sources.append({
            "index": index,
            "id": chunk_id,
            "document_id": chunk["document_id"],
            "filename": chunk.get("filename", "document"),
            "page": chunk.get("page"),
            "excerpt": chunk.get("content", "")[:560],
            "score": round(score, 3),
        })
        return index

    def get_source_by_index(self, index: int) -> dict | None:
        if 1 <= index <= len(self.sources):
            return self.sources[index - 1]
        return None


def _rank_chunks_for_query(
    chunks: list[dict],
    target_terms: set[str],
    name_tokens: set[str],
) -> list[tuple[float, dict]]:
    """Ranks chunks based on term overlap and entity prominence."""
    scored: list[tuple[float, dict]] = []
    for chunk in chunks:
        content_lower = chunk["content"].casefold()
        chunk_tokens = set(tokenize(content_lower))

        # Check entity presence
        name_hits = sum(1 for tok in name_tokens if tok in content_lower)
        term_hits = len(target_terms & chunk_tokens)

        if name_hits == 0 and term_hits == 0:
            continue

        score = (name_hits * 2.0) + (term_hits * 1.0)
        scored.append((score, chunk))

    scored.sort(key=lambda item: (-item[0], int(item[1]["id"])))
    return scored


def _synthesize_biography(
    name: str,
    names_to_match: set[str],
    ranked_chunks: list[tuple[float, dict]],
    timeline_events: list[dict],
    source_mgr: DossierSourceManager,
) -> tuple[str, list[int]]:
    claims: list[str] = []
    citations: list[int] = []
    seen_texts: set[str] = set()

    # 1. Timeline education & joining events
    for ev in timeline_events:
        txt = ev["event_text"]
        txt_lower = txt.casefold()
        if any(term in txt_lower for term in ("graduated", "joined", "architect", "engineer", "director", "founded", "role", "title", "promoted", "served")):
            if ev.get("source_chunk"):
                idx = source_mgr.get_or_add_source(ev["source_chunk"])
                date_str = f" in {ev['event_date']}" if ev.get("event_date") and ev["event_date"] not in txt else ""
                claim = f"{txt}{date_str} [{idx}]."
                key = claim.casefold()
                if key not in seen_texts:
                    seen_texts.add(key)
                    claims.append(claim)
                    if idx not in citations:
                        citations.append(idx)

    # 2. Extract from ranked chunks
    for _, chunk in ranked_chunks:
        sentences = _split_sentences(chunk["content"])
        for s in sentences:
            s_lower = s.casefold()
            if any(name_variant in s_lower for name_variant in names_to_match):
                if any(term in s_lower for term in BIOGRAPHY_TERMS):
                    key = s_lower[:60]
                    if key not in seen_texts:
                        seen_texts.add(key)
                        idx = source_mgr.get_or_add_source(chunk)
                        # Ensure trailing period
                        clean_s = s.rstrip(".!?")
                        claim = f"{clean_s} [{idx}]."
                        claims.append(claim)
                        if idx not in citations:
                            citations.append(idx)
            if len(claims) >= 3:
                break
        if len(claims) >= 3:
            break

    if not claims:
        # Fallback: general introductory sentence from top chunk
        if ranked_chunks:
            top_chunk = ranked_chunks[0][1]
            sentences = _split_sentences(top_chunk["content"])
            for s in sentences:
                if any(name_variant in s.casefold() for name_variant in names_to_match):
                    idx = source_mgr.get_or_add_source(top_chunk)
                    claim = f"{s.rstrip('.!?')} [{idx}]."
                    claims.append(claim)
                    citations.append(idx)
                    break

    if not claims:
        return f"No documented biographical or role information was recorded for {name} in the selected documents.", []

    content = "\n".join(f"- {c}" for c in claims)
    return content, citations


def _synthesize_relationships(
    name: str,
    names_to_match: set[str],
    graph_edges: list[dict],
    ranked_chunks: list[tuple[float, dict]],
    chunks_by_id: dict[int, dict],
    source_mgr: DossierSourceManager,
) -> tuple[str, list[int]]:
    claims: list[str] = []
    citations: list[int] = []
    seen_texts: set[str] = set()

    # 1. Use verified relationship triples from the entity graph
    for edge in graph_edges:
        s_ent = edge.get("source") or edge.get("source_entity")
        rel = edge.get("relation") or "connected with"
        t_ent = edge.get("target") or edge.get("target_entity")
        if not s_ent or not t_ent:
            continue
        raw_chunk_id = edge.get("chunk_id")
        try:
            chunk_id = int(raw_chunk_id) if raw_chunk_id is not None else None
        except (ValueError, TypeError):
            chunk_id = None
        chunk = chunks_by_id.get(chunk_id) if chunk_id is not None else None
        if chunk:
            idx = source_mgr.get_or_add_source(chunk)
            claim = f"{s_ent} {rel} {t_ent} [{idx}]."
            key = f"{s_ent}:{rel}:{t_ent}".casefold()
            if key not in seen_texts:
                seen_texts.add(key)
                claims.append(claim)
                if idx not in citations:
                    citations.append(idx)
        if len(claims) >= 4:
            break

    # 2. Extract relationship sentences from chunks
    if len(claims) < 4:
        for _, chunk in ranked_chunks:
            sentences = _split_sentences(chunk["content"])
            for s in sentences:
                s_lower = s.casefold()
                if any(name_variant in s_lower for name_variant in names_to_match):
                    if any(term in s_lower for term in RELATIONSHIP_TERMS):
                        key = s_lower[:60]
                        if key not in seen_texts:
                            seen_texts.add(key)
                            idx = source_mgr.get_or_add_source(chunk)
                            claim = f"{s.rstrip('.!?')} [{idx}]."
                            claims.append(claim)
                            if idx not in citations:
                                citations.append(idx)
                if len(claims) >= 4:
                    break
            if len(claims) >= 4:
                break

    if not claims:
        return f"No documented direct reporting lines or collaborative relationships were found for {name} in the selected scope.", []

    content = "\n".join(f"- {c}" for c in claims)
    return content, citations


def _synthesize_projects(
    name: str,
    names_to_match: set[str],
    timeline_events: list[dict],
    ranked_chunks: list[tuple[float, dict]],
    source_mgr: DossierSourceManager,
) -> tuple[str, list[int]]:
    claims: list[str] = []
    citations: list[int] = []
    seen_texts: set[str] = set()

    # 1. Timeline events representing achievements / milestones
    for ev in timeline_events:
        txt = ev["event_text"]
        txt_lower = txt.casefold()
        if any(term in txt_lower for term in ("launched", "project", "initiative", "deliverable", "milestone", "outcome", "developed", "built", "shipped", "quantum", "system")):
            if ev.get("source_chunk"):
                idx = source_mgr.get_or_add_source(ev["source_chunk"])
                date_str = f" in {ev['event_date']}" if ev.get("event_date") and ev["event_date"] not in txt else ""
                claim = f"{txt}{date_str} [{idx}]."
                key = claim.casefold()
                if key not in seen_texts:
                    seen_texts.add(key)
                    claims.append(claim)
                    if idx not in citations:
                        citations.append(idx)

    # 2. Ranked project chunks
    for _, chunk in ranked_chunks:
        sentences = _split_sentences(chunk["content"])
        for s in sentences:
            s_lower = s.casefold()
            if any(name_variant in s_lower for name_variant in names_to_match):
                if any(term in s_lower for term in PROJECT_TERMS):
                    key = s_lower[:60]
                    if key not in seen_texts:
                        seen_texts.add(key)
                        idx = source_mgr.get_or_add_source(chunk)
                        claim = f"{s.rstrip('.!?')} [{idx}]."
                        claims.append(claim)
                        if idx not in citations:
                            citations.append(idx)
            if len(claims) >= 4:
                break
        if len(claims) >= 4:
            break

    if not claims:
        return f"No documented project milestones or major deliverables were identified for {name} in the selected scope.", []

    content = "\n".join(f"- {c}" for c in claims)
    return content, citations


def _synthesize_quotes(
    name: str,
    names_to_match: set[str],
    ranked_chunks: list[tuple[float, dict]],
    all_person_chunks: list[dict],
    source_mgr: DossierSourceManager,
) -> tuple[str, list[int]]:
    claims: list[str] = []
    citations: list[int] = []
    seen_texts: set[str] = set()

    # Regex patterns for quotes:
    # 1. Quoted text followed or preceded by attribution to the person
    quote_pattern = re.compile(r'["“]([^"”]+)["”]', re.DOTALL)

    for chunk in all_person_chunks:
        content = chunk["content"]
        sentences = _split_sentences(content)
        for s in sentences:
            s_lower = s.casefold()
            if not any(name_variant in s_lower for name_variant in names_to_match):
                continue

            # Check if there are quotation marks
            quotes = quote_pattern.findall(s)
            if quotes:
                for q in quotes:
                    clean_q = q.strip()
                    if len(clean_q) >= 10:
                        key = clean_q.casefold()
                        if key not in seen_texts:
                            seen_texts.add(key)
                            idx = source_mgr.get_or_add_source(chunk)
                            claim = f'"{clean_q}" [{idx}].'
                            claims.append(claim)
                            if idx not in citations:
                                citations.append(idx)
                            break
            elif any(verb in s_lower for verb in QUOTE_VERBS):
                # Statement with attribution verb
                key = s_lower[:60]
                if key not in seen_texts:
                    seen_texts.add(key)
                    idx = source_mgr.get_or_add_source(chunk)
                    claim = f"{s.rstrip('.!?')} [{idx}]."
                    claims.append(claim)
                    if idx not in citations:
                        citations.append(idx)

            if len(claims) >= 3:
                break
        if len(claims) >= 3:
            break

    if not claims:
        return f"No direct statements, recorded quotations, or stated viewpoints were identified for {name} in the selected scope.", []

    content = "\n".join(f"- {c}" for c in claims)
    return content, citations


def _generate_executive_summary(
    name: str,
    sections: list[dict],
    source_mgr: DossierSourceManager,
) -> str:
    """Generates a cohesive, fully cited executive summary paragraph from the section claims."""
    summary_sentences: list[str] = []

    for sec in sections:
        content = sec.get("content", "")
        # Find first bullet point or claim
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("- "):
                claim = line[2:].strip()
                summary_sentences.append(claim)
                break
        if len(summary_sentences) >= 3:
            break

    if not summary_sentences:
        return f"Executive briefing on {name} based on verified document intelligence."

    return " ".join(summary_sentences)


def generate_persona_dossier(
    name: str,
    store: Store,
    settings: Settings,
    vectors: VectorService | None = None,
    reranker: RerankerService | None = None,
    llm: LLMService | None = None,
    document_ids: Iterable[str] | None = None,
    owner_id: str | None = None,
) -> dict[str, Any]:
    """Generates an autonomous, multi-step executive briefing dossier on an entity."""
    doc_scope = list(document_ids or [])

    # 1. Fetch all people in scope for alias resolution
    all_people = store.list_people(document_ids=doc_scope or None, owner_id=owner_id)
    canonical_name = name
    matched_person: dict | None = None
    for p in all_people:
        p_name = p["name"]
        p_aliases = p.get("aliases", []) or get_person_aliases(p_name, all_people)
        if p_name.casefold() == name.casefold() or any(a.casefold() == name.casefold() for a in p_aliases):
            canonical_name = p_name
            matched_person = p
            break

    if not matched_person:
        for p in all_people:
            p_name = p["name"]
            parts = [part.casefold() for part in p_name.split() if part]
            if name.casefold() in parts:
                canonical_name = p_name
                matched_person = p
                break

    aliases = get_person_aliases(canonical_name, all_people)
    names_to_match = {canonical_name.casefold(), name.casefold(), *[a.casefold() for a in aliases]}
    name_tokens = {tok for n in names_to_match for tok in tokenize(n)}

    # 2. Retrieve all scoped chunks for this owner
    all_chunks = store.get_chunks(document_ids=doc_scope or None, owner_id=owner_id)
    if not all_chunks:
        raise HTTPException(
            status_code=404,
            detail=f"Persona '{name}' not found in the selected scope.",
        )

    chunks_by_id = {int(c["id"]): c for c in all_chunks}

    # Filter chunks that mention the entity or aliases
    person_chunks: list[dict] = []
    for chunk in all_chunks:
        content_lower = chunk["content"].casefold()
        chunk_people = [p.casefold() for p in chunk.get("people", [])]
        if (
            any(name_variant in chunk_people for name_variant in names_to_match)
            or any(name_variant in content_lower for name_variant in names_to_match)
        ):
            person_chunks.append(chunk)

    if not person_chunks:
        # If no chunks explicitly match, check if matched_person exists
        if not matched_person:
            raise HTTPException(
                status_code=404,
                detail=f"Persona '{name}' not found in the selected scope.",
            )
        # Use top chunks as candidate scope
        person_chunks = all_chunks[:5]

    # 3. Retrieve Graph and Timeline signals
    graph_data = store.get_graph(document_ids=doc_scope or None, owner_id=owner_id, person=canonical_name)
    graph_edges = graph_data.get("edges", [])

    timeline_events = store.get_person_timeline(canonical_name, document_ids=doc_scope or None, owner_id=owner_id)

    # 4. Multi-step Research Plan: Rank chunks for each structured sub-query
    bio_ranked = _rank_chunks_for_query(person_chunks, BIOGRAPHY_TERMS, name_tokens)
    rel_ranked = _rank_chunks_for_query(person_chunks, RELATIONSHIP_TERMS, name_tokens)
    proj_ranked = _rank_chunks_for_query(person_chunks, PROJECT_TERMS, name_tokens)
    quote_ranked = _rank_chunks_for_query(person_chunks, QUOTE_VERBS, name_tokens)

    # 5. Autonomous Grounded Synthesis
    source_mgr = DossierSourceManager()

    bio_content, bio_citations = _synthesize_biography(
        canonical_name, names_to_match, bio_ranked, timeline_events, source_mgr
    )
    rel_content, rel_citations = _synthesize_relationships(
        canonical_name, names_to_match, graph_edges, rel_ranked, chunks_by_id, source_mgr
    )
    proj_content, proj_citations = _synthesize_projects(
        canonical_name, names_to_match, timeline_events, proj_ranked, source_mgr
    )
    quote_content, quote_citations = _synthesize_quotes(
        canonical_name, names_to_match, quote_ranked, person_chunks, source_mgr
    )

    sections = [
        {
            "id": "biography",
            "title": "Biography & Current Roles",
            "content": bio_content,
            "citations": bio_citations,
            "excerpt_ids": [source_mgr.get_source_by_index(i)["id"] for i in bio_citations if source_mgr.get_source_by_index(i)],
        },
        {
            "id": "relationships",
            "title": "Key Relationships & Network",
            "content": rel_content,
            "citations": rel_citations,
            "excerpt_ids": [source_mgr.get_source_by_index(i)["id"] for i in rel_citations if source_mgr.get_source_by_index(i)],
        },
        {
            "id": "projects",
            "title": "Projects & Key Accomplishments",
            "content": proj_content,
            "citations": proj_citations,
            "excerpt_ids": [source_mgr.get_source_by_index(i)["id"] for i in proj_citations if source_mgr.get_source_by_index(i)],
        },
        {
            "id": "quotes",
            "title": "Direct Statements & Positions",
            "content": quote_content,
            "citations": quote_citations,
            "excerpt_ids": [source_mgr.get_source_by_index(i)["id"] for i in quote_citations if source_mgr.get_source_by_index(i)],
        },
    ]

    executive_summary = _generate_executive_summary(canonical_name, sections, source_mgr)

    # 6. Format Markdown Report
    generated_at_iso = datetime.now(UTC).isoformat()
    generated_at_display = datetime.now(UTC).strftime("%B %d, %Y at %H:%M UTC")

    scope_summary = f"{len(doc_scope)} documents" if doc_scope else "Entire Document Library"

    sources_list_md = []
    for src in source_mgr.sources:
        page_str = f", page {src['page']}" if src.get("page") else ""
        snippet = src["excerpt"][:180].replace("\n", " ").strip()
        sources_list_md.append(
            f"- [{src['index']}] **{src['filename']}**{page_str} (Excerpt ID: `{src['id']}`): \"{snippet}…\""
        )
    sources_formatted_md = "\n".join(sources_list_md) if sources_list_md else "No sources cited."

    markdown = f"""# Executive Briefing: {canonical_name}

**Generated**: {generated_at_display}  
**Scope**: {scope_summary}  
**Citation Provenance**: 100% Grounded across {len(source_mgr.sources)} verified document excerpts

## Executive Summary
{executive_summary}

## 1. Biography & Current Roles
{bio_content}

## 2. Key Relationships & Network
{rel_content}

## 3. Projects & Key Accomplishments
{proj_content}

## 4. Direct Statements & Positions
{quote_content}

---

### Verified Document Sources
{sources_formatted_md}
"""

    return {
        "entity_name": canonical_name,
        "generated_at": generated_at_iso,
        "scope": {
            "document_ids": doc_scope,
            "summary": scope_summary,
        },
        "executive_summary": executive_summary,
        "sections": sections,
        "sources": source_mgr.sources,
        "markdown": markdown,
    }
