from __future__ import annotations

import time
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.entity_resolution import resolve_query_entities
from app.llm import LLMService, format_source_context
from app.main import create_app
from app.retrieval import format_graph_context, hybrid_retrieve
from app.store import Chunk, Store


def test_resolve_query_entities():
    known_people = [
        {"name": "Jordan Lee", "normalized": "jordan lee", "aliases": ["Jordan", "J. Lee"]},
        {"name": "Maya Patel", "normalized": "maya patel", "aliases": ["Maya"]},
        {"name": "Robert Smith", "normalized": "robert smith", "aliases": ["Bob Smith", "Rob Smith"]},
    ]
    known_entities = {"Jordan Lee", "Maya Patel", "Robert Smith", "Project Apollo", "Acme Labs"}

    # 1. Multi-hop query with nicknames and entities
    entities = resolve_query_entities(
        "Who worked with Jordan on Project Apollo through Maya?",
        known_entities=known_entities,
        known_people=known_people,
    )
    assert "Jordan Lee" in entities
    assert "Project Apollo" in entities
    assert "Maya Patel" in entities

    # 2. Nickname resolution ("Bob" -> "Robert Smith")
    bob_entities = resolve_query_entities(
        "What projects does Bob work on at Acme Labs?",
        known_entities=known_entities,
        known_people=known_people,
    )
    assert "Robert Smith" in bob_entities
    assert "Acme Labs" in bob_entities

    # 3. Quoted entity and honorific handling
    honorific_entities = resolve_query_entities(
        'What connects "Dr. Robert Smith" and Acme Labs?',
        known_entities=known_entities,
        known_people=known_people,
    )
    assert "Robert Smith" in honorific_entities
    assert "Acme Labs" in honorific_entities


