import assert from "node:assert/strict";
import test from "node:test";

import { API_ERROR_MESSAGE, api, getDocumentFileUrl, parseApiError } from "../lib/api.ts";

function jsonResponse(payload) {
  return new Response(JSON.stringify(payload), {
    status: 400,
    headers: { "content-type": "application/json" },
  });
}

test("parses a string API error detail", async () => {
  const message = await parseApiError(jsonResponse({ detail: "The document is too large." }));

  assert.equal(message, "The document is too large.");
});

test("parses FastAPI validation error details", async () => {
  const message = await parseApiError(jsonResponse({
    detail: [
      { loc: ["body", "file"], msg: "Field required", type: "missing" },
      { loc: ["body", "file"], msg: "Unsupported file type", type: "value_error" },
    ],
  }));

  assert.equal(message, "Field required Unsupported file type");
});

test("uses a safe fallback for non-JSON and unrecognized errors", async () => {
  const htmlMessage = await parseApiError(new Response("Bad gateway", { status: 502 }));
  const unknownMessage = await parseApiError(jsonResponse({ detail: { code: "bad_file" } }));

  assert.equal(htmlMessage, API_ERROR_MESSAGE);
  assert.equal(unknownMessage, API_ERROR_MESSAGE);
});

test("routes /api/health to same-origin path", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return new Response(JSON.stringify({ status: "ok" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const result = await api("/api/health");
    assert.deepEqual(result, { status: "ok" });
    assert.equal(requestedUrl, "/api/health");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("getDocumentFileUrl returns correct endpoint path", () => {
  assert.equal(getDocumentFileUrl("doc-123"), "/api/documents/doc-123/file");
});

test("fetchPersonTimeline requests correct endpoint with url encoding and document scoping", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = null;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return new Response(JSON.stringify([{
      id: "ev-1",
      document_id: "doc-1",
      filename: "test.pdf",
      entity_name: "Maya Patel",
      event_text: "Graduated in 2018",
      event_date: "2018",
      chunk_id: 1,
      page: 1,
    }]), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  try {
    const { fetchPersonTimeline } = await import("../lib/api.ts");
    const result = await fetchPersonTimeline("Maya Patel", "doc-1");
    assert.equal(requestedUrl, "/api/people/Maya%20Patel/timeline?document_id=doc-1");
    assert.equal(result.length, 1);
    assert.equal(result[0].event_date, "2018");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("collection API client helpers route to /api/collections endpoints and scope graph/timeline", async () => {
  const originalFetch = globalThis.fetch;
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    return new Response(
      JSON.stringify({
        id: "col-1",
        name: "Phoenix",
        description: "Migration docs",
        created_at: "2026-08-01T12:00:00Z",
        document_ids: ["doc-1"],
        document_count: 1,
        nodes: [],
        edges: [],
        deleted: "col-1",
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  };

  try {
    const {
      createCollection,
      deleteCollection,
      fetchGraph,
      fetchPersonTimeline,
      updateCollection,
      updateCollectionDocuments,
    } = await import("../lib/api.ts");

    await createCollection({ name: "Phoenix", description: "Migration docs", document_ids: ["doc-1"] });
    assert.equal(calls[0].url, "/api/collections");
    assert.equal(calls[0].method, "POST");
    assert.deepEqual(calls[0].body, {
      name: "Phoenix",
      description: "Migration docs",
      document_ids: ["doc-1"],
    });

    await updateCollection("col-1", { name: "Phoenix v2" });
    assert.equal(calls[1].url, "/api/collections/col-1");
    assert.equal(calls[1].method, "PATCH");

    await updateCollectionDocuments("col-1", { add_document_ids: ["doc-2"] });
    assert.equal(calls[2].url, "/api/collections/col-1/documents");
    assert.equal(calls[2].method, "POST");
    assert.deepEqual(calls[2].body, { add_document_ids: ["doc-2"] });

    await fetchGraph(undefined, undefined, "col-1");
    assert.equal(calls[3].url, "/api/graph?collection_id=col-1");

    await fetchPersonTimeline("Jordan Lee", undefined, "col-1");
    assert.equal(calls[4].url, "/api/people/Jordan%20Lee/timeline?collection_id=col-1");

    await deleteCollection("col-1");
    assert.equal(calls[5].url, "/api/collections/col-1");
    assert.equal(calls[5].method, "DELETE");
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("generatePersonDossier requests POST /api/people/{name}/dossier with url encoding and scoping", async () => {
  const originalFetch = globalThis.fetch;
  let requestedUrl = null;
  let requestedMethod = null;
  let requestedBody = null;
  globalThis.fetch = async (url, init = {}) => {
    requestedUrl = url;
    requestedMethod = init.method;
    requestedBody = init.body ? JSON.parse(init.body) : null;
    return new Response(
      JSON.stringify({
        entity_name: "Maya Patel",
        generated_at: "2026-10-14T00:00:00Z",
        scope: { document_ids: ["doc-1"], summary: "1 document" },
        executive_summary: "Executive summary text.",
        sections: [],
        sources: [],
        markdown: "# Executive Briefing: Maya Patel",
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    );
  };
  try {
    const { generatePersonDossier } = await import("../lib/api.ts");
    const result = await generatePersonDossier("Maya Patel", { documentId: "doc-1", collectionId: "col-1" });
    assert.equal(requestedMethod, "POST");
    assert.equal(requestedUrl, "/api/people/Maya%20Patel/dossier?document_id=doc-1&collection_id=col-1");
    assert.equal(requestedBody, null);
    assert.equal(result.entity_name, "Maya Patel");
    assert.equal(result.markdown, "# Executive Briefing: Maya Patel");

    await generatePersonDossier("Maya Patel", { documentIds: ["doc-1", "doc-2"] });
    assert.deepEqual(requestedBody, { document_ids: ["doc-1", "doc-2"] });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
