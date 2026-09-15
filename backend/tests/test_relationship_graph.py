from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.relationship_extraction import (
    ExtractedRelationship,
    clean_entity_name,
    classify_entity,
    extract_relationships_from_text,
)
from app.store import Store


def test_clean_entity_name():
    assert clean_entity_name("  the Acme Corp,  ") == "Acme Corp"
    assert clean_entity_name("Dr. Robert Smith") == "Robert Smith"
    assert clean_entity_name("Project Apollo in 2021.") == "Project Apollo"


def test_classify_entity():
    known_people = {"Robert Smith", "Maya Patel"}
    assert classify_entity("Robert Smith", known_people) == "person"
    assert classify_entity("Acme Corporation", known_people) == "organization"
    assert classify_entity("Stanford University", known_people) == "organization"
    assert classify_entity("Chief Technology Officer", known_people) == "role"
    assert classify_entity("rollout plan", known_people) == "project"


def test_extract_role_relationship():
    text = "Dr. Robert Smith was appointed as Chief Technology Officer at Acme Labs in 2021."
    rels = extract_relationships_from_text(text)
    assert len(rels) >= 1
    rel = next((r for r in rels if "Acme" in r.target_entity), None)
    assert rel is not None
    assert "Robert Smith" in rel.source_entity
    assert "Chief Technology Officer" in rel.relation
    assert "Acme Labs" in rel.target_entity
    assert rel.source_type == "person"
    assert rel.target_type == "organization"


def test_extract_hierarchy_and_reporting():
    text = "Jordan Lee reports to Robert Smith. Robert oversaw the architecture."
    rels = extract_relationships_from_text(text, known_people={"Jordan Lee", "Robert Smith"})
    assert any(
        r.source_entity == "Jordan Lee" and r.relation == "reports to" and r.target_entity == "Robert Smith"
        for r in rels
    )


def test_extract_action_and_ownership():
    text = "Jordan Lee owns the rollout plan."
    rels = extract_relationships_from_text(text, known_people={"Jordan Lee"})
    assert any(
        r.source_entity == "Jordan Lee" and r.relation == "owns" and "rollout plan" in r.target_entity
        for r in rels
    )


def test_extract_collaboration():
    text = "Maya Patel collaborated with Jordan Lee on the migration."
    rels = extract_relationships_from_text(text, known_people={"Maya Patel", "Jordan Lee"})
    assert any(
        "Maya Patel" in r.source_entity and "collaborat" in r.relation and "Jordan Lee" in r.target_entity
        for r in rels
    )


def test_store_graph_retrieval_and_scoping(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    # Upload Doc 1: Robert and Acme
    doc1_content = (
        "Executive Summary.\n"
        "Dr. Robert Smith was appointed as Chief Technology Officer at Acme Labs. "
        "Robert oversees the cloud migration architecture."
    )
    # Upload Doc 2: Jordan and Maya
    doc2_content = (
        "Project Update.\n"
        "Jordan Lee reported to Maya Patel and owns the rollout plan."
    )

    p1 = store.upload_dir / "doc1.txt"
    p1.write_text(doc1_content)
    store.add_document(
        document_id="doc-1",
        filename="doc1.txt",
        content_type="text/plain",
        stored_path=p1,
        digest="d1",
        size_bytes=len(doc1_content),
        chunks=[
            type("Chunk", (), {
                "ordinal": 0, "page": 1, "content": doc1_content,
                "people": ("Robert Smith",),
            })()
        ],
        people={"Robert Smith": 2},
        owner_id="user-1",
    )

    p2 = store.upload_dir / "doc2.txt"
    p2.write_text(doc2_content)
    store.add_document(
        document_id="doc-2",
        filename="doc2.txt",
        content_type="text/plain",
        stored_path=p2,
        digest="d2",
        size_bytes=len(doc2_content),
        chunks=[
            type("Chunk", (), {
                "ordinal": 0, "page": 1, "content": doc2_content,
                "people": ("Jordan Lee", "Maya Patel"),
            })()
        ],
        people={"Jordan Lee": 1, "Maya Patel": 1},
        owner_id="user-1",
    )

    # 1. Full graph for user-1
    graph = store.get_graph(owner_id="user-1")
    assert len(graph["nodes"]) >= 3
    node_labels = {n["label"] for n in graph["nodes"]}
    assert "Robert Smith" in node_labels
    assert "Jordan Lee" in node_labels
    assert "Maya Patel" in node_labels

    edge_sources = {e["source"] for e in graph["edges"]}
    assert any("Robert" in s or "Jordan" in s for s in edge_sources)

    # 2. Document scoping (only doc-1)
    scoped_doc1 = store.get_graph(document_ids=["doc-1"], owner_id="user-1")
    doc1_labels = {n["label"] for n in scoped_doc1["nodes"]}
    assert "Robert Smith" in doc1_labels
    assert "Jordan Lee" not in doc1_labels

    # 3. Person scoping (Jordan Lee)
    jordan_subgraph = store.get_graph(owner_id="user-1", person="Jordan Lee")
    jordan_labels = {n["label"] for n in jordan_subgraph["nodes"]}
    assert "Jordan Lee" in jordan_labels
    assert "Robert Smith" not in jordan_labels

    # 4. Multi-tenant isolation (user-2 sees nothing)
    user2_graph = store.get_graph(owner_id="user-2")
    assert len(user2_graph["nodes"]) == 0
    assert len(user2_graph["edges"]) == 0

    # 5. Deletion cascades relationships
    store.delete_document("doc-1", owner_id="user-1")
    post_del_graph = store.get_graph(owner_id="user-1")
    post_del_labels = {n["label"] for n in post_del_graph["nodes"]}
    assert "Robert Smith" not in post_del_labels


def owner_headers(identity: str, secret: str = "test-proxy-secret"):
    import hashlib
    import hmac
    from datetime import UTC, datetime
    from app.main import opaque_owner_id

    owner = opaque_owner_id(identity)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    signature = hmac.new(
        secret.encode(), f"{owner}:{timestamp}".encode(), hashlib.sha256
    ).hexdigest()
    return {
        "x-personagraph-owner": owner,
        "x-personagraph-owner-timestamp": timestamp,
        "x-personagraph-owner-signature": signature,
    }


def test_api_graph_endpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PROXY_SECRET", "test-proxy-secret")
    alice = owner_headers("alice@example.com")
    bob = owner_headers("bob@example.com")

    app = create_app(tmp_path)
    with TestClient(app) as client:
        content = (
            "Team Structure.\n"
            "Jordan Lee reports to Dr. Robert Smith. "
            "Jordan Lee owns the rollout plan."
        )
        res = client.post(
            "/api/documents",
            files={"file": ("team.txt", content.encode(), "text/plain")},
            headers=alice,
        )
        assert res.status_code == 201

        # GET /api/graph with matching user
        graph_res = client.get("/api/graph", headers=alice)
        assert graph_res.status_code == 200
        data = graph_res.json()
        assert "nodes" in data
        assert "edges" in data
        assert any("Jordan" in n["label"] for n in data["nodes"])

        # GET /api/graph with scoped person
        person_graph = client.get("/api/graph?person=Jordan+Lee", headers=alice)
        assert person_graph.status_code == 200
        p_data = person_graph.json()
        assert any("Jordan" in n["label"] for n in p_data["nodes"])

        # GET /api/graph with unowned user receives empty graph
        other_graph = client.get("/api/graph", headers=bob)
        assert other_graph.status_code == 200
        assert len(other_graph.json()["nodes"]) == 0
