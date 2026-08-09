import { expect, test } from "@playwright/test";

const timestamp = "2026-08-01T12:00:00Z";

function documentRecord(id, filename, people, overrides = {}) {
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
    ...overrides,
  };
}

function personRecord(name, mentions = 1, documentCount = 1) {
  return {
    normalized: name.toLowerCase(),
    name,
    mentions,
    document_count: documentCount,
  };
}

function source(index, document, excerpt, score = 0.9, page = null) {
  return {
    index,
    document_id: document.id,
    filename: document.filename,
    page,
    excerpt,
    score,
  };
}

function createApiState({ documents = [], people = [], uploads = [], onChat } = {}) {
  return {
    documents: [...documents],
    people: [...people],
    uploads: [...uploads],
    onChat,
    sessions: [],
    messagesBySession: new Map(),
    chatRequests: [],
    uploadRequests: 0,
    chatGate: null,
  };
}

function sessionRecord(id, request) {
  return {
    id,
    topic: "New conversation",
    document_ids: request.document_ids ?? [],
    person: request.person ?? null,
    created_at: timestamp,
    updated_at: timestamp,
  };
}

function responseForChat({ request, session, answer, sources = [], mode = "local-grounded", retrievalMode = "lexical" }) {
  const createdAt = "2026-08-01T12:00:02Z";
  const userMessage = {
    id: `user-${request.client_message_id}`,
    ordinal: 0,
    role: "user",
    content: request.message,
    sources: [],
    mode: null,
    retrieval_mode: null,
    created_at: createdAt,
  };
  const assistantMessage = {
    id: `assistant-${request.client_message_id}`,
    ordinal: 1,
    role: "assistant",
    content: answer,
    sources,
    mode,
    retrieval_mode: retrievalMode,
    created_at: createdAt,
  };
  return {
    answer,
    sources,
    mode,
    retrieval_mode: retrievalMode,
    session_id: session.id,
    topic: request.message,
    user_message: userMessage,
    assistant_message: assistantMessage,
  };
}

async function installApi(page, state) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();

    if (pathname === "/api/health") {
      await route.fulfill({ json: { status: "ok" } });
      return;
    }

    if (pathname === "/api/documents" && method === "GET") {
      await route.fulfill({ json: state.documents });
      return;
    }

    if (pathname === "/api/documents" && method === "POST") {
      state.uploadRequests += 1;
      const upload = state.uploads.shift();
      if (upload?.error) {
        await route.fulfill({ status: upload.error.status, json: { detail: upload.error.detail } });
        return;
      }
      if (!upload?.document) {
        await route.fulfill({ status: 500, json: { detail: "No upload response was configured." } });
        return;
      }
      state.documents = [...state.documents, upload.document];
      if (upload.people) state.people = upload.people;
      await route.fulfill({ status: 201, json: upload.document });
      return;
    }

    if (pathname.startsWith("/api/documents/") && method === "DELETE") {
      const documentId = pathname.split("/").pop();
      state.documents = state.documents.filter((document) => document.id !== documentId);
      const remainingNames = new Set(state.documents.flatMap((document) => document.people));
      state.people = state.people.filter((person) => remainingNames.has(person.name));
      await route.fulfill({ json: { deleted: true } });
      return;
    }

    if (pathname === "/api/people") {
      await route.fulfill({ json: state.people });
      return;
    }

    if (pathname === "/api/sessions" && method === "GET") {
      await route.fulfill({ json: { sessions: state.sessions, next_cursor: null } });
      return;
    }

    if (pathname === "/api/sessions" && method === "POST") {
      const body = request.postDataJSON();
      const session = sessionRecord(`session-${state.sessions.length + 1}`, body);
      state.sessions = [session, ...state.sessions];
      await route.fulfill({ status: 201, json: session });
      return;
    }

    if (pathname.startsWith("/api/sessions/") && method === "GET") {
      const sessionId = pathname.split("/").pop();
      const session = state.sessions.find((item) => item.id === sessionId);
      if (!session) {
        await route.fulfill({ status: 404, json: { detail: "Conversation not found." } });
        return;
      }
      await route.fulfill({ json: { ...session, messages: state.messagesBySession.get(session.id) ?? [] } });
      return;
    }

    if (pathname === "/api/chat") {
      const body = request.postDataJSON();
      const session = state.sessions.find((item) => item.id === body.session_id);
      state.chatRequests.push(body);
      if (state.chatGate) await state.chatGate;
      const outcome = state.onChat
        ? await state.onChat({ request: body, session, state })
        : { answer: "No grounded answer was configured." };
      if (outcome?.error) {
        await route.fulfill({ status: outcome.error.status, json: { detail: outcome.error.detail } });
        return;
      }
      const response = responseForChat({ request: body, session, ...outcome });
      state.messagesBySession.set(session.id, [response.user_message, response.assistant_message]);
      state.sessions = state.sessions.map((item) => item.id === session.id
        ? { ...item, topic: response.topic, updated_at: response.assistant_message.created_at }
        : item);
      await route.fulfill({ json: response });
      return;
    }

    await route.abort();
  });
}

