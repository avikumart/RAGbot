from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .entity_resolution import are_names_compatible, parse_name_parts, slugify_name
from .extraction import extract_people
from .relationship_extraction import ORG_INDICATORS, clean_entity_name


@dataclass(frozen=True)
class ExtractedTimelineEvent:
    entity_name: str
    event_text: str
    event_date: str


MONTHS_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

SEASON_MAP = {
    "spring": 3,
    "summer": 6,
    "fall": 9,
    "autumn": 9,
    "winter": 12,
    "q1": 1,
    "q2": 4,
    "q3": 7,
    "q4": 10,
}

MONTH_REGEX_STR = r"(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"

# 1. Year range: 2018-2022, 2018–2022, 2018 to 2022
YEAR_RANGE_PATTERN = re.compile(
    r"\b(?P<start_year>19\d{2}|20\d{2})\s*(?:-|–|—|to)\s*(?P<end_year>19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

# 2. Month Day, Year: January 15, 2021 or Jan 15 2021
MONTH_DAY_YEAR_PATTERN = re.compile(
    rf"\b(?P<month>{MONTH_REGEX_STR})\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>19\d{{2}}|20\d{{2}})\b",
    re.IGNORECASE,
)

# 3. Day Month Year: 15 January 2021
DAY_MONTH_YEAR_PATTERN = re.compile(
    rf"\b(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month>{MONTH_REGEX_STR})\s+(?P<year>19\d{{2}}|20\d{{2}})\b",
    re.IGNORECASE,
)

# 4. Month Year: September 2020, Sept. 2020
MONTH_YEAR_PATTERN = re.compile(
    rf"\b(?P<month>{MONTH_REGEX_STR})\s+(?P<year>19\d{{2}}|20\d{{2}})\b",
    re.IGNORECASE,
)

# 5. Season or Quarter Year: Fall 2021, Q3 2022
SEASON_YEAR_PATTERN = re.compile(
    r"\b(?P<season>Spring|Summer|Fall|Autumn|Winter|Q[1-4])\s+(?P<year>19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

# 6. ISO Date: 2021-09-15
ISO_DATE_PATTERN = re.compile(
    r"\b(?P<year>19\d{2}|20\d{2})-(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12]\d|3[01])\b",
    re.IGNORECASE,
)

# 7. Standalone Year with contextual indicators: In 2020, since 2019, by 2023, during 2021
CONTEXTUAL_YEAR_PATTERN = re.compile(
    r"\b(?:in|since|by|during|from|around|circa|c\.|until)\s+(?P<year>19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

# 8. Event verb followed by year: joined in 2020, promoted in 2021, graduated 2018
VERB_YEAR_PATTERN = re.compile(
    r"\b(?:joined|promoted|founded|co-founded|started|graduated|acquired|elected|appointed|retired|awarded|received|completed|left|launched|moved|became)\s+(?:in\s+)?(?P<year>19\d{2}|20\d{2})\b",
    re.IGNORECASE,
)

# 9. Parenthesized year: (2020)
PAREN_YEAR_PATTERN = re.compile(
    r"\((?P<year>19\d{2}|20\d{2})\)",
    re.IGNORECASE,
)

# 10. General standalone year: 1900-2099
STANDALONE_YEAR_PATTERN = re.compile(
    r"\b(?P<year>19\d{2}|20\d{2})\b",
)

MILESTONE_VERBS = {
    "join", "joined", "joining",
    "promote", "promoted", "promotion",
    "found", "founded", "founder", "co-found", "co-founded", "co-founder",
    "graduate", "graduated", "graduation",
    "acquire", "acquired", "acquisition",
    "appoint", "appointed", "appointment",
    "serve", "served", "serving",
    "elect", "elected", "election",
    "retire", "retired", "retirement",
    "award", "awarded", "receive", "received", "honored",
    "complete", "completed", "completion",
    "start", "started", "starting",
    "leave", "left", "leaving",
    "become", "became", "becoming",
    "launch", "launched", "launching",
    "publish", "published", "publishing",
    "author", "authored", "co-authored",
    "spearhead", "spearheaded",
    "lead", "led", "leading",
    "architect", "architected",
    "earn", "earned", "earning",
    "obtain", "obtained",
    "hire", "hired",
    "step down", "stepped down",
}


def parse_date_sort_key(date_str: str) -> tuple[int, int, int]:
    """Parse a date string into a chronological sort tuple (year, month, day)."""
    if not date_str:
        return (9999, 12, 31)

    clean = date_str.strip()

    # 1. ISO Date: YYYY-MM-DD
    iso_match = ISO_DATE_PATTERN.search(clean)
    if iso_match:
        return (int(iso_match.group("year")), int(iso_match.group("month")), int(iso_match.group("day")))

    # 2. Month Day, Year
    mdy_match = MONTH_DAY_YEAR_PATTERN.search(clean)
    if mdy_match:
        m_name = mdy_match.group("month").rstrip(".").lower()
        month = MONTHS_MAP.get(m_name, 1)
        return (int(mdy_match.group("year")), month, int(mdy_match.group("day")))

    # 3. Day Month Year
    dmy_match = DAY_MONTH_YEAR_PATTERN.search(clean)
    if dmy_match:
        m_name = dmy_match.group("month").rstrip(".").lower()
        month = MONTHS_MAP.get(m_name, 1)
        return (int(dmy_match.group("year")), month, int(dmy_match.group("day")))

    # 4. Month Year
    my_match = MONTH_YEAR_PATTERN.search(clean)
    if my_match:
        m_name = my_match.group("month").rstrip(".").lower()
        month = MONTHS_MAP.get(m_name, 1)
        return (int(my_match.group("year")), month, 1)

    # 5. Season / Quarter Year
    sy_match = SEASON_YEAR_PATTERN.search(clean)
    if sy_match:
        s_name = sy_match.group("season").lower()
        month = SEASON_MAP.get(s_name, 1)
        return (int(sy_match.group("year")), month, 1)

    # 6. Year range: 2018-2022
    yr_match = YEAR_RANGE_PATTERN.search(clean)
    if yr_match:
        return (int(yr_match.group("start_year")), 1, 1)

    # 7. Standalone Year
    y_match = STANDALONE_YEAR_PATTERN.search(clean)
    if y_match:
        return (int(y_match.group("year")), 1, 1)

    return (9999, 12, 31)


def extract_dates_from_sentence(sentence: str) -> list[str]:
    """Extract all temporal/date expressions present in a single sentence."""
    dates: list[str] = []
    seen_spans: list[tuple[int, int]] = []

    def is_overlapping(start: int, end: int) -> bool:
        return any(not (end <= s or start >= e) for s, e in seen_spans)

    def add_match(match: re.Match[str], raw_text: str | None = None) -> None:
        start, end = match.span()
        if not is_overlapping(start, end):
            seen_spans.append((start, end))
            dates.append((raw_text or match.group(0)).strip(" ,;:.()"))

    # Priority 1: High specificity patterns first
    for m in ISO_DATE_PATTERN.finditer(sentence):
        add_match(m)

    for m in MONTH_DAY_YEAR_PATTERN.finditer(sentence):
        add_match(m)

    for m in DAY_MONTH_YEAR_PATTERN.finditer(sentence):
        add_match(m)

    for m in MONTH_YEAR_PATTERN.finditer(sentence):
        add_match(m)

    for m in SEASON_YEAR_PATTERN.finditer(sentence):
        add_match(m)

    for m in YEAR_RANGE_PATTERN.finditer(sentence):
        add_match(m)

    for m in CONTEXTUAL_YEAR_PATTERN.finditer(sentence):
        add_match(m, m.group("year"))

    for m in VERB_YEAR_PATTERN.finditer(sentence):
        add_match(m, m.group("year"))

    for m in PAREN_YEAR_PATTERN.finditer(sentence):
        add_match(m, m.group("year"))

    for m in STANDALONE_YEAR_PATTERN.finditer(sentence):
        add_match(m, m.group("year"))

    return dates


def _extract_organizations(sentence: str) -> list[str]:
    """Extract organization / institution names from sentence."""
    orgs: list[str] = []
    # Match capitalized phrases containing organization indicator keywords
    # e.g., 'Acme Corp', 'Stanford University', 'DeepMind Labs', 'TechCorp'
    pattern = re.compile(
        r"\b([A-Z][a-zA-Z0-9'-]+(?:\s+[A-Z][a-zA-Z0-9'-]+){0,4})\b"
    )
    for match in pattern.finditer(sentence):
        phrase = match.group(1).strip()
        tokens = [t.lower() for t in phrase.split()]
        is_org = any(
            token in ORG_INDICATORS
            or any(token.endswith(ind) for ind in ("corp", "inc", "llc", "ltd", "labs"))
            for token in tokens
        )
        if is_org:
            cleaned = clean_entity_name(phrase)
            if cleaned and len(cleaned) <= 60 and cleaned not in orgs:
                orgs.append(cleaned)
    return orgs


def extract_timeline_events(
    text: str,
    known_people: set[str] | None = None,
) -> list[ExtractedTimelineEvent]:
    """Extract dated milestone events for people and organizations from text."""
    if not text or not text.strip():
        return []

    people_pool = set(known_people or [])
    # Also extract people directly from the text
    for p in extract_people(text):
        people_pool.add(p)
        prefix, core, suffix = parse_name_parts(p)
        if core:
            people_pool.add(" ".join(core))

    # Split into sentences or structured bullet lines
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    events: list[ExtractedTimelineEvent] = []
    seen: set[tuple[str, str, str]] = set()

    for raw_sent in raw_sentences:
        sent = raw_sent.strip()
        if len(sent) < 5:
            continue

        # Extract dates from sentence
        dates = extract_dates_from_sentence(sent)
        if not dates:
            continue

        # Find people and entities mentioned in sentence
        mentioned_entities: list[str] = []

        # 1. Check known people (full name and first name)
        for person in sorted(people_pool, key=len, reverse=True):
            if re.search(rf"\b{re.escape(person)}\b", sent, re.IGNORECASE):
                mentioned_entities.append(person)
                continue
            _, core, _ = parse_name_parts(person)
            if core and len(core[0]) >= 3:
                first_name = core[0]
                if re.search(rf"\b{re.escape(first_name)}\b", sent):
                    mentioned_entities.append(person)

        # 2. Check general extracted people in this sentence
        for p in extract_people(sent):
            p_lower = p.lower()
            tokens = p_lower.split()
            if any(t in MONTHS_MAP or t in SEASON_MAP for t in tokens):
                continue
            if p not in mentioned_entities:
                mentioned_entities.append(p)

        # 3. Check organizations in this sentence
        for org in _extract_organizations(sent):
            org_lower = org.lower()
            tokens = org_lower.split()
            if any(t in MONTHS_MAP or t in SEASON_MAP for t in tokens):
                continue
            if org not in mentioned_entities:
                mentioned_entities.append(org)

        # Resolve extracted people to full known person if compatible
        resolved_entities: list[str] = []
        for ent in mentioned_entities:
            ent_clean = clean_entity_name(ent)
            if not ent_clean or len(ent_clean) < 2:
                continue

            # Check if ent_clean is a compatible alias or part of a known person
            resolved = ent_clean
            for kp in sorted(known_people or [], key=len, reverse=True):
                if ent_clean.lower() == kp.lower() or are_names_compatible(ent_clean, kp):
                    resolved = kp
                    break
                # If single first name matches
                _, core, _ = parse_name_parts(kp)
                if core and ent_clean.lower() == core[0].lower():
                    resolved = kp
                    break

            if resolved not in resolved_entities:
                resolved_entities.append(resolved)

        if not resolved_entities:
            continue

        clean_event_text = re.sub(r"\s+", " ", sent).strip()

        for date_str in dates:
            for ent in resolved_entities:
                key = (ent.lower(), date_str.lower(), clean_event_text.lower())
                if key not in seen:
                    seen.add(key)
                    events.append(
                        ExtractedTimelineEvent(
                            entity_name=ent,
                            event_text=clean_event_text,
                            event_date=date_str,
                        )
                    )

    # Sort events chronologically
    events.sort(key=lambda ev: parse_date_sort_key(ev.event_date))
    return events
