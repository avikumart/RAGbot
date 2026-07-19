from fastapi.testclient import TestClient

from app.main import create_app


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

        documents = client.get("/api/documents").json()
        people = client.get("/api/people").json()
        assert documents[0]["id"] == document["id"]
        assert any(person["name"] == "Jordan Lee" for person in people)
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
