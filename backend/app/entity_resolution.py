from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


HONORIFIC_PREFIXES = {
    "dr", "doctor", "prof", "professor", "mr", "mrs", "ms", "miss",
    "sir", "dame", "rev", "reverend", "gen", "general", "col", "colonel",
    "capt", "captain", "sen", "senator", "rep", "representative", "gov", "governor"
}

HONORIFIC_SUFFIXES = {
    "jr", "sr", "ii", "iii", "iv", "phd", "md", "esq", "jd", "ma", "ba", "bs", "ms"
}

NICKNAME_MAP: dict[str, set[str]] = {
    "robert": {"bob", "bobby", "rob", "robbie", "bert"},
    "william": {"bill", "billy", "will", "willy", "liam"},
    "richard": {"dick", "rich", "rick", "ricky"},
    "james": {"jim", "jimmy", "jamie"},
    "michael": {"mike", "mikey", "mick"},
    "alexander": {"alex", "alec", "lex"},
    "alexandra": {"alex", "lexi", "sasha"},
    "thomas": {"tom", "tommy"},
    "elizabeth": {"beth", "liz", "lizzie", "eliza", "ellie"},
    "edward": {"ed", "eddie", "ted", "teddy", "ned"},
    "joseph": {"joe", "joey"},
    "charles": {"charlie", "chuck", "chas"},
    "david": {"dave", "davey"},
    "john": {"jack", "jackie", "johnny"},
    "margaret": {"maggie", "meg", "peggy", "marge"},
    "katherine": {"kate", "katie", "cathy", "cat"},
    "catherine": {"kate", "katie", "cathy", "cat"},
    "christopher": {"chris", "kit"},
    "daniel": {"dan", "danny"},
    "matthew": {"matt", "matty"},
    "anthony": {"tony"},
    "benjamin": {"ben", "benny", "benji"},
    "jonathan": {"jon", "jonny"},
    "nicholas": {"nick", "nicky"},
    "samuel": {"sam", "sammy"},
    "timothy": {"tim", "timmy"},
    "stephen": {"steve", "steven"},
    "steven": {"steve", "stephen"},
    "patrick": {"pat", "paddy"},
    "andrew": {"andy", "drew"},
    "gerald": {"jerry"},
    "harold": {"hal", "harry"},
    "henry": {"hank", "harry"},
    "arthur": {"art", "artie"},
    "lawrence": {"larry"},
    "walter": {"walt", "wally"},
    "raymond": {"ray"},
    "ronald": {"ron", "ronnie"},
    "donald": {"don", "donnie"},
    "douglas": {"doug"},
    "gregory": {"greg"},
    "phillip": {"phil"},
    "philip": {"phil"},
    "theodore": {"ted", "teddy", "theo"},
    "kenneth": {"ken", "kenny"},
    "alan": {"al"},
    "albert": {"al", "bert"},
    "vincent": {"vince", "vinny"},
    "eugene": {"gene"},
    "russell": {"russ"},
    "bradley": {"brad"},
    "clifford": {"cliff"},
    "leonard": {"leo", "len", "lenny"},
    "stanley": {"stan"},
    "bernard": {"bernie"},
}


