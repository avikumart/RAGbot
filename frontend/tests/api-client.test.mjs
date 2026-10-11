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
