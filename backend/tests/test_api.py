import hashlib
import hmac
import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from app.llm import LLMProvider, LLMService
from app.main import create_app, opaque_owner_id
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


def test_chat_queries_cerebras_once_for_each_fresh_grounded_question(tmp_path, monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-api-key")
    requests = []

    async def fake_cerebras(**kwargs):
        requests.append(kwargs)
        return f"Grounded answer {len(requests)} [1]."

    monkeypatch.setattr("app.main.generate_with_cerebras", fake_cerebras)
    client, document = client_with_sample(tmp_path)
    try:
        for question in (
            "What does Jordan Lee own?",
            "What does Maya Patel review?",
        ):
            response = client.post(
                "/api/chat",
                json={"message": question, "document_ids": [document["id"]]},
            )
            assert response.status_code == 200
            assert response.json()["mode"] == "cerebras:gpt-oss-120b"

        assert [request["question"] for request in requests] == [
            "What does Jordan Lee own?",
            "What does Maya Patel review?",
        ]
        assert all(request["sources"] for request in requests)
        assert all(
            request["sources"][0]["filename"] == "people-notes.txt"
            for request in requests
        )
    finally:
        client.__exit__(None, None, None)


def test_chat_uses_custom_injected_llm_service(tmp_path):
    class MockCustomProvider(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "mock-provider"

        @property
        def model_name(self) -> str:
            return "v1"

        def is_configured(self) -> bool:
            return True

        async def _send_request(self, client, *, question, context):
            return "Injected provider response [1]."

    custom_service = LLMService(MockCustomProvider())
    app = create_app(tmp_path, llm_service=custom_service)
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={"file": ("people-notes.txt", SAMPLE, "text/plain")},
        ).json()
        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [upload["id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "mock-provider:v1"
        assert payload["answer"] == "Injected provider response [1]."


def test_chat_uses_openai_provider_when_configured(tmp_path, monkeypatch):
    import httpx

    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer test-openai-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "OpenAI generated answer [1]."}}]},
        )

    transport = httpx.MockTransport(handler)
    # We can inject client via provider or test create_app with configured OpenAI
    client_mock = httpx.AsyncClient(transport=transport)

    from app.config import Settings
    from app.llm import create_llm_provider
    settings = Settings.from_env(tmp_path)
    provider = create_llm_provider(settings)

    class TransportProvider(LLMProvider):
        @property
        def provider_name(self) -> str:
            return provider.provider_name

        @property
        def model_name(self) -> str:
            return provider.model_name

        def is_configured(self) -> bool:
            return provider.is_configured()

        async def _send_request(self, client, *, question, context, history=None):
            return await provider._send_request(client_mock, question=question, context=context, history=history)

    app = create_app(tmp_path, llm_service=LLMService(TransportProvider()))
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={"file": ("people-notes.txt", SAMPLE, "text/plain")},
        ).json()
        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [upload["id"]]},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["mode"] == "openai:gpt-4o-mini"
        assert payload["answer"] == "OpenAI generated answer [1]."


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


def test_sessions_are_owned_persistent_and_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PROXY_SECRET", "test-proxy-secret")
    client, document = client_with_sample(tmp_path)
    alice, bob = owner_headers("alice@example.com"), owner_headers("bob@example.com")
    try:
        created = client.post(
            "/api/sessions",
            headers=alice,
            json={"document_ids": [document["id"]], "person": "Jordan Lee"},
        )
        assert created.status_code == 201
        session = created.json()
        assert session["topic"] == "New conversation"

        first = client.post(
            "/api/chat",
            headers=alice,
            json={
                "session_id": session["id"],
                "client_message_id": "message-0001",
                "message": "  What does Jordan Lee own?  ",
                "document_ids": [document["id"]],
            },
        )
        assert first.status_code == 200
        payload = first.json()
        assert payload["session_id"] == session["id"]
        assert payload["topic"] == "What does Jordan Lee own?"
        assert payload["assistant_message"]["sources"][0]["filename"] == "people-notes.txt"
        assert payload["assistant_message"]["retrieval_mode"] == "lexical"

        retry = client.post(
            "/api/chat",
            headers=alice,
            json={
                "session_id": session["id"],
                "client_message_id": "message-0001",
                "message": "What does Jordan Lee own?",
                "document_ids": [document["id"]],
            },
        )
        assert retry.status_code == 200
        assert retry.json()["assistant_message"]["id"] == payload["assistant_message"]["id"]

        loaded = client.get(f"/api/sessions/{session['id']}", headers=alice)
        assert [message["role"] for message in loaded.json()["messages"]] == ["user", "assistant"]
        assert client.get(f"/api/sessions/{session['id']}", headers=bob).status_code == 404
        assert client.patch(
            f"/api/sessions/{session['id']}", headers=bob, json={"topic": "Nope"}
        ).status_code == 404
        assert client.delete(f"/api/sessions/{session['id']}", headers=bob).status_code == 404

        renamed = client.patch(
            f"/api/sessions/{session['id']}", headers=alice, json={"topic": "Jordan rollout"}
        )
        assert renamed.json()["topic"] == "Jordan rollout"
        assert client.delete(f"/api/sessions/{session['id']}", headers=alice).status_code == 204
        with client.app.state.store.connect() as connection:
            assert connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == 0
    finally:
        client.__exit__(None, None, None)


