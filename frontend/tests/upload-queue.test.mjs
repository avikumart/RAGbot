import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { UploadQueue } from "../components/upload-queue.mjs";

test("UploadQueue renders null when queue is empty", () => {
  const html = renderToStaticMarkup(
    React.createElement(UploadQueue, { items: [], onRetry: () => {}, onClear: () => {} })
  );
  assert.equal(html, "");
});

test("UploadQueue renders items with their statuses, progress, and retry actions", () => {
  const items = [
    { id: "1", name: "report.pdf", size: 1024, status: "uploading" },
    { id: "2", name: "notes.txt", size: 2048, status: "ready" },
    { id: "3", name: "broken.xyz", size: 512, status: "error", error: "Unsupported file type" },
  ];

  const html = renderToStaticMarkup(
    React.createElement(UploadQueue, { items, onRetry: () => {}, onClear: () => {} })
  );

  assert.match(html, /Upload queue/);
  assert.match(html, /report\.pdf/);
  assert.match(html, /Uploading…/);
  assert.match(html, /notes\.txt/);
  assert.match(html, /✓ Ready/);
  assert.match(html, /broken\.xyz/);
  assert.match(html, /Unsupported file type/);
  assert.match(html, /Retry/);
});