async function openApp(page, state) {
  await page.addInitScript(() => localStorage.clear());
  await installApi(page, state);
  const libraryLoaded = page.waitForResponse((response) => {
    const { pathname } = new URL(response.url());
    return pathname === "/api/documents" && response.request().method() === "GET" && response.ok();
  });
  await page.goto("/");
  await libraryLoaded;
  await expect(page.locator(".connection-pill")).not.toHaveText("Connecting");
}

async function ask(page, question) {
  const composer = page.getByRole("textbox", { name: "Your question" });
  await composer.fill(question);
  await page.getByRole("button", { name: "Send question" }).click();
}

function documentButton(page, filename) {
  return page.locator(".document-row").filter({ hasText: filename }).locator("button.document-item");
}

function personButton(page, name) {
  return page.locator(".people-list").getByRole("button", { name: new RegExp(name) });
}

test.describe("First document workflow", () => {
  test("uploads a supported document, chooses a detected person, and receives cited evidence", async ({ page }) => {
    const notes = documentRecord("people-notes", "people-notes.txt", ["Jordan Lee", "Maya Patel"]);
    const state = createApiState({
      uploads: [{
        document: notes,
        people: [personRecord("Jordan Lee"), personRecord("Maya Patel")],
      }],
      onChat: ({ request }) => {
        expect(request.person).toBe("Jordan Lee");
        expect(request.document_ids).toEqual([notes.id]);
        return {
          answer: "Jordan Lee owns the rollout plan [1].",
          sources: [source(1, notes, "Jordan Lee owns the rollout plan.", 0.96)],
        };
      },
    });

    await openApp(page, state);
    await expect(page.getByRole("button", { name: /Upload your first document/ })).toBeVisible();

    await page.locator('input[type="file"]').setInputFiles({
      name: notes.filename,
      mimeType: "text/plain",
      buffer: Buffer.from("Jordan Lee owns the rollout plan. Maya Patel reviews it."),
    });

    await expect(documentButton(page, notes.filename)).toBeVisible();
    await expect(page.getByText("Ready", { exact: true })).toBeVisible();
    await expect(personButton(page, "Jordan Lee")).toBeVisible();
    await expect(personButton(page, "Maya Patel")).toBeVisible();

    await personButton(page, "Jordan Lee").click();
    await expect(page.locator(".active-person")).toContainText("Jordan Lee");
    await ask(page, "What should I know about this person?");

    await expect(page.locator(".message.user")).toContainText("What should I know about this person?");
    const assistant = page.locator(".message.assistant").last();
    await expect(assistant.locator(".answer-text")).toContainText("Jordan Lee owns the rollout plan");
    await expect(assistant.locator(".source-card")).toHaveCount(1);
    await assistant.locator(".source-card summary").click();
    await expect(assistant.locator(".source-card")).toContainText("people-notes.txt");
    await expect(assistant.locator(".source-card")).toContainText("Jordan Lee owns the rollout plan.");
  });

  test("shows a clear empty-library state without enabling chat", async ({ page }) => {
    await openApp(page, createApiState());

    await expect(page.getByRole("button", { name: /Upload your first document/ })).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Your question" })).toBeDisabled();
    await expect(page.getByLabel("Library activity summary")).toContainText(/0\s*documents/);
    await expect(page.locator(".notice")).toHaveCount(0);
  });
});

