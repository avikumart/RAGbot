import hashlib
import hmac
import io
import re
from datetime import UTC, datetime
from fastapi.testclient import TestClient

from app.main import create_app, opaque_owner_id


def owner_headers(identity: str, secret: str = "test-proxy-secret"):
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


def test_dossier_generation_schema_and_grounding(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PROXY_SECRET", "test-proxy-secret")
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = owner_headers("alice")

        doc_text = (
            "Maya Patel graduated from Stanford University with a degree in Computer Science in 2018. "
            "In September 2020, Maya joined Acme Corp as Principal AI Architect. "
            "Maya Patel collaborates with Jordan Lee on distributed machine learning systems. "
            "In 2023, Maya launched the Quantum Project to optimize neural network inference. "
            "Maya Patel stated: \"Reliability and test coverage must precede feature rollout at scale.\" "
            "She also remarked that data integrity is essential for user trust."
        )

        res = client.post(
            "/api/documents",
            files={"file": ("profile.txt", io.BytesIO(doc_text.encode("utf-8")), "text/plain")},
            headers=headers,
        )
        assert res.status_code == 201
        doc_id = res.json()["id"]

        # 1. Generate dossier via POST /api/people/Maya%20Patel/dossier
        dossier_res = client.post("/api/people/Maya%20Patel/dossier", headers=headers)
        assert dossier_res.status_code == 200
        data = dossier_res.json()

        # 2. Verify Schema
        assert data["entity_name"] == "Maya Patel"
        assert "generated_at" in data
        assert "executive_summary" in data and len(data["executive_summary"]) > 0
        assert "sections" in data and len(data["sections"]) == 4
        assert "sources" in data and len(data["sources"]) > 0
        assert "markdown" in data and len(data["markdown"]) > 0

        section_ids = [s["id"] for s in data["sections"]]
        assert section_ids == ["biography", "relationships", "projects", "quotes"]

        # 3. Verify Source Grounding & Excerpt IDs
        source_indices = {s["index"] for s in data["sources"]}
        source_excerpt_ids = {s["id"] for s in data["sources"]}
        assert all(isinstance(s["id"], int) for s in data["sources"])

        for section in data["sections"]:
            assert "title" in section
            assert "content" in section
            assert "citations" in section
            assert "excerpt_ids" in section
            # Every citation index in section references a verified source
            for cite in section["citations"]:
                assert cite in source_indices
            for excerpt_id in section["excerpt_ids"]:
                assert excerpt_id in source_excerpt_ids

        # 4. Verify Content & Grounded Claims
        bio = next(s for s in data["sections"] if s["id"] == "biography")
        assert "Stanford" in bio["content"] or "Principal AI Architect" in bio["content"]
        assert len(bio["citations"]) > 0

        rel = next(s for s in data["sections"] if s["id"] == "relationships")
        assert "Jordan Lee" in rel["content"] or "Acme Corp" in rel["content"]
        assert len(rel["citations"]) > 0

        proj = next(s for s in data["sections"] if s["id"] == "projects")
        assert "Quantum Project" in proj["content"]
        assert len(proj["citations"]) > 0

        quotes = next(s for s in data["sections"] if s["id"] == "quotes")
        assert "Reliability" in quotes["content"] or "data integrity" in quotes["content"]
        assert len(quotes["citations"]) > 0

        # 5. Verify Markdown Output
        md = data["markdown"]
        assert "# Executive Briefing: Maya Patel" in md
        assert "## Executive Summary" in md
        assert "## 1. Biography & Current Roles" in md
        assert "## 2. Key Relationships & Network" in md
        assert "## 3. Projects & Key Accomplishments" in md
        assert "## 4. Direct Statements & Positions" in md
        assert "### Verified Document Sources" in md
        assert "Excerpt ID:" in md

        # Verify citation brackets in markdown reference valid sources
        bracketed_cites = [int(m) for m in re.findall(r"\[(\d+)\]", md)]
        assert len(bracketed_cites) > 0
        for cite in bracketed_cites:
            assert cite in source_indices

        # 6. Entity Alias Resolution (querying by first name "Maya")
        alias_res = client.post("/api/people/Maya/dossier", headers=headers)
        assert alias_res.status_code == 200
        alias_data = alias_res.json()
        assert alias_data["entity_name"] == "Maya Patel"
        assert len(alias_data["sources"]) > 0

        # 7. Document Scoping
        scoped_res = client.post(
            "/api/people/Maya%20Patel/dossier",
            json={"document_ids": [doc_id]},
            headers=headers,
        )
        assert scoped_res.status_code == 200
        assert scoped_res.json()["scope"]["document_ids"] == [doc_id]

        scoped_empty = client.post(
            "/api/people/Maya%20Patel/dossier",
            json={"document_ids": ["nonexistent-doc-id"]},
            headers=headers,
        )
        assert scoped_empty.status_code == 404

        # 8. Multi-tenant Isolation
        bob_headers = owner_headers("bob")
        bob_res = client.post("/api/people/Maya%20Patel/dossier", headers=bob_headers)
        assert bob_res.status_code == 404

        # 9. Non-existent person
        unknown_res = client.post("/api/people/UnknownPerson/dossier", headers=headers)
        assert unknown_res.status_code == 404
