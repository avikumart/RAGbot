# Personagraph Documentation

Welcome to the Personagraph (RAGbot) documentation library. This directory contains detailed architecture guides, technical references, and the development roadmap.

---

## Documentation Index

### 1. Product & Architecture
- **[Product Overview](product.md)**: Value proposition, target use cases, core workflows, and privacy principles.
- **[System Architecture](architecture.md)**: End-to-end design, trust boundaries, runtime topology, and invariant guarantees.
- **[Hybrid Retrieval Engine](retrieval-engine.md)**: Deep dive into the ingestion pipeline, FastEmbed dense retrieval, BM25 lexical search, Reciprocal Rank Fusion, and person boosting.

### 2. Component References
- **[Backend Service](backend.md)**: FastAPI application structure, configuration, lifecycle hooks, and operations.
- **[Frontend Application](frontend.md)**: React 19 / Vinext client, SSR/RSC setup, test suites, and signing proxy boundary.
- **[Database & Storage](database.md)**: Relational schema, ordered migrations (`PRAGMA user_version`), vector storage, and failure-resilient cleanup.
- **[REST API Reference](api-reference.md)**: Endpoint specifications, request/response models, and HMAC proxy authentication.

### 3. Strategy & Evolution
- **[Product Roadmap](roadmap.md)**: Planned phases and tracking GitHub issues ([#37](https://github.com/avikumart/RAGbot/issues/37)–[#47](https://github.com/avikumart/RAGbot/issues/47)).
- **[Architecture Decision Records (ADRs)](adr/README.md)**: Log of architectural decisions and trade-off evaluations.

---

## Quick Start

For full local development with Docker Compose:

```bash
cp .env.example .env
docker compose up --build
```

- **Frontend App**: <http://localhost:3000>
- **API & Swagger Docs**: <http://localhost:8000/docs>
