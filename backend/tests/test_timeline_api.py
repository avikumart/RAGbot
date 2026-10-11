import hashlib
import hmac
import io
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


def test_timeline_endpoint_and_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PROXY_SECRET", "test-proxy-secret")
    app = create_app(tmp_path)
    with TestClient(app) as client:
        headers = owner_headers("alice")

        doc_text = (
            "Maya Patel graduated from Stanford University in 2018. "
            "In September 2020, Maya joined Acme Corp as Principal AI Architect. "
            "Acme Corp acquired DataWave in 2022. "
            "In 2023, Maya launched the Quantum Project."
        )
        res = client.post(
            "/api/documents",
            files={"file": ("resume.txt", io.BytesIO(doc_text.encode("utf-8")), "text/plain")},
            headers=headers,
        )
        assert res.status_code == 201
        doc_id = res.json()["id"]

        # 1. Query Maya Patel's timeline
        t_res = client.get("/api/people/Maya%20Patel/timeline", headers=headers)
        assert t_res.status_code == 200
        events = t_res.json()
        assert len(events) >= 3

        # Check chronological order
        event_dates = [ev["event_date"] for ev in events]
        assert event_dates == ["2018", "September 2020", "2023"]

        # Check fields and chunk linking
        first_ev = events[0]
        assert first_ev["entity_name"] == "Maya Patel"
        assert "2018" in first_ev["event_date"]
        assert first_ev["document_id"] == doc_id
        assert first_ev["filename"] == "resume.txt"
        assert first_ev["chunk_id"] is not None
        assert first_ev["chunk_content"] is not None
        assert first_ev["source_chunk"]["id"] == first_ev["chunk_id"]
        assert first_ev["source_chunk"]["content"] == first_ev["chunk_content"]

        # 2. Query by alias (first name)
        alias_res = client.get("/api/people/Maya/timeline", headers=headers)
        assert alias_res.status_code == 200
        alias_events = alias_res.json()
        assert len(alias_events) >= 3

        # 3. Query Acme Corp's timeline
        org_res = client.get("/api/people/Acme%20Corp/timeline", headers=headers)
        assert org_res.status_code == 200
        org_events = org_res.json()
        assert any("2020" in ev["event_date"] for ev in org_events)
        assert any("2022" in ev["event_date"] for ev in org_events)

        # 4. Scope by document_id
        scoped_res = client.get(f"/api/people/Maya%20Patel/timeline?document_id={doc_id}", headers=headers)
        assert scoped_res.status_code == 200
        assert len(scoped_res.json()) >= 3

        unscoped_res = client.get("/api/people/Maya%20Patel/timeline?document_id=nonexistent", headers=headers)
        assert unscoped_res.status_code == 200
        assert unscoped_res.json() == []

        # 5. Multi-tenant isolation: other user sees empty timeline
        bob_headers = owner_headers("bob")
        bob_res = client.get("/api/people/Maya%20Patel/timeline", headers=bob_headers)
        assert bob_res.status_code == 200
        assert bob_res.json() == []

        # 6. Deletion cascades
        del_res = client.delete(f"/api/documents/{doc_id}", headers=headers)
        assert del_res.status_code == 200

        after_del = client.get("/api/people/Maya%20Patel/timeline", headers=headers)
        assert after_del.status_code == 200
        assert after_del.json() == []
