# API Reference

The Personagraph backend exposes a RESTful FastAPI interface. When deployed in production, access is routed through the same-origin Next.js/Vinext frontend proxy to enforce cryptographic request signing.

---

## Base URLs

- **Local Development API**: `http://localhost:8000`
- **Frontend Reverse Proxy**: `http://localhost:3000/api`
- **OpenAPI Interactive Documentation**: `http://localhost:8000/docs`

---

## Authentication & Proxy Headers

The frontend signs owner identities using HMAC-SHA256 with a shared `AUTH_PROXY_SECRET`.

| Header | Description |
| :--- | :--- |
| `x-personagraph-owner` | SHA-256 hash of the authenticated user identity (`personagraph-owner:v1:<id>`). |
| `x-personagraph-owner-timestamp` | Unix timestamp in seconds (valid for 300s clock skew window). |
| `x-personagraph-owner-signature` | HMAC-SHA256 hex digest of `${owner}:${timestamp}`. |

*In local development without `AUTH_PROXY_SECRET`, the API defaults to the `LOCAL_DEVELOPMENT_OWNER` identity.*

---

## Endpoints

### 1. System Health

```http
GET /api/health
```

#### Response (`200 OK`)
```json
{
  "status": "ok",
  "service": "personagraph-api",
  "components": {
    "api": { "status": "ready" },
    "sqlite": { "status": "ready", "error": null },
    "vector_database": { "status": "ready", "error": null },
    "embedding_model": {
      "status": "ready",
      "model": "BAAI/bge-small-en-v1.5",
      "dimensions": 384,
      "error": null
    }
  }
}
```

---

### 2. Document Library

#### List Documents
```http
GET /api/documents
```

#### Response (`200 OK`)
```json
[
  {
    "id": "e4b2d183...",
    "filename": "team-profiles.pdf",
    "content_type": "application/pdf",
    "size_bytes": 142850,
    "uploaded_at": "2026-08-19T10:00:00Z",
    "chunk_count": 12,
    "people": ["Alice Chen", "Bob Smith"],
    "index_status": "ready",
    "index_error": null,
    "index_updated_at": "2026-08-19T10:00:05Z"
  }
]
```

#### Upload Document
```http
POST /api/documents
Content-Type: multipart/form-data
```
- `file`: Multipart binary upload (PDF, DOCX, TXT, MD up to 10 MB).

#### Response (`201 Created`)
Returns the created `DocumentRecord`.

#### Delete Document
```http
DELETE /api/documents/{document_id}
```

#### Response (`200 OK`)
```json
{ "deleted": true }
```

---

### 3. People & Entities

```http
GET /api/people
GET /api/people?document_id=e4b2d183...
```

#### Response (`200 OK`)
```json
[
  {
    "name": "Alice Chen",
    "normalized": "alice chen",
    "mentions": 8,
    "document_count": 2
  }
]
```

---

### 4. Chat Sessions

#### List Sessions
```http
GET /api/sessions?limit=30&cursor={cursor_token}
```

#### Create Session
```http
POST /api/sessions
Content-Type: application/json

{
  "topic": "Project Architecture",
  "document_ids": ["e4b2d183..."],
  "person": "Alice Chen"
}
```

#### Get Session (with Messages)
```http
GET /api/sessions/{session_id}
```

#### Update Session
```http
PATCH /api/sessions/{session_id}
Content-Type: application/json

{
  "topic": "Updated Topic",
  "person": null
}
```

#### Delete Session
```http
DELETE /api/sessions/{session_id}
```
*Returns `204 No Content`.*

---

### 5. Chat Turn (Question Answering)

```http
POST /api/chat
Content-Type: application/json

{
  "message": "What is Alice's role in the architecture team?",
  "session_id": "session-1234...",
  "document_ids": ["e4b2d183..."],
  "person": "Alice Chen",
  "top_k": 4,
  "client_message_id": "client-uuid-..."
}
```

#### Response (`200 OK`)
```json
{
  "session_id": "session-1234...",
  "topic": "Alice's role in the architecture team",
  "answer": "Alice Chen serves as the Principal System Architect [1] leading the platform migration [2].",
  "people": ["Alice Chen"],
  "mode": "cerebras:gpt-oss-120b",
  "retrieval_mode": "hybrid",
  "sources": [
    {
      "index": 1,
      "document_id": "e4b2d183...",
      "filename": "team-profiles.pdf",
      "page": 3,
      "excerpt": "Alice Chen joined in 2024 as Principal System Architect overseeing distributed systems...",
      "score": 1.0
    },
    {
      "index": 2,
      "document_id": "e4b2d183...",
      "filename": "team-profiles.pdf",
      "page": 4,
      "excerpt": "Under Alice's technical guidance, the platform migration completed on schedule...",
      "score": 0.88
    }
  ],
  "user_message": {
    "id": "msg-user-...",
    "role": "user",
    "content": "What is Alice's role in the architecture team?",
    "created_at": "2026-08-19T10:05:00Z"
  },
  "assistant_message": {
    "id": "msg-asst-...",
    "role": "assistant",
    "content": "Alice Chen serves as the Principal System Architect [1] leading the platform migration [2].",
    "sources": [ ... ],
    "mode": "cerebras:gpt-oss-120b",
    "retrieval_mode": "hybrid",
    "created_at": "2026-08-19T10:05:02Z"
  }
}
```