test.describe("Upload validation", () => {
  for (const filename of ["picture.png", "spreadsheet.csv", "archive.zip"]) {
    test(`rejects unsupported ${filename} before it enters the library`, async ({ page }) => {
      const state = createApiState();
      await openApp(page, state);

      await page.locator('input[type="file"]').setInputFiles({
        name: filename,
        mimeType: "application/octet-stream",
        buffer: Buffer.from("not a supported document"),
      });

      await expect(page.locator(".notice")).toContainText("Choose a PDF, DOCX, TXT, or Markdown file.");
      await expect(page.getByText("Your uploaded documents will appear here.")).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Your question" })).toBeDisabled();
      expect(state.uploadRequests).toBe(0);
    });
  }

  for (const [name, mimeType, buffer, message] of [
    ["empty.txt", "text/plain", Buffer.alloc(0), "The uploaded document is empty."],
    ["scanned.pdf", "application/pdf", Buffer.from("scanned image"), "Scanned PDFs need OCR before upload."],
    ["oversized.txt", "text/plain", Buffer.alloc(10 * 1024 * 1024 + 1, "x"), "The maximum document size is 10 MB."],
  ]) {
    test(`shows the API validation error for ${name}`, async ({ page }) => {
      const state = createApiState({ uploads: [{ error: { status: 422, detail: message } }] });
      if (name === "oversized.txt") state.uploads[0].error.status = 413;
      if (name === "empty.txt") state.uploads[0].error.status = 400;
      await openApp(page, state);

      await page.locator('input[type="file"]').setInputFiles({ name, mimeType, buffer });

      await expect(page.locator(".notice")).toContainText(message);
      await expect(page.getByText("Your uploaded documents will appear here.")).toBeVisible();
      expect(state.documents).toHaveLength(0);
    });
  }
});

test.describe("Scoped retrieval and citation integrity", () => {
  test("limits a question to the selected document and displays only its source", async ({ page }) => {
    const alpha = documentRecord("alpha", "alpha.txt", ["Jordan Lee"]);
    const beta = documentRecord("beta", "beta.txt", ["Jordan Lee"]);
    const state = createApiState({
      documents: [alpha, beta],
      people: [personRecord("Jordan Lee", 2, 2)],
      onChat: ({ request }) => {
        expect(request.document_ids).toEqual([alpha.id]);
        return {
          answer: "Jordan Lee is working on Project Alpha [1].",
          sources: [source(1, alpha, "Jordan Lee is assigned to Project Alpha.")],
        };
      },
    });
    await openApp(page, state);

    await documentButton(page, alpha.filename).click();
    await ask(page, "Which project is Jordan working on?");

    const sources = page.locator(".message.assistant .source-card");
    await expect(sources).toHaveCount(1);
    await expect(sources).toContainText("alpha.txt");
    await expect(sources).not.toContainText("beta.txt");
    await sources.locator("summary").click();
    await expect(sources).toContainText("Project Alpha");
  });

  test("keeps citation markers, source cards, excerpts, and ranking aligned", async ({ page }) => {
    const alpha = documentRecord("alpha", "alpha.txt", ["Jordan Lee"]);
    const beta = documentRecord("beta", "beta.txt", ["Maya Patel"]);
    const alphaSource = source(1, alpha, "Jordan Lee leads the alpha launch.", 0.94, 2);
    const betaSource = source(2, beta, "Maya Patel owns beta operations.", 0.73);
    const state = createApiState({
      documents: [alpha, beta],
      people: [personRecord("Jordan Lee"), personRecord("Maya Patel")],
      onChat: () => ({
        answer: "Jordan leads the alpha launch [1], while Maya owns beta operations [2].",
        sources: [alphaSource, betaSource],
      }),
    });
    await openApp(page, state);

    await ask(page, "Who leads each project?");

    const assistant = page.locator(".message.assistant").last();
    await expect(assistant.locator(".inline-citation")).toHaveText(["1", "2"]);
    const cards = assistant.locator(".source-card");
    await expect(cards).toHaveCount(2);
    await expect(cards.nth(0)).toContainText("alpha.txt");
    await expect(cards.nth(0)).toContainText("p. 2");
    await expect(cards.nth(0)).toContainText("94% match");
    await expect(cards.nth(1)).toContainText("beta.txt");
    await expect(cards.nth(1)).toContainText("73% match");
    await cards.nth(0).locator("summary").click();
    await cards.nth(1).locator("summary").click();
    await expect(cards.nth(0)).toContainText(alphaSource.excerpt);
    await expect(cards.nth(0)).not.toContainText(betaSource.excerpt);
    await expect(cards.nth(1)).toContainText(betaSource.excerpt);
    await expect(cards.nth(1)).not.toContainText(alphaSource.excerpt);
  });
});

