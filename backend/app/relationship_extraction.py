from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .entity_resolution import are_names_compatible, parse_name_parts, slugify_name
from .extraction import extract_people


@dataclass(frozen=True)
class ExtractedRelationship:
    source_entity: str
    relation: str
    target_entity: str
    source_type: str = "person"
    target_type: str = "entity"


ORG_INDICATORS = {
    "corp", "corporation", "inc", "incorporated", "llc", "ltd", "limited",
    "labs", "laboratory", "laboratories", "institute", "foundation", "university",
    "college", "technologies", "group", "department", "agency", "ministry",
    "capital", "partners", "systems", "solutions", "association", "hospital", "clinic",
    "team", "board", "committee", "consortium", "alliance", "ventures", "school"
}

ROLE_KEYWORDS = {
    "ceo", "cto", "cfo", "coo", "cio", "cpo", "ciso", "president", "vice president", "vp",
    "director", "head", "lead", "manager", "architect", "engineer", "scientist",
    "researcher", "analyst", "consultant", "specialist", "coordinator", "officer",
    "founder", "co-founder", "partner", "principal", "fellow", "professor", "advisor"
}

ROLE_VERBS = (
    r"(?:is|was|serves as|served as|acting as|acted as|works as|worked as|"
    r"appointed as|was appointed as|promoted to|was promoted to|hired as|was hired as|"
    r"joined as|became)"
)

HIERARCHY_VERBS = [
    ("reports to", "reports to"),
    ("reported to", "reports to"),
    ("reporting to", "reports to"),
    ("manages", "manages"),
    ("managed", "manages"),
    ("managing", "manages"),
    ("supervises", "supervises"),
    ("supervised", "supervises"),
    ("mentors", "mentors"),
    ("mentored", "mentors"),
    ("leads", "leads"),
    ("led", "leads"),
    ("leading", "leads"),
    ("heads", "heads"),
    ("headed", "heads"),
    ("heading", "heads"),
    ("directs", "directs"),
    ("directed", "directs"),
    ("oversees", "oversees"),
    ("oversaw", "oversees"),
    ("overseeing", "oversees"),
]

ACTION_VERBS = [
    ("owns", "owns"),
    ("owned", "owns"),
    ("owning", "owns"),
    ("authored", "authored"),
    ("co-authored", "co-authored"),
    ("wrote", "wrote"),
    ("created", "created"),
    ("founded", "founded"),
    ("co-founded", "co-founded"),
    ("started", "started"),
    ("launched", "launched"),
    ("developed", "developed"),
    ("designed", "designed"),
    ("built", "built"),
    ("architected", "architected"),
    ("delivered", "delivered"),
    ("presented", "presented"),
    ("drove", "drove"),
]

COLLAB_VERBS = [
    ("works with", "works with"),
    ("worked with", "works with"),
    ("working with", "works with"),
    ("collaborates with", "collaborates with"),
    ("collaborated with", "collaborated with"),
    ("collaborating with", "collaborates with"),
    ("partnered with", "partnered with"),
    ("partnering with", "partnered with"),
    ("teamed with", "teamed with"),
    ("co-authored with", "co-authored with"),
    ("assisted", "assisted"),
    ("advises", "advises"),
    ("advised", "advised"),
    ("met with", "met with"),
    ("succeeded", "succeeded"),
    ("replaced", "replaced"),
]


def clean_entity_name(name: str) -> str:
    """Clean entity name by stripping punctuation, articles, and dates."""
    cleaned = name.strip(" .,:;()[]{}'\"“”")
    # Remove leading determiners
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    # Remove trailing date/year indications e.g. "in 2021"
    cleaned = re.sub(r"\s+(?:in|at|on|since|during)\s+(?:\d{4}|Q\d|January|February|March|April|May|June|July|August|September|October|November|December).*$", "", cleaned, flags=re.IGNORECASE)
    # Remove trailing prepositional clauses like "on the migration", "about the project"
    cleaned = re.sub(r"\s+(?:on|about|regarding|over)\s+(?:the\s+|a\s+|an\s+)?[a-zA-Z0-9\s\-_]+$", "", cleaned, flags=re.IGNORECASE)
    # Remove honorific prefix if present
    prefix, core, suffix = parse_name_parts(cleaned)
    if prefix and core:
        cleaned = " ".join(core)
    return cleaned.strip(" .,:;()[]{}'\"“”")


