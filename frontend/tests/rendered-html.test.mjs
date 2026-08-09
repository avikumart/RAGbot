import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { DocumentIndexStatus } from "../app/document-index-status.mjs";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the finished Personagraph interface", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>Personagraph — Private document intelligence<\/title>/i);
  assert.match(html, /Ask the people/);
  assert.match(html, /Add a document/);
  assert.match(html, /Check status/);
  assert.match(html, /Local by design/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("renders the four document indexing states accurately", () => {
  const states = [
    ["pending", "indexing", "Indexing"],
    ["ready", "ready", "Ready"],
    ["disabled", "lexical", "Lexical only"],
    ["needs_reindex", "repair", "Needs repair"],
  ];

  for (const [status, tone, label] of states) {
    const html = renderToStaticMarkup(
      React.createElement(DocumentIndexStatus, { status }),
    );
    assert.match(html, new RegExp(`data-index-status="${tone}"`));
    assert.match(html, new RegExp(`>${label}<\\/small>`));
    if (status === "needs_reindex") assert.doesNotMatch(html, />Ready<\/small>/);
  }
});

test("renders an unknown degraded state as needing repair, never ready", () => {
  const html = renderToStaticMarkup(
    React.createElement(DocumentIndexStatus, { status: "degraded" }),
  );

  assert.match(html, /data-index-status="repair"/);
  assert.match(html, />Needs repair<\/small>/);
  assert.doesNotMatch(html, />Ready<\/small>/);
});