def test_session_listing_is_latest_first_with_deterministic_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTH_PROXY_SECRET", "test-proxy-secret")
    with TestClient(create_app(tmp_path)) as client:
        headers = owner_headers("alice@example.com")
        first = client.post("/api/sessions", headers=headers, json={"topic": "First"}).json()
        second = client.post("/api/sessions", headers=headers, json={"topic": "Second"}).json()
        client.patch(f"/api/sessions/{first['id']}", headers=headers, json={"topic": "First edited"})
        page_one = client.get("/api/sessions?limit=1", headers=headers).json()
        assert page_one["sessions"][0]["id"] == first["id"]
        assert page_one["next_cursor"]
        page_two = client.get(
            f"/api/sessions?limit=1&cursor={page_one['next_cursor']}", headers=headers
        ).json()
        assert page_two["sessions"][0]["id"] == second["id"]


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


def test_delete_succeeds_and_records_cleanup_when_unlink_fails(
    tmp_path, monkeypatch, caplog
):
    monkeypatch.setenv("VECTOR_SEARCH_ENABLED", "true")
    vectors = FakeApiVectors()
    app = create_app(tmp_path, vector_service=vectors)
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={
                "file": (
                    "locked.txt",
                    b"Jordan owns the locked rollout plan.",
                    "text/plain",
                )
            },
        )
        assert upload.status_code == 201
        document_id = upload.json()["id"]
        with app.state.store.connect() as connection:
            stored_path = Path(
                connection.execute(
                    "SELECT stored_path FROM documents WHERE id = ?", (document_id,)
                ).fetchone()["stored_path"]
            )

        def fail_unlink(path, missing_ok=False):
            assert path == stored_path
            assert missing_ok is True
            raise PermissionError("simulated API unlink failure")

        monkeypatch.setattr(Path, "unlink", fail_unlink)
        deletion = client.delete(f"/api/documents/{document_id}")

        assert deletion.status_code == 200
        assert deletion.json() == {"deleted": True}
        assert vectors.deleted == [document_id]
        assert app.state.store.get_document(document_id) is None
        assert stored_path.exists()
        with app.state.store.connect() as connection:
            cleanup = connection.execute(
                """SELECT document_id, attempt_count, last_error
                FROM pending_file_cleanup WHERE stored_path = ?""",
                (str(stored_path),),
            ).fetchone()
        assert cleanup["document_id"] == document_id
        assert cleanup["attempt_count"] == 1
        assert cleanup["last_error"] == "simulated API unlink failure"
        assert "pending cleanup retained" in caplog.text


def test_multi_turn_chat_followup_resolves_pronouns_and_preserves_session_context(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        # Turn 1: Ask about Jordan Lee
        first_resp = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [document["id"]]},
        )
        assert first_resp.status_code == 200
        first_payload = first_resp.json()
        session_id = first_payload["session_id"]
        assert first_payload["people"] == ["Jordan Lee"]
        assert "rollout plan" in first_payload["answer"]

        # Turn 2: Follow-up question with pronoun "they" in the same session
        second_resp = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "message": "When did they join the rollout?",
            },
        )
        assert second_resp.status_code == 200
        second_payload = second_resp.json()
        assert second_payload["session_id"] == session_id
        # Person should be resolved from previous conversation context
        assert second_payload["people"] == ["Jordan Lee"]
        assert len(second_payload["sources"]) > 0

        # Verify session message history
        session_resp = client.get(f"/api/sessions/{session_id}")
        assert session_resp.status_code == 200
        session_data = session_resp.json()
        assert len(session_data["messages"]) == 4
        assert session_data["messages"][0]["role"] == "user"
        assert session_data["messages"][1]["role"] == "assistant"
        assert session_data["messages"][2]["role"] == "user"
        assert session_data["messages"][3]["role"] == "assistant"
    finally:
        client.__exit__(None, None, None)