def classify_entity(entity: str, known_people: set[str] | None = None) -> str:
    """Classify an entity into person, organization, role, project, or general entity."""
    clean = clean_entity_name(entity)
    low = clean.lower()
    if known_people:
        if clean in known_people or any(are_names_compatible(clean, p) for p in known_people):
            return "person"

    tokens = low.split()
    if any(tok.rstrip(".,") in ORG_INDICATORS for tok in tokens):
        return "organization"

    if any(rk in low for rk in ROLE_KEYWORDS):
        return "role"

    if any(k in low for k in ("project", "initiative", "system", "architecture", "plan", "program", "tool", "framework")):
        return "project"

    # Check person heuristic if 2-3 capitalized name words
    person_cand = extract_people(clean)
    if person_cand and person_cand[0].lower() == clean.lower():
        return "person"

    return "entity"


def _extract_role_relationships(sentence: str, known_people: set[str]) -> list[ExtractedRelationship]:
    """Extract role / position relationships like 'X was appointed as CTO at Acme'."""
    results: list[ExtractedRelationship] = []
    pattern = re.compile(
        rf"(?P<person>[A-Z][a-zA-Z\s\.\,\-]+?)\s+{ROLE_VERBS}\s+"
        r"(?:the\s+|a\s+|an\s+)?(?P<role>[A-Za-z\s\/\-]+?)\s+(?:at|for|of|in)\s+"
        r"(?P<org>[A-Z][a-zA-Z0-9\s\.\,\-]+?)(?:[\.\,\;\n]|$)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(sentence):
        raw_person = clean_entity_name(match.group("person"))
        raw_role = clean_entity_name(match.group("role"))
        raw_org = clean_entity_name(match.group("org"))

        if not raw_person or not raw_org or not raw_role:
            continue
        if len(raw_person) > 50 or len(raw_org) > 50 or len(raw_role) > 50:
            continue
        if raw_person.lower() == raw_org.lower():
            continue

        p_type = classify_entity(raw_person, known_people)
        o_type = classify_entity(raw_org, known_people)
        if o_type == "person":
            o_type = "organization"

        results.append(
            ExtractedRelationship(
                source_entity=raw_person,
                relation=f"{raw_role} at",
                target_entity=raw_org,
                source_type=p_type,
                target_type=o_type,
            )
        )
    return results


def _extract_hierarchy_relationships(sentence: str, known_people: set[str]) -> list[ExtractedRelationship]:
    """Extract reporting and management hierarchy triples."""
    results: list[ExtractedRelationship] = []
    for verb_phrase, canon_rel in HIERARCHY_VERBS:
        pattern = re.compile(
            rf"(?P<source>[A-Z][a-zA-Z\s\.\,\-]+?)\s+{re.escape(verb_phrase)}\s+"
            r"(?P<target>[A-Za-z0-9\s\.\,\-]+?)(?:[\.\,\;\n]|$)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(sentence):
            raw_source = clean_entity_name(match.group("source"))
            raw_target = clean_entity_name(match.group("target"))

            if not raw_source or not raw_target:
                continue
            if len(raw_source) > 50 or len(raw_target) > 50:
                continue
            if raw_source.lower() == raw_target.lower():
                continue

            s_type = classify_entity(raw_source, known_people)
            t_type = classify_entity(raw_target, known_people)

            results.append(
                ExtractedRelationship(
                    source_entity=raw_source,
                    relation=canon_rel,
                    target_entity=raw_target,
                    source_type=s_type,
                    target_type=t_type,
                )
            )
    return results


def _extract_action_and_collab_relationships(sentence: str, known_people: set[str]) -> list[ExtractedRelationship]:
    """Extract project ownership, authorship, and collaboration triples."""
    results: list[ExtractedRelationship] = []
    # Collaboration
    for verb_phrase, canon_rel in COLLAB_VERBS:
        pattern = re.compile(
            rf"(?P<source>[A-Z][a-zA-Z\s\.\,\-]+?)\s+{re.escape(verb_phrase)}\s+"
            r"(?P<target>[A-Z][a-zA-Z0-9\s\.\,\-]+?)(?:[\.\,\;\n]|$)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(sentence):
            raw_source = clean_entity_name(match.group("source"))
            raw_target = clean_entity_name(match.group("target"))
            for p in sorted(known_people, key=len, reverse=True):
                if raw_target.lower().startswith(p.lower()):
                    raw_target = p
                    break
            if not raw_source or not raw_target or raw_source.lower() == raw_target.lower():
                continue
            if len(raw_source) > 50 or len(raw_target) > 50:
                continue
            results.append(
                ExtractedRelationship(
                    source_entity=raw_source,
                    relation=canon_rel,
                    target_entity=raw_target,
                    source_type=classify_entity(raw_source, known_people),
                    target_type=classify_entity(raw_target, known_people),
                )
            )

    # Action / Project ownership
    for verb_phrase, canon_rel in ACTION_VERBS:
        pattern = re.compile(
            rf"(?P<source>[A-Z][a-zA-Z\s\.\,\-]+?)\s+{re.escape(verb_phrase)}\s+"
            r"(?:the\s+|a\s+|an\s+)?(?P<target>[A-Za-z0-9\s\.\,\-]+?)(?:[\.\,\;\n]|$)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(sentence):
            raw_source = clean_entity_name(match.group("source"))
            raw_target = clean_entity_name(match.group("target"))
            if not raw_source or not raw_target or raw_source.lower() == raw_target.lower():
                continue
            if len(raw_source) > 50 or len(raw_target) > 50:
                continue
            t_type = classify_entity(raw_target, known_people)
            if t_type == "entity":
                t_type = "project"
            results.append(
                ExtractedRelationship(
                    source_entity=raw_source,
                    relation=canon_rel,
                    target_entity=raw_target,
                    source_type=classify_entity(raw_source, known_people),
                    target_type=t_type,
                )
            )
    return results


def _extract_cooccurrence_relationships(sentence: str, known_people: set[str]) -> list[ExtractedRelationship]:
    """Extract relational connections between known people co-occurring in a sentence."""
    results: list[ExtractedRelationship] = []
    # Identify which known people are mentioned in this sentence
    mentioned: list[str] = []
    for p in known_people:
        if re.search(rf"\b{re.escape(p)}\b", sentence, re.IGNORECASE):
            mentioned.append(p)

    if len(mentioned) < 2:
        # Check general extracted people
        found_people = extract_people(sentence)
        mentioned = list(dict.fromkeys(mentioned + found_people))

    if len(mentioned) >= 2:
        for i in range(len(mentioned)):
            for j in range(i + 1, len(mentioned)):
                p1 = mentioned[i]
                p2 = mentioned[j]
                if p1.lower() == p2.lower() or are_names_compatible(p1, p2):
                    continue
                # Determine relationship verb if any exists between the two mentions
                m1_idx = sentence.lower().find(p1.lower())
                m2_idx = sentence.lower().find(p2.lower())
                rel_label = "connected with"
                if m1_idx != -1 and m2_idx != -1:
                    first_p = p1 if m1_idx < m2_idx else p2
                    second_p = p2 if m1_idx < m2_idx else p1
                    span = sentence[min(m1_idx, m2_idx):max(m1_idx, m2_idx) + len(second_p)]
                    for vp, canon in COLLAB_VERBS + HIERARCHY_VERBS:
                        if vp in span.lower():
                            rel_label = canon
                            break
                    results.append(
                        ExtractedRelationship(
                            source_entity=first_p,
                            relation=rel_label,
                            target_entity=second_p,
                            source_type="person",
                            target_type="person",
                        )
                    )
    return results


def extract_relationships_from_text(text: str, known_people: set[str] | None = None) -> list[ExtractedRelationship]:
    """Extract relationship triples from a block of text."""
    if not text.strip():
        return []

    people_set = set(known_people or [])
    # Also extract any people mentioned in the text
    for p in extract_people(text):
        prefix, core, suffix = parse_name_parts(p)
        clean_p = " ".join(core) if core else p
        people_set.add(clean_p)
        people_set.add(p)

    # Split text into sentences
    sentences = re.split(r"(?<=[.!?])\s+", text)
    relationships: list[ExtractedRelationship] = []
    seen: set[tuple[str, str, str]] = set()

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        sent_rels: list[ExtractedRelationship] = []
        sent_rels.extend(_extract_role_relationships(sent, people_set))
        sent_rels.extend(_extract_hierarchy_relationships(sent, people_set))
        sent_rels.extend(_extract_action_and_collab_relationships(sent, people_set))
        sent_rels.extend(_extract_cooccurrence_relationships(sent, people_set))

        for rel in sent_rels:
            key = (rel.source_entity.lower(), rel.relation.lower(), rel.target_entity.lower())
            if key not in seen:
                seen.add(key)
                relationships.append(rel)

    return relationships
