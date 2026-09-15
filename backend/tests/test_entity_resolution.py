from __future__ import annotations

import pytest

from app.entity_resolution import (
    are_names_compatible,
    are_nicknames,
    cluster_people,
    get_person_aliases,
    jaro_winkler_similarity,
    parse_name_parts,
)
from app.main import create_app
from app.retrieval import identify_people
from fastapi.testclient import TestClient


def test_parse_name_parts():
    prefix, core, suffix = parse_name_parts("Dr. Robert J. Smith, Jr.")
    assert prefix == "Dr."
    assert core == ["Robert", "J", "Smith"]
    assert suffix == "Jr"

    prefix, core, suffix = parse_name_parts("Bob Smith")
    assert prefix is None
    assert core == ["Bob", "Smith"]
    assert suffix is None

    prefix, core, suffix = parse_name_parts("Professor Maya Patel")
    assert prefix == "Professor"
    assert core == ["Maya", "Patel"]
    assert suffix is None

    prefix, core, suffix = parse_name_parts("Aristotle")
    assert prefix is None
    assert core == ["Aristotle"]
    assert suffix is None


def test_nickname_matching():
    assert are_nicknames("Robert", "Bob")
    assert are_nicknames("Bob", "Bobby")
    assert are_nicknames("William", "Bill")
    assert are_nicknames("Margaret", "Peggy")
    assert are_nicknames("Michael", "Mike")
    assert are_nicknames("James", "Jim")
    assert not are_nicknames("Robert", "John")
    assert not are_nicknames("Alice", "Bob")


def test_are_names_compatible():
    # Honorifics
    assert are_names_compatible("Dr. Robert Smith", "Robert Smith")
    assert are_names_compatible("Prof. Maya Patel", "Maya Patel")

    # Nicknames with same surname
    assert are_names_compatible("Bob Smith", "Robert Smith")
    assert are_names_compatible("Dr. Robert Smith", "Bob Smith")
    assert are_names_compatible("Bill Miller", "William Miller")

    # Middle initials / names
    assert are_names_compatible("Robert J. Smith", "Robert Smith")
    assert are_names_compatible("Robert John Smith", "Robert J. Smith")

    # Incompatible cases
    assert not are_names_compatible("Robert John Smith", "Robert Alan Smith")  # Conflicting middle names
    assert not are_names_compatible("Robert Smith", "John Smith")  # Different first names
    assert not are_names_compatible("Robert Smith", "Robert Jones")  # Different last names


def test_cluster_people_merges_aliases_and_honorifics():
    raw_people = [
        {"name": "Dr. Robert Smith", "mentions": 5, "document_id": "doc1"},
        {"name": "Bob Smith", "mentions": 3, "document_id": "doc2"},
        {"name": "Robert Smith", "mentions": 2, "document_id": "doc1"},
        {"name": "Jordan Lee", "mentions": 4, "document_id": "doc1"},
        {"name": "Dr. Maya Patel", "mentions": 6, "document_id": "doc2"},
    ]

    clustered = cluster_people(raw_people)
    by_name = {p["name"]: p for p in clustered}

    assert "Robert Smith" in by_name
    robert = by_name["Robert Smith"]
    assert robert["mentions"] == 10
    assert robert["document_count"] == 2
    assert set(robert["aliases"]) == {"Dr. Robert Smith", "Bob Smith", "Robert Smith"}
    assert robert["canonical_id"] == "robert-smith"

    assert "Jordan Lee" in by_name
    jordan = by_name["Jordan Lee"]
    assert jordan["mentions"] == 4
    assert jordan["aliases"] == ["Jordan Lee"]

    assert "Maya Patel" in by_name or "Dr. Maya Patel" in by_name


