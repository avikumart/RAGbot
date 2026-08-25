import { expect, test } from "@playwright/test";

const timestamp = "2026-08-01T12:00:00Z";

function documentRecord(id, filename, people) {
  return {
    id,
    filename,
    content_type: "text/plain",
    size_bytes: 42,
    uploaded_at: timestamp,
    chunk_count: 1,
    people,
    index_status: "ready",
    index_error: null,
    index_updated_at: timestamp,
  };
}

function personRecord(name) {
  return {
    normalized: name.toLowerCase(),
    name,
    mentions: 1,
    document_count: 1,
  };
}

function source(index, document, excerpt, score = 0.96) {
  return {
    index,
    document_id: document.id,
    filename: document.filename,
    page: null,
    excerpt,
    score,
  };
}

test("streams tokens and metadata in real-time via Server-Sent Events", async ({ page }) => {
  const doc = documentRecord("doc-1", "notes.txt", ["Jordan Lee"]);
  const people = [personRecord("Jordan Lee")];

  await page.addInitScript(() => localStorage.clear());

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());

    if (pathname === "/api/health") {
      await route.fulfill({ json: { status: "ok" } });
      return;
    }
    if (pathname === "/api/documents" && request.method() === "GET") {
      await route.fulfill({ json: [doc] });
      return;
    }
    if (pathname === "/api/people") {
      await route.fulfill({ json: people });
      return;
    }
    if (pathname === "/api/sessions" && request.method() === "GET") {
      await route.fulfill({ json: { sessions: [], next_cursor: null } });
      return;
    }
    if (pathname === "/api/sessions" && request.method() === "POST") {
      const body = request.postDataJSON();
      const session = {
        id: "session-1",
        topic: "New conversation",
        document_ids: body.document_ids ?? [],
        person: body.person ?? null,
        created_at: timestamp,
        updated_at: timestamp,
      };
      await route.fulfill({ status: 201, json: session });
      return;
    }
    if (pathname === "/api/chat") {
      const body = request.postDataJSON();
      const sseBody = [
        "event: metadata",
        `data: ${JSON.stringify({ sources: [source(1, doc, "Jordan Lee owns the rollout plan.")], people: ["Jordan Lee"], mode: "cerebras:gpt-oss-120b", retrieval_mode: "hybrid" })}`,
        "",
        "event: token",
        `data: ${JSON.stringify({ delta: "Jordan " })}`,
        "",
        "event: token",
        `data: ${JSON.stringify({ delta: "owns the rollout plan [1]." })}`,
        "",
        "event: complete",
        `data: ${JSON.stringify({
          session_id: "session-1",
          topic: body.message,
          user_message: {
            id: `user-${body.client_message_id}`,
            ordinal: 0,
            role: "user",
            content: body.message,
            sources: [],
            mode: null,
            retrieval_mode: null,
            created_at: timestamp,
          },
          assistant_message: {
            id: `assistant-${body.client_message_id}`,
            ordinal: 1,
            role: "assistant",
            content: "Jordan owns the rollout plan [1].",
            sources: [source(1, doc, "Jordan Lee owns the rollout plan.")],
            mode: "cerebras:gpt-oss-120b",
            retrieval_mode: "hybrid",
            created_at: timestamp,
          },
          answer: "Jordan owns the rollout plan [1].",
        })}`,
        "",
      ].join("\n");

      await route.fulfill({
        status: 200,
        headers: {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache",
        },
        body: sseBody,
      });
      return;
    }
    await route.abort();
  });

  await page.goto("/");
  await expect(page.locator(".connection-pill")).not.toHaveText("Connecting");

  const composer = page.getByRole("textbox", { name: "Your question" });
  await composer.fill("What does Jordan own?");
  await page.getByRole("button", { name: "Send question" }).click();

  await expect(page.locator(".message.assistant")).toContainText("Jordan owns the rollout plan");
  await expect(page.locator(".source-card")).toContainText("notes.txt");
  await expect(page.locator(".answer-mode")).toContainText("Cerebras");
});
