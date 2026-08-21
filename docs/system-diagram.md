# System Architecture Diagrams

This document contains high-level and detailed architectural diagrams for **Personagraph (RAGbot)**, illustrating runtime topology, component boundaries, document ingestion pipelines, hybrid retrieval orchestration, and security trust zones.

---

## 🏗️ Overall System Architecture

The following diagram depicts the end-to-end component topology, data storage layers, and external integrations of Personagraph:

```mermaid
flowchart TD
    subgraph Client["Client Layer (Browser)"]
        UI["React 19 / Vinext SPA"]
        ChatUI["Interactive Chat & Document Manager"]
    end

    subgraph Security["Edge & Security Layer"]
        Proxy["Vinext API Signing Proxy / Cloudflare Worker"]
        AuthHMAC["HMAC Header Signer (x-personagraph-owner)"]
    end

    subgraph Backend["FastAPI Backend Application"]
        API["FastAPI REST Endpoints"]
        IngestEngine["Ingestion Engine (PDF/DOCX/TXT Parsers)"]
        Chunker["Sliding Window Chunker (Configurable Overlap)"]
        PersonExtractor["Heuristic Person Extractor"]
        RetrievalOrchestrator["Hybrid Retrieval Orchestrator"]
        RRF["Reciprocal Rank Fusion (RRF)"]
        Reranker["Cross-Encoder Reranker"]
    end

    subgraph Storage["Data & Storage Layer"]
        DB[("PostgreSQL / SQLite Database\nAuthoritative Metadata, Chunks, Sessions")]
        FTS5[("SQLite FTS5 Index\nC-Level BM25 Full-Text Index")]
        Qdrant[("Qdrant Vector Engine\nDense Embedding Vectors")]
        Volume[("Upload Storage Volume\nOriginal Managed Files")]
    end

    subgraph LLM["Generative AI Layer"]
        Cerebras["Cerebras Cloud API / Local Synthesis"]
    end

    UI --> Proxy
    ChatUI --> Proxy
    Proxy --> AuthHMAC
    AuthHMAC -- Signed HTTP Requests --> API

    API --> IngestEngine
    IngestEngine --> Chunker
    Chunker --> PersonExtractor
    PersonExtractor --> DB
    Chunker --> Volume
    Chunker --> FTS5
    Chunker --> Qdrant

    API --> RetrievalOrchestrator
    RetrievalOrchestrator -- Parallel Query --> FTS5
    RetrievalOrchestrator -- Parallel Query --> Qdrant
    FTS5 -- Lexical Hits --> RRF
    Qdrant -- Vector Hits --> RRF
    RRF --> Reranker
    Reranker -- Top Evidence Passages --> API

    API --> Cerebras
    Cerebras -- Grounded Response with Citations --> API
```

---

## 📥 Document Ingestion Pipeline

The sequence below details the multi-stage document ingestion workflow from user upload to dual FTS5 and vector indexing:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Frontend as Vinext Signing Proxy
    participant API as FastAPI Backend
    participant Ingestion as Extractor & Chunker
    participant DB as Relational Store (DB)
    participant FTS as FTS5 Virtual Table
    participant Qdrant as Qdrant Vector Service

    User->>Frontend: Upload Document (PDF / DOCX / TXT)
    Frontend->>API: Signed POST /api/documents
    API->>API: Validate file size & SHA256 digest
    API->>Ingestion: Extract pages & split with Sliding Window (Overlap)
    Ingestion->>Ingestion: Extract personal names & entity aliases
    API->>DB: Begin DB Transaction
    DB->>DB: Save Document, Chunks, People & Index State
    API->>FTS: Populate chunks_fts index
    API->>DB: Commit DB Transaction
    API-->>User: Return 201 Created (Status: Pending)

    opt Background Embedding Generation
        API->>Qdrant: Batch upsert dense vector embeddings
        Qdrant-->>API: Success
        API->>DB: Update index_state = ready
    end
```

---

## 🔍 Hybrid Retrieval & Reranking Sequence

The diagram below outlines the multi-stage hybrid search strategy combining BM25 keyword matching, FastEmbed vector search, Reciprocal Rank Fusion (RRF), Person Boosting, and Cross-Encoder rescoring:

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Frontend as Vinext Signing Proxy
    participant API as FastAPI Backend
    participant Retrieval as Hybrid Retrieval Engine
    participant FTS as SQLite FTS5 Engine
    participant Qdrant as Qdrant Vector DB
    participant DB as Authoritative Relational DB
    participant Reranker as Cross-Encoder Reranker
    participant Cerebras as Cerebras LLM API

    User->>Frontend: Submit Chat Question ("What did Maya Patel lead?")
    Frontend->>API: Signed POST /api/chat/completions
    API->>Retrieval: hybrid_retrieve(question, document_ids)
    
    par Parallel Retrieval Candidates
        Retrieval->>FTS: BM25 Full-Text Match Query
        FTS-->>Retrieval: Lexical Ranked Candidates
    and
        Retrieval->>Qdrant: Vector Similarity Search
        Qdrant-->>Retrieval: Vector Ranked Candidates
    end

    Retrieval->>DB: Validate Vector Hits against Scoped Owner Rows
    DB-->>Retrieval: Authorized Chunk Metadata

    Retrieval->>Retrieval: Reciprocal Rank Fusion (RRF) & Person Boosting (+4.0)
    Retrieval->>Reranker: Cross-Encoder Rescoring on Top 20 Candidates
    Reranker-->>Retrieval: Top K Re-ordered Evidence Passages

    API->>Cerebras: Send Query + Grounded Evidence Excerpts
    Cerebras-->>API: Streaming / Synthesized Grounded Response
    API->>DB: Persist Chat Message & Citation Snapshot
    API-->>User: Return Grounded Response with [Index] Citations
```

---

## 🔒 Trust Boundaries & Data Security

```mermaid
flowchart LR
    subgraph UntrustedZone["Untrusted Client Zone"]
        Browser["User Browser"]
    end

    subgraph ProxyZone["Trusted Edge / Signing Zone"]
        Proxy["Vinext Server / Cloudflare Worker\n(HMAC Secret Storage)"]
    end

    subgraph PrivateZone["Isolated Backend Zone"]
        FastAPI["FastAPI Application"]
        DB["Authoritative DB"]
        Qdrant["Vector Storage"]
    end

    Browser -- "HTTP Requests (No Secret Access)" --> Proxy
    Proxy -- "Signed Requests (x-personagraph-owner)" --> FastAPI
    FastAPI -- "Scoped Database Queries" --> DB
    FastAPI -- "Filtered Vector Lookups" --> Qdrant

    style UntrustedZone fill:#fff0f0,stroke:#d9534f
    style ProxyZone fill:#f0f7ff,stroke:#0275d8
    style PrivateZone fill:#f0fff0,stroke:#5cb85c
```