def test_cluster_people_resolves_unambiguous_single_name():
    raw_people = [
        {"name": "Robert Smith", "mentions": 4, "document_id": "doc1"},
        {"name": "Robert", "mentions": 2, "document_id": "doc1"},
        {"name": "Alice Walker", "mentions": 3, "document_id": "doc1"},
    ]

    clustered = cluster_people(raw_people)
    by_name = {p["name"]: p for p in clustered}

    assert "Robert Smith" in by_name
    assert "Robert" not in by_name  # Merged into Robert Smith
    assert "Robert" in by_name["Robert Smith"]["aliases"]
    assert by_name["Robert Smith"]["mentions"] == 6


def test_cluster_people_keeps_ambiguous_single_name_separate():
    raw_people = [
        {"name": "Robert Smith", "mentions": 4, "document_id": "doc1"},
        {"name": "Robert Jones", "mentions": 3, "document_id": "doc1"},
        {"name": "Robert", "mentions": 2, "document_id": "doc1"},
    ]

    clustered = cluster_people(raw_people)
    by_name = {p["name"]: p for p in clustered}

    # "Robert" is ambiguous between Smith and Jones, so it remains separate
    assert "Robert Smith" in by_name
    assert "Robert Jones" in by_name
    assert "Robert" in by_name


def test_cluster_people_preserves_unique_names():
    raw_people = [
        {"name": "Plato", "mentions": 5, "document_id": "doc1"},
        {"name": "Aristotle", "mentions": 4, "document_id": "doc1"},
    ]

    clustered = cluster_people(raw_people)
    by_name = {p["name"]: p for p in clustered}
    assert "Plato" in by_name
    assert "Aristotle" in by_name


def test_retrieval_alias_expansion():
    known_people = [
        {
            "canonical_id": "robert-smith",
            "name": "Robert Smith",
            "normalized": "robert smith",
            "mentions": 8,
            "document_count": 2,
            "aliases": ["Bob Smith", "Dr. Robert Smith", "Robert"],
        },
        {
            "canonical_id": "jordan-lee",
            "name": "Jordan Lee",
            "normalized": "jordan lee",
            "mentions": 4,
            "document_count": 1,
            "aliases": ["Jordan Lee"],
        },
    ]

    # Explicit scoping to canonical name expands to all aliases
    people = identify_people("What was the result?", known_people, explicit="Robert Smith")
    assert "Robert Smith" in people
    assert "Dr. Robert Smith" in people
    assert "Bob Smith" in people

    # Explicit scoping to an alias expands to canonical name and all aliases
    people_from_alias = identify_people("What was the result?", known_people, explicit="Bob Smith")
    assert "Robert Smith" in people_from_alias
    assert "Dr. Robert Smith" in people_from_alias

    # Question mentioning alias resolves to the persona cluster
    people_from_q = identify_people("What did Bob do yesterday?", known_people)
    assert "Robert Smith" in people_from_q
    assert "Bob Smith" in people_from_q


def test_api_people_endpoint_clusters_aliases(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        # Upload doc 1 mentioning "Dr. Robert Smith" and "Robert"
        doc1_content = (
            "Executive Summary.\n"
            "Dr. Robert Smith was appointed as Chief Technology Officer in 2021. "
            "Robert oversaw the cloud migration architecture."
        )
        # Upload doc 2 mentioning "Bob Smith"
        doc2_content = (
            "Quarterly Review.\n"
            "Bob Smith presented the engineering milestone update to the board."
        )

        r1 = client.post(
            "/api/documents",
            files={"file": ("doc1.txt", doc1_content.encode(), "text/plain")},
        )
        assert r1.status_code == 201

        r2 = client.post(
            "/api/documents",
            files={"file": ("doc2.txt", doc2_content.encode(), "text/plain")},
        )
        assert r2.status_code == 201

        people_res = client.get("/api/people")
        assert people_res.status_code == 200
        people = people_res.json()

        # Find the Robert Smith cluster
        robert_profiles = [p for p in people if "Smith" in p["name"] or any("Smith" in a for a in p.get("aliases", []))]
        assert len(robert_profiles) == 1
        robert = robert_profiles[0]
        assert "aliases" in robert
        assert len(robert["aliases"]) >= 2
        assert any("Robert" in a for a in robert["aliases"])
        assert any("Bob" in a for a in robert["aliases"])