def test_multi_turn_chat_with_llm_receives_prior_turns(tmp_path):
    received_histories = []

    class MockHistoryProvider(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "history-test"

        @property
        def model_name(self) -> str:
            return "v1"

        def is_configured(self) -> bool:
            return True

        async def _send_request(self, client, *, question, context, history=None):
            received_histories.append(list(history or []))
            return f"Answer for '{question}' [1]."

    custom_service = LLMService(MockHistoryProvider())
    app = create_app(tmp_path, llm_service=custom_service)
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={"file": ("people-notes.txt", SAMPLE, "text/plain")},
        ).json()

        # Turn 1
        t1 = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [upload["id"]]},
        ).json()
        session_id = t1["session_id"]
        assert len(received_histories) == 1
        assert received_histories[0] == []  # No prior history on first turn

        # Turn 2 in same session
        t2 = client.post(
            "/api/chat",
            json={"session_id": session_id, "message": "What else do they manage?"},
        ).json()
        assert t2["session_id"] == session_id
        assert len(received_histories) == 2
        # Prior turn should be in history passed to provider
        assert len(received_histories[1]) == 2
        assert received_histories[1][0]["role"] == "user"
        assert received_histories[1][0]["content"] == "What does Jordan Lee own?"
        assert received_histories[1][1]["role"] == "assistant"


def parse_sse_events(text: str) -> list[tuple[str, dict]]:
    events = []
    current_event = "message"
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            current_event = "message"
            continue
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            data_str = line[5:].strip()
            data = json.loads(data_str)
            events.append((current_event, data))
    return events


def test_chat_sse_streaming_local_fallback(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [document["id"]], "stream": True},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = parse_sse_events(response.text)
        event_types = [e[0] for e in events]
        assert "metadata" in event_types
        assert "token" in event_types
        assert "complete" in event_types

        # Verify metadata
        meta = next(data for ev, data in events if ev == "metadata")
        assert meta["mode"] == "local-grounded"
        assert meta["people"] == ["Jordan Lee"]
        assert len(meta["sources"]) >= 1

        # Verify tokens
        tokens = [data["delta"] for ev, data in events if ev == "token"]
        full_text = "".join(tokens)
        assert "[1]" in full_text

        # Verify complete
        complete = next(data for ev, data in events if ev == "complete")
        assert complete["session_id"]
        assert complete["topic"]
        assert complete["user_message"]["role"] == "user"
        assert complete["assistant_message"]["role"] == "assistant"
        assert complete["answer"] == full_text
    finally:
        client.__exit__(None, None, None)


def test_chat_sse_streaming_accept_header(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        response = client.post(
            "/api/chat",
            headers={"Accept": "text/event-stream"},
            json={"message": "What does Jordan Lee own?", "document_ids": [document["id"]]},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = parse_sse_events(response.text)
        assert any(ev == "metadata" for ev, _ in events)
        assert any(ev == "token" for ev, _ in events)
        assert any(ev == "complete" for ev, _ in events)
    finally:
        client.__exit__(None, None, None)


def test_chat_sse_streaming_custom_provider(tmp_path):
    class MockStreamingProvider(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "stream-test"

        @property
        def model_name(self) -> str:
            return "v1"

        def is_configured(self) -> bool:
            return True

        async def _send_request(self, client, *, question, context, history=None):
            return "Full mock response [1]."

        async def _stream_request(self, client, *, question, context, history=None):
            yield "Mock "
            yield "streamed "
            yield "tokens [1]."

    custom_service = LLMService(MockStreamingProvider())
    app = create_app(tmp_path, llm_service=custom_service)
    with TestClient(app) as client:
        upload = client.post(
            "/api/documents",
            files={"file": ("people-notes.txt", SAMPLE, "text/plain")},
        ).json()

        response = client.post(
            "/api/chat",
            json={"message": "What does Jordan Lee own?", "document_ids": [upload["id"]], "stream": True},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        events = parse_sse_events(response.text)
        tokens = [data["delta"] for ev, data in events if ev == "token"]
        assert "".join(tokens) == "Mock streamed tokens [1]."

        complete = next(data for ev, data in events if ev == "complete")
        assert complete["answer"] == "Mock streamed tokens [1]."
        assert complete["assistant_message"]["mode"] == "stream-test:v1"


def test_chat_sse_streaming_idempotent_replay(tmp_path):
    client, document = client_with_sample(tmp_path)
    try:
        # Create session first
        session = client.post("/api/sessions", json={"topic": "Test replay"}).json()
        session_id = session["id"]

        # Request 1
        r1 = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "client_message_id": "msg-replay-123456",
                "message": "What does Jordan Lee own?",
                "stream": True,
            },
        )
        assert r1.status_code == 200
        events1 = parse_sse_events(r1.text)
        complete1 = next(data for ev, data in events1 if ev == "complete")

        # Request 2 (Idempotent replay)
        r2 = client.post(
            "/api/chat",
            json={
                "session_id": session_id,
                "client_message_id": "msg-replay-123456",
                "message": "What does Jordan Lee own?",
                "stream": True,
            },
        )
        assert r2.status_code == 200
        assert "text/event-stream" in r2.headers["content-type"]
        events2 = parse_sse_events(r2.text)
        complete2 = next(data for ev, data in events2 if ev == "complete")
        assert complete2["assistant_message"]["id"] == complete1["assistant_message"]["id"]
        assert complete2["answer"] == complete1["answer"]
    finally:
        client.__exit__(None, None, None)


