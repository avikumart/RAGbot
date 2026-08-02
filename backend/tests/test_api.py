from fastapi.testclient import TestClient

from app.main import create_app
from app.vector_store import VectorCandidate


SAMPLE = b"""People notes

Jordan Lee leads the Phoenix migration and owns the rollout plan. Jordan Lee joined the program in 2023.

Maya Patel is the security reviewer. Maya Patel coordinates the access review with Jordan Lee.

Elliot Chen manages the vendor relationship and presents progress every Friday.
"""


def client_with_sample(tmp_path):
    app = create_app(tmp_path)
    client = TestClient(app)
    client.__enter__()
    response = client.post(
        "/api/documents",
        files={"file": ("people-notes.txt", SAMPLE, "text/plain")},
    )
    assert response.status_code == 201, response.text
    return client, response.json()


def test_upload_extracts_people_and_persists_document(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        assert document["filename"] == "people-notes.txt"
        assert document["chunk_count"] >= 1
        assert "Jordan Lee" in document["people"]
        assert "Maya Patel" in document["people"]
        assert document["index_status"] == "disabled"
        assert document["index_error"] is None
        assert document["index_updated_at"] is not None

        documents = client.get("/api/documents").json()
        people = client.get("/api/people").json()
        assert documents[0]["id"] == document["id"]
        assert documents[0]["index_status"] == "disabled"
        assert documents[0]["index_error"] is None
        assert documents[0]["index_updated_at"] is not None
        assert any(person["name"] == "Jordan Lee" for person in people)
    finally:
        client.__exit__(None, None, None)


def test_documents_endpoint_defaults_missing_index_status(tmp_path):
    client, uploaded = client_with_sample(tmp_path)
    try:
        with client.app.state.store.connect() as connection:
            connection.execute(
                "DELETE FROM vector_index_state WHERE document_id = ?",
                (uploaded["id"],),
            )

        document = client.get("/api/documents").json()[0]
        assert document["index_status"] == "pending"
        assert document["index_error"] is None
        assert document["index_updated_at"] is None
    finally:
        client.__exit__(None, None, None)


def test_chat_retrieves_requested_person_with_citations(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [document["id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "local-grounded"
        assert payload["people"] == ["Jordan Lee"]
        assert payload["sources"]
        assert payload["sources"][0]["filename"] == "people-notes.txt"
        assert "[1]" in payload["answer"]
        assert "rollout plan" in payload["answer"]
    finally:
        client.__exit__(None, None, None)


def test_chat_uses_cerebras_when_api_key_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-api-key")

    async def fake_cerebras(**kwargs):
        assert kwargs["api_key"] == "test-api-key"
        assert kwargs["base_url"] == "https://api.cerebras.ai/v1"
        assert kwargs["model"] == "gpt-oss-120b"
        assert kwargs["sources"]
        return "Jordan Lee owns the rollout plan [1]."

    monkeypatch.setattr("app.main.generate_with_cerebras", fake_cerebras)
    client, document = client_with_sample(tmp_path)
    try:
        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [document["id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "cerebras:gpt-oss-120b"
        assert payload["answer"] == "Jordan Lee owns the rollout plan [1]."
    finally:
        client.__exit__(None, None, None)


def test_chat_honors_document_scope(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        second = client.post(
            "/api/documents",
            files={
                "file": (
                    "separate.txt",
                    b"Jordan Lee won the annual chess tournament.",
                    "text/plain",
                )
            },
        ).json()
        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [document["id"]]},
        ).json()
        assert all(source["document_id"] != second["id"] for source in response["sources"])
        assert "chess" not in response["answer"].lower()
    finally:
        client.__exit__(None, None, None)


def test_empty_library_and_unsupported_file_are_clear(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        chat = client.post("/api/chat", json={"message": "Who is Jordan Lee?"})
        assert chat.status_code == 409
        assert "Upload a document" in chat.json()["detail"]

        upload = client.post(
            "/api/documents",
            files={"file": ("people.csv", b"name,role", "text/csv")},
        )
        assert upload.status_code == 422
        assert "Supported formats" in upload.json()["detail"]


class FakeApiVectors:
    enabled = True

    def __init__(self):
        self.indexed = []
        self.deleted = []
        self.candidates = []

    def health(self):
        return {
            "vector_database": {"status": "ready"},
            "embedding_model": {"status": "ready"},
        }

    def index_document(self, document_id):
        self.indexed.append(document_id)
        return 1, 0

    def search(self, question, document_ids, limit):
        return self.candidates[:limit]

    def delete_document(self, document_id):
        self.deleted.append(document_id)


class FailingApiVectors(FakeApiVectors):
    def index_document(self, document_id):
        raise RuntimeError("Private host qdrant.internal rejected token=secret-value")

    def search(self, question, document_ids, limit):
        raise RuntimeError("Vector search is unavailable")


def test_degraded_upload_reports_repair_and_keeps_lexical_chat_available(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
    vectors = FailingApiVectors()
    app = create_app(tmp_path, vector_service=vectors)
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={"file": ("failed.txt", SAMPLE, "text/plain")},
        )
        assert upload.status_code == 201
        uploaded = upload.json()
        assert uploaded["index_status"] == "needs_reindex"
        assert uploaded["index_status"] != "ready"
        assert uploaded["index_error"] == (
            "Document embeddings could not be generated. Retry indexing and check the status again."
        )
        assert "qdrant.internal" not in upload.text
        assert "secret-value" not in upload.text

        response = client.get("/api/documents")
        assert response.status_code == 200
        document = response.json()[0]
        assert document["index_status"] == "needs_reindex"
        assert document["index_error"] == (
            "Document embeddings could not be generated. Retry indexing and check the status again."
        )
        assert document["index_updated_at"] is not None
        assert "qdrant.internal" not in response.text
        assert "secret-value" not in response.text

        chat = client.post(
            "/api/chat",
            json={
                "message": "What does Jordan Lee own?",
                "document_ids": [uploaded["id"]],
            },
        )
        assert chat.status_code == 200
        payload = chat.json()
        assert payload["retrieval_mode"] == "lexical-fallback"
        assert payload["sources"][0]["filename"] == "failed.txt"
        assert "rollout plan" in payload["answer"]


def test_upload_semantic_retrieval_and_delete_use_vector_layer(tmp_path, monkeypatch):
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
    vectors = FakeApiVectors()
    app = create_app(tmp_path, vector_service=vectors)
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={
                "file": (
                    "rollout.txt",
                    b"Jordan owns the rollout plan.",
                    "text/plain",
                )
            },
        )
        assert upload.status_code == 201
        document_id = upload.json()["id"]
        assert vectors.indexed == [document_id]

        chunk = app.state.store.get_chunks([document_id])[0]
        vectors.candidates = [VectorCandidate(chunk["id"], document_id, 0.95)]
        chat = client.post(
            "/api/chat", json={"message": "Who is responsible for deployment?"}
        )
        assert chat.status_code == 200
        assert chat.json()["retrieval_mode"] == "hybrid"
        assert chat.json()["sources"][0]["filename"] == "rollout.txt"

        deletion = client.delete(f"/api/documents/{document_id}")
        assert deletion.status_code == 200
        assert vectors.deleted == [document_id]