test.describe("Document lifecycle", () => {
  test("cancels removal, then removes the selected document and keeps later chat scoped safely", async ({ page }) => {
    const alpha = documentRecord("alpha", "alpha.txt", ["Jordan Lee"]);
    const beta = documentRecord("beta", "beta.txt", ["Maya Patel"]);
    const state = createApiState({
      documents: [alpha, beta],
      people: [personRecord("Jordan Lee"), personRecord("Maya Patel")],
      onChat: ({ request }) => {
        const selected = request.document_ids?.[0] === alpha.id ? alpha : beta;
        return {
          answer: `${selected.filename} answers the question [1].`,
          sources: [source(1, selected, `${selected.filename} is the only retrieved source.`)],
        };
      },
    });
    await openApp(page, state);

    await documentButton(page, alpha.filename).click();
    page.once("dialog", (dialog) => dialog.dismiss());
    await page.getByRole("button", { name: "Remove alpha.txt" }).click();
    await expect(documentButton(page, alpha.filename)).toBeVisible();
    await expect(page.getByRole("textbox", { name: "Your question" })).toBeEnabled();

    await ask(page, "What does Jordan own?");
    await expect(page.locator(".message.assistant .source-card")).toContainText("alpha.txt");

    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Remove alpha.txt" }).click();
    await expect(documentButton(page, alpha.filename)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "All documents" })).toHaveAttribute("aria-current", "true");
    await expect(documentButton(page, beta.filename)).toBeVisible();
    await expect(personButton(page, "Jordan Lee")).toHaveCount(0);

    await page.getByRole("button", { name: "New", exact: true }).click();
    await ask(page, "What remains in the library?");
    const latestSources = page.locator(".message.assistant .source-card");
    await expect(latestSources).toContainText("beta.txt");
    await expect(latestSources).not.toContainText("alpha.txt is the only retrieved source.");
  });
});

test.describe("Connectivity and interaction resilience", () => {
  test("shows an offline state instead of loading indefinitely when the API cannot be reached", async ({ page }) => {
    await page.addInitScript(() => localStorage.clear());
    await page.route("**/api/**", (route) => route.abort());
    await page.goto("/");

    await expect(page.getByText("API offline", { exact: true })).toBeVisible();
    await expect(page.getByText("Your uploaded documents will appear here.")).toBeVisible();
    await expect(page.getByText("Loading your library…")).toHaveCount(0);
  });

  test("preserves a failed chat message and restores the composer after an API error", async ({ page }) => {
    const notes = documentRecord("notes", "notes.txt", ["Jordan Lee"]);
    const state = createApiState({
      documents: [notes],
      people: [personRecord("Jordan Lee")],
      onChat: () => ({ error: { status: 503, detail: "The API is temporarily unavailable." } }),
    });
    await openApp(page, state);

    await ask(page, "What does Jordan own?");

    await expect(page.locator(".message.user")).toContainText("What does Jordan own?");
    await expect(page.locator(".notice")).toContainText("The API is temporarily unavailable.");
    await expect(page.locator(".thinking-message")).toHaveCount(0);
    await expect(page.getByRole("textbox", { name: "Your question" })).toBeEnabled();
    await expect(page.getByRole("button", { name: "Couldn’t send. Retry" })).toBeVisible();
  });

  test("submits once with Enter, permits Shift+Enter, and ignores repeated Enter while waiting", async ({ page }) => {
    const notes = documentRecord("notes", "notes.txt", ["Jordan Lee"]);
    let releaseChat;
    const state = createApiState({
      documents: [notes],
      people: [personRecord("Jordan Lee")],
      onChat: () => ({
        answer: "Jordan owns the plan [1].",
        sources: [source(1, notes, "Jordan owns the plan.")],
      }),
    });
    state.chatGate = new Promise((resolve) => { releaseChat = resolve; });
    await openApp(page, state);

    const composer = page.getByRole("textbox", { name: "Your question" });
    await composer.fill("What does Jordan own?");
    await composer.press("Shift+Enter");
    await expect(composer).toHaveValue("What does Jordan own?\n");
    expect(state.chatRequests).toHaveLength(0);

    await composer.press("Enter");
    await expect(page.locator(".thinking-message")).toBeVisible();
    await composer.press("Enter");
    await composer.press("Enter");
    expect(state.chatRequests).toHaveLength(1);

    releaseChat();
    await expect(page.locator(".message.assistant .answer-text")).toContainText("Jordan owns the plan");
    await expect(page.locator(".message.user")).toHaveCount(1);
  });
});