def test_traverse_subgraph_execution_time_under_15ms(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    # Seed store with relationships
    doc_content = "Maya Patel collaborated with Jordan Lee. Jordan Lee leads Project Apollo."
    p = store.upload_dir / "seed.txt"
    p.write_text(doc_content)
    store.add_document(
        document_id="doc-perf",
        filename="seed.txt",
        content_type="text/plain",
        stored_path=p,
        digest="perf-digest",
        size_bytes=len(doc_content),
        chunks=[
            Chunk(0, 1, "Maya Patel collaborated with Jordan Lee.", ("Maya Patel", "Jordan Lee")),
            Chunk(1, 1, "Jordan Lee leads Project Apollo.", ("Jordan Lee",)),
        ],
        people={"Maya Patel": 1, "Jordan Lee": 2},
        owner_id="user-perf",
    )

    # Insert 50 additional relationship edges to verify indexed traversal performance
    with store.connect() as conn:
        extra_edges = []
        for i in range(50):
            extra_edges.append((
                "doc-perf",
                None,
                f"Entity_{i}",
                f"Entity_{i+1}",
                "connects to",
                "entity",
                "entity",
            ))
        conn.executemany(
            """INSERT INTO entity_relationships
            (document_id, chunk_id, source_entity, target_entity, relation, source_type, target_type)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            extra_edges,
        )

    # Measure execution time
    start = time.perf_counter()
    result = store.traverse_subgraph(
        seed_entities=["Jordan Lee"],
        document_ids=["doc-perf"],
        owner_id="user-perf",
        max_depth=2,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    assert elapsed_ms < 15.0, f"Traversal took {elapsed_ms:.2f}ms, expected under 15ms"
    assert len(result["edges"]) >= 2
    assert "Project Apollo" in result["nodes"]
    assert "Maya Patel" in result["nodes"]


def test_traverse_subgraph_scoping_and_bridging_nodes(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    # Doc A (Owner 1): Alice -> Acme
    doc_a_path = store.upload_dir / "doc_a.txt"
    doc_a_path.write_text("Alice works at Acme Corp.")
    store.add_document(
        document_id="doc-a",
        filename="doc_a.txt",
        content_type="text/plain",
        stored_path=doc_a_path,
        digest="d-a",
        size_bytes=25,
        chunks=[Chunk(0, 1, "Alice works at Acme Corp.", ("Alice",))],
        people={"Alice": 1},
        owner_id="owner-1",
    )

    # Doc B (Owner 1): Bob -> Acme
    doc_b_path = store.upload_dir / "doc_b.txt"
    doc_b_path.write_text("Bob is employed by Acme Corp.")
    store.add_document(
        document_id="doc-b",
        filename="doc_b.txt",
        content_type="text/plain",
        stored_path=doc_b_path,
        digest="d-b",
        size_bytes=29,
        chunks=[Chunk(0, 1, "Bob is employed by Acme Corp.", ("Bob",))],
        people={"Bob": 1},
        owner_id="owner-1",
    )

    # Multi-hop query with 2 seeds: Alice and Bob
    subgraph = store.traverse_subgraph(
        seed_entities=["Alice", "Bob"],
        document_ids=["doc-a", "doc-b"],
        owner_id="owner-1",
        max_depth=2,
    )

    # Acme Corp connects Alice and Bob -> Acme Corp is the bridging node
    assert any("Acme" in b for b in subgraph["bridging_nodes"])
    assert len(subgraph["edges"]) == 2

    # Owner isolation: owner-2 should see nothing
    isolated = store.traverse_subgraph(
        seed_entities=["Alice", "Bob"],
        owner_id="owner-2",
        max_depth=2,
    )
    assert isolated["edges"] == []
    assert isolated["bridging_nodes"] == []


def test_format_graph_context():
    edges = [
        {"source_entity": "Jordan Lee", "relation": "worked with", "target_entity": "Maya Patel"},
        {"source_entity": "Maya Patel", "relation": "leads", "target_entity": "Project Apollo"},
        {"source_entity": "Jordan Lee", "relation": "worked with", "target_entity": "Maya Patel"}, # duplicate
    ]
    formatted = format_graph_context(edges)
    expected_lines = [
        "[Jordan Lee] --(worked with)--> [Maya Patel]",
        "[Maya Patel] --(leads)--> [Project Apollo]",
    ]
    assert formatted == "\n".join(expected_lines)


def test_format_source_context_injects_relationship_subgraph():
    sources = [
        {"index": 1, "filename": "doc1.txt", "page": 1, "excerpt": "Jordan Lee worked with Maya Patel."},
        {"index": 2, "filename": "doc2.txt", "page": 2, "excerpt": "Maya Patel leads Project Apollo."},
    ]
    graph_context = "[Jordan Lee] --(worked with)--> [Maya Patel]\n[Maya Patel] --(leads)--> [Project Apollo]"
    context = format_source_context(sources, graph_context=graph_context)

    assert "Entity Relationships:" in context
    assert "[Jordan Lee] --(worked with)--> [Maya Patel]" in context
    assert "Document Excerpts:" in context
    assert "[1] doc1.txt, page 1" in context
    assert "[2] doc2.txt, page 2" in context


def test_multihop_retrieval_across_documents_boosts_bridging_chunks(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    # Doc 1: Jordan Lee collaborates with Maya Patel
    doc1_content = "Jordan Lee collaborated with Maya Patel on infrastructure migrations."
    p1 = store.upload_dir / "apollo.txt"
    p1.write_text(doc1_content)
    store.add_document(
        document_id="doc-1",
        filename="apollo.txt",
        content_type="text/plain",
        stored_path=p1,
        digest="d1",
        size_bytes=len(doc1_content),
        chunks=[Chunk(0, 1, doc1_content, ("Jordan Lee", "Maya Patel"))],
        people={"Jordan Lee": 1, "Maya Patel": 1},
        owner_id="user-1",
    )

    # Doc 2: Maya Patel directs Project Apollo
    doc2_content = "Maya Patel leads Project Apollo and oversees deliverables."
    p2 = store.upload_dir / "projects.txt"
    p2.write_text(doc2_content)
    store.add_document(
        document_id="doc-2",
        filename="projects.txt",
        content_type="text/plain",
        stored_path=p2,
        digest="d2",
        size_bytes=len(doc2_content),
        chunks=[Chunk(0, 1, doc2_content, ("Maya Patel",))],
        people={"Maya Patel": 1},
        owner_id="user-1",
    )

    # Doc 3: Unrelated
    doc3_content = "Elliot Chen manages the vendor relationship and presents progress every Friday."
    p3 = store.upload_dir / "unrelated.txt"
    p3.write_text(doc3_content)
    store.add_document(
        document_id="doc-3",
        filename="unrelated.txt",
        content_type="text/plain",
        stored_path=p3,
        digest="d3",
        size_bytes=len(doc3_content),
        chunks=[Chunk(0, 1, doc3_content, ("Elliot Chen",))],
        people={"Elliot Chen": 1},
        owner_id="user-1",
    )

    # Multi-hop question: Connecting Jordan Lee and Project Apollo via Maya
    people, sources, mode, graph_ctx = hybrid_retrieve(
        store,
        "Who worked with Jordan on Project Apollo through Maya?",
        document_ids=["doc-1", "doc-2", "doc-3"],
        explicit_person=None,
        top_k=3,
        owner_id="user-1",
        graphrag_enabled=True,
        graphrag_depth=2,
        return_graph_context=True,
    )

    source_files = {s["filename"] for s in sources}
    # Both Doc 1 and Doc 2 must be retrieved in top sources
    assert "apollo.txt" in source_files
    assert "projects.txt" in source_files
    assert len(sources) >= 2

    # Verify graph context contains the multi-hop connection
    assert "Jordan Lee" in graph_ctx
    assert "Maya Patel" in graph_ctx
    assert "Project Apollo" in graph_ctx


def test_graphrag_config_toggle_disables_expansion(tmp_path):
    store = Store(tmp_path)
    store.initialize()

    p1 = store.upload_dir / "apollo.txt"
    p1.write_text("Jordan Lee collaborated with Maya Patel.")
    store.add_document(
        document_id="doc-1",
        filename="apollo.txt",
        content_type="text/plain",
        stored_path=p1,
        digest="d1",
        size_bytes=40,
        chunks=[Chunk(0, 1, "Jordan Lee collaborated with Maya Patel.", ("Jordan Lee", "Maya Patel"))],
        people={"Jordan Lee": 1, "Maya Patel": 1},
        owner_id="user-1",
    )

    # When graphrag_enabled=False, graph_ctx should be empty
    people, sources, mode, graph_ctx = hybrid_retrieve(
        store,
        "Who worked with Jordan?",
        document_ids=["doc-1"],
        explicit_person=None,
        top_k=2,
        owner_id="user-1",
        graphrag_enabled=False,
        return_graph_context=True,
    )
    assert graph_ctx == ""


def test_api_chat_graphrag_flow(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHRAG_ENABLED", "true")
    monkeypatch.setenv("GRAPHRAG_DEPTH", "2")

    app = create_app(tmp_path)
    with TestClient(app) as client:
        # Upload Doc 1: Alice and Acme
        doc1_text = b"Alice Smith was appointed as CTO at Acme Labs in 2021."
        resp1 = client.post(
            "/api/documents",
            files={"file": ("doc1.txt", doc1_text, "text/plain")},
        )
        assert resp1.status_code == 201

        # Upload Doc 2: Bob and Acme
        doc2_text = b"Bob Jones works as Lead Architect at Acme Labs."
        resp2 = client.post(
            "/api/documents",
            files={"file": ("doc2.txt", doc2_text, "text/plain")},
        )
        assert resp2.status_code == 201

        # Ask multi-hop question connecting Alice and Bob
        chat_resp = client.post(
            "/api/chat",
            json={"message": "What companies connect Alice and Bob?"},
        )
        assert chat_resp.status_code == 200
        payload = chat_resp.json()

        # Sources should contain both documents
        retrieved_files = {s["filename"] for s in payload["sources"]}
        assert "doc1.txt" in retrieved_files
        assert "doc2.txt" in retrieved_files

        # Graph context should be present in payload
        assert "graph_context" in payload
        assert "Acme Labs" in payload["graph_context"]