def jaro_similarity(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    len1, len2 = len(s1), len(s2)
    if len1 == 0 or len2 == 0:
        return 0.0

    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1[i] != s2[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1[i] != s2[k]:
            transpositions += 1
        k += 1

    return (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3.0


def jaro_winkler_similarity(s1: str, s2: str, p: float = 0.1, max_l: int = 4) -> float:
    j_sim = jaro_similarity(s1, s2)
    l = 0
    for c1, c2 in zip(s1, s2):
        if c1 == c2:
            l += 1
            if l == max_l:
                break
        else:
            break
    return j_sim + (l * p * (1.0 - j_sim))


def are_nicknames(name1: str, name2: str) -> bool:
    n1, n2 = name1.lower(), name2.lower()
    if n1 == n2:
        return True
    if n1 in NICKNAME_MAP and n2 in NICKNAME_MAP[n1]:
        return True
    if n2 in NICKNAME_MAP and n1 in NICKNAME_MAP[n2]:
        return True
    for formal, nicks in NICKNAME_MAP.items():
        if (n1 == formal or n1 in nicks) and (n2 == formal or n2 in nicks):
            return True
    return False


def parse_name_parts(name: str) -> tuple[str | None, list[str], str | None]:
    """Parse name into (honorific_prefix, core_tokens, honorific_suffix)."""
    clean = re.sub(r"[,;]", " ", name).strip()
    raw_tokens = clean.split()
    if not raw_tokens:
        return None, [], None

    prefix = None
    suffix = None
    start_idx = 0
    end_idx = len(raw_tokens)

    first_tok = raw_tokens[0].lower().rstrip(".")
    if first_tok in HONORIFIC_PREFIXES and len(raw_tokens) > 1:
        prefix = raw_tokens[0]
        start_idx = 1

    last_tok = raw_tokens[-1].lower().rstrip(".")
    if last_tok in HONORIFIC_SUFFIXES and end_idx - start_idx > 1:
        suffix = raw_tokens[-1].rstrip(".")
        end_idx -= 1

    core = [t.rstrip(".") for t in raw_tokens[start_idx:end_idx] if t.rstrip(".")]
    return prefix, core, suffix


def are_names_compatible(name1: str, name2: str) -> bool:
    """Return True if name1 and name2 can refer to the same person."""
    if name1.strip().lower() == name2.strip().lower():
        return True

    _, core1, _ = parse_name_parts(name1)
    _, core2, _ = parse_name_parts(name2)

    if not core1 or not core2:
        return False

    # Both multi-token: first [middle...] last
    if len(core1) >= 2 and len(core2) >= 2:
        last1, last2 = core1[-1].lower(), core2[-1].lower()
        # Last name must match or have extreme similarity (typo)
        if last1 != last2 and jaro_winkler_similarity(last1, last2) < 0.92:
            return False

        first1, first2 = core1[0].lower(), core2[0].lower()
        # Check first name equivalence
        first_compatible = False
        if first1 == first2:
            first_compatible = True
        elif are_nicknames(first1, first2):
            first_compatible = True
        elif (len(first1) == 1 or len(first2) == 1) and first1[0] == first2[0]:
            first_compatible = True
        elif jaro_winkler_similarity(first1, first2) >= 0.88:
            first_compatible = True

        if not first_compatible:
            return False

        # Middle name check if present on both
        mid1 = [m.lower() for m in core1[1:-1]]
        mid2 = [m.lower() for m in core2[1:-1]]
        if mid1 and mid2:
            m1, m2 = mid1[0], mid2[0]
            if len(m1) == 1 or len(m2) == 1:
                if m1[0] != m2[0]:
                    return False
            elif m1 != m2 and jaro_winkler_similarity(m1, m2) < 0.88:
                return False

        return True

    return False


def slugify_name(name: str) -> str:
    """Create a URL-safe canonical ID from a person's name."""
    normalized = unicodedata.normalize("NFKD", name)
    clean = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    return re.sub(r"[-\s]+", "-", clean)


def pick_canonical_name(aliases: list[str], mention_counts: dict[str, int]) -> str:
    """Select the best canonical display name from a set of aliases."""
    def score_name(n: str) -> tuple[int, int, int, int, str]:
        prefix, core, suffix = parse_name_parts(n)
        is_full = 1 if len(core) >= 2 else 0
        has_no_prefix = 1 if not prefix else 0
        first_is_formal = 0
        if core:
            first = core[0].lower()
            # If it's a known nickname but not the formal version, penalize
            is_formal = first in NICKNAME_MAP or not any(first in nicks for nicks in NICKNAME_MAP.values())
            first_is_formal = 1 if is_formal else 0
        mentions = mention_counts.get(n, 0)
        return (is_full, has_no_prefix, first_is_formal, mentions, n)

    # Sort descending by score
    sorted_names = sorted(aliases, key=score_name, reverse=True)
    return sorted_names[0]


class UnionFind:
    def __init__(self, elements: list[str]):
        self.parent = {e: e for e in elements}

    def find(self, i: str) -> str:
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i: str, j: str) -> None:
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j


def cluster_people(raw_people: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cluster raw people records into canonical entities with alias lists.

    Input dicts must have at least 'name' and optionally 'mentions', 'document_id'.
    """
    if not raw_people:
        return []

    mention_counts: dict[str, int] = defaultdict(int)
    doc_sets: dict[str, set[str]] = defaultdict(set)
    names_set: set[str] = set()

    for item in raw_people:
        name = item["name"].strip()
        if not name:
            continue
        names_set.add(name)
        mention_counts[name] += item.get("mentions", 1)
        doc_id = item.get("document_id")
        if doc_id:
            doc_sets[name].add(doc_id)

    all_names = list(names_set)
    uf = UnionFind(all_names)

    # 1. Cluster multi-token names
    multi_token_names = [n for n in all_names if len(parse_name_parts(n)[1]) >= 2]
    single_token_names = [n for n in all_names if len(parse_name_parts(n)[1]) == 1]

    for i in range(len(multi_token_names)):
        for j in range(i + 1, len(multi_token_names)):
            n1 = multi_token_names[i]
            n2 = multi_token_names[j]
            if are_names_compatible(n1, n2):
                uf.union(n1, n2)

    # 2. Resolve single-token names to multi-token clusters if unambiguous
    # Map each cluster root to its member first names
    root_to_firsts: dict[str, set[str]] = defaultdict(set)
    for n in multi_token_names:
        r = uf.find(n)
        _, core, _ = parse_name_parts(n)
        if core:
            fn = core[0].lower()
            root_to_firsts[r].add(fn)
            if fn in NICKNAME_MAP:
                root_to_firsts[r].update(NICKNAME_MAP[fn])

    for s in single_token_names:
        _, core_s, _ = parse_name_parts(s)
        if not core_s:
            continue
        token_s = core_s[0].lower()
        matching_roots = [
            r for r, fns in root_to_firsts.items()
            if token_s in fns or any(are_nicknames(token_s, fn) for fn in fns)
        ]
        if len(matching_roots) == 1:
            # Unambiguous match!
            uf.union(s, matching_roots[0])

    # 3. Group by cluster root
    clusters: dict[str, list[str]] = defaultdict(list)
    for name in all_names:
        clusters[uf.find(name)].append(name)

    results: list[dict[str, Any]] = []
    for _, members in clusters.items():
        canonical_name = pick_canonical_name(members, mention_counts)
        total_mentions = sum(mention_counts[m] for m in members)
        all_docs = set()
        for m in members:
            all_docs.update(doc_sets[m])

        doc_count = len(all_docs) if all_docs else max((item.get("document_count", 1) for item in raw_people if item["name"] in members), default=1)
        aliases = sorted(members)

        results.append({
            "canonical_id": slugify_name(canonical_name) or "person",
            "name": canonical_name,
            "normalized": canonical_name.lower(),
            "mentions": total_mentions,
            "document_count": doc_count,
            "aliases": aliases,
        })

    # Sort by mentions desc, name asc
    return sorted(results, key=lambda p: (-p["mentions"], p["name"].lower()))


def get_person_aliases(person_name: str, known_people: list[dict[str, Any]]) -> list[str]:
    """Retrieve all aliases for a person name from a list of known clustered people."""
    target = person_name.strip().lower()
    for person in known_people:
        p_name = person["name"].lower()
        p_aliases = [a.lower() for a in person.get("aliases", [person["name"]])]
        if target == p_name or target in p_aliases:
            all_known = [person["name"], *person.get("aliases", [])]
            return list(dict.fromkeys(all_known))
    return [person_name]
