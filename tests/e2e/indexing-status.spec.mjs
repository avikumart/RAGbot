import { expect, test } from "@playwright/test";

const degradedDocument = {
  id: "degraded-document",
  filename: "failed.txt",
  content_type: "text/plain",
  size_bytes: 37,
  uploaded_at: "2026-08-01T12:00:00Z",
  chunk_count: 1,
  people: ["Jordan Lee"],
  index_status: "needs_reindex",
  index_error:
    "Document embeddings could not be generated. Retry indexing and check the status again.",
  index_updated_at: "2026-08-01T12:00:01Z",
};

test("a degraded upload shows Needs repair and remains available to chat", async ({ page }) => {
  let uploaded = false;
  const session = {
    id: "session-1",
    topic: "New conversation",
    document_ids: [degradedDocument.id],
    person: null,
    created_at: "2026-08-01T12:00:00Z",
    updated_at: "2026-08-01T12:00:00Z",
  };
  let savedMessages = [];

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;

    if (path === "/api/health") {
      await route.fulfill({ json: { status: "degraded" } });
      return;
    }
    if (path === "/api/documents" && request.method() === "POST") {
      uploaded = true;
      await route.fulfill({ status: 201, json: degradedDocument });
      return;
    }
    if (path === "/api/documents") {
      await route.fulfill({ json: uploaded ? [degradedDocument] : [] });
      return;
    }
    if (path === "/api/people") {
      await route.fulfill({
        json: uploaded
          ? [{ normalized: "jordan lee", name: "Jordan Lee", mentions: 1, document_count: 1 }]
          : [],
      });
      return;
    }
    if (path === "/api/sessions" && request.method() === "GET") {
      await route.fulfill({ json: { sessions: savedMessages.length ? [session] : [], next_cursor: null } });
      return;
    }
    if (path === "/api/sessions" && request.method() === "POST") {
      await route.fulfill({ status: 201, json: session });
      return;
    }
    if (path === "/api/sessions/session-1" && request.method() === "GET") {
      await route.fulfill({ json: { ...session, messages: savedMessages } });
      return;
    }
    if (path === "/api/chat") {
      const requestBody = request.postDataJSON();
      const createdAt = "2026-08-01T12:00:02Z";
      const response = {
          session_id: session.id,
          topic: "What does Jordan Lee own?",
          answer: "Jordan Lee owns the rollout plan [1].",
          mode: "local-grounded",
          retrieval_mode: "lexical-fallback",
          sources: [
            {
              index: 1,
              document_id: degradedDocument.id,
              filename: degradedDocument.filename,
              page: null,
              excerpt: "Jordan Lee owns the rollout plan.",
              score: 1,
            },
          ],
          user_message: {
            id: "user-message-1",
            ordinal: 0,
            role: "user",
            content: requestBody.message,
            sources: [],
            mode: null,
            retrieval_mode: null,
            created_at: createdAt,
          },
          assistant_message: {
            id: "assistant-message-1",
            ordinal: 1,
            role: "assistant",
            content: "Jordan Lee owns the rollout plan [1].",
            sources: [
              {
                index: 1,
                document_id: degradedDocument.id,
                filename: degradedDocument.filename,
                page: null,
                excerpt: "Jordan Lee owns the rollout plan.",
                score: 1,
              },
            ],
            mode: "local-grounded",
            retrieval_mode: "lexical-fallback",
            created_at: createdAt,
          },
        };
      session.topic = response.topic;
      session.updated_at = createdAt;
      savedMessages = [response.user_message, response.assistant_message];
      await route.fulfill({ json: response });
      return;
    }

    await route.abort();
  });

  await page.goto("/");
  await expect(page.getByText("Your uploaded documents will appear here.")).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: "failed.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Jordan Lee owns the rollout plan."),
  });

  await expect(page.getByText("Needs repair", { exact: true })).toBeVisible();
  await expect(page.locator(".notice")).toContainText(
    "uploaded in lexical-only mode, but its semantic index needs repair",
  );
  await expect(page.locator(".notice")).not.toContainText("uploaded and ready");

  const question = page.getByRole("textbox", { name: "Your question" });
  await expect(question).toBeEnabled();
  await question.fill("What does Jordan Lee own?");
  await page.getByRole("button", { name: "Send question" }).click();

  await expect(page.locator(".message.assistant .answer-text")).toContainText(
    "Jordan Lee owns the rollout plan",
  );
  await expect(page.locator(".message.assistant .source-list")).toContainText("failed.txt");

  await page.reload();
  await expect(page.locator(".message.assistant .answer-text")).toContainText(
    "Jordan Lee owns the rollout plan",
  );
  await page.getByRole("button", { name: "New", exact: true }).click();
  await expect(page.getByText("PERSON-AWARE RETRIEVAL")).toBeVisible();
  await expect(page.getByText("What does Jordan Lee own?", { exact: true })).toBeVisible();
});
