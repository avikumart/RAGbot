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

function createApiState({ documents = [], people = [], collections = [], uploads = [], onChat } = {}) {
  return {
    documents: [...documents],
    people: [...people],
    collections: [...collections],
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

    if (pathname === "/api/collections" && method === "GET") {
      await route.fulfill({ json: state.collections });
      return;
    }

    if (pathname === "/api/collections" && method === "POST") {
      const body = request.postDataJSON();
      const docIds = body.document_ids ?? [];
      const created = {
        id: `col-${state.collections.length + 1}`,
        name: body.name,
        description: body.description ?? null,
        created_at: timestamp,
        document_ids: docIds,
        document_count: docIds.length,
      };
      state.collections = [created, ...state.collections];
      await route.fulfill({ status: 201, json: created });
      return;
    }

    if (pathname.startsWith("/api/collections/") && pathname.endsWith("/documents") && method === "POST") {
      const parts = pathname.split("/");
      const colId = parts[3];
      const body = request.postDataJSON();
      const target = state.collections.find((c) => c.id === colId);
      if (!target) {
        await route.fulfill({ status: 404, json: { detail: "Collection not found." } });
        return;
      }
      const nextSet = new Set(target.document_ids);
      for (const id of body.add_document_ids ?? body.add ?? []) nextSet.add(id);
      for (const id of body.remove_document_ids ?? body.remove ?? []) nextSet.delete(id);
      const updated = {
        ...target,
        document_ids: Array.from(nextSet),
        document_count: nextSet.size,
      };
      state.collections = state.collections.map((c) => (c.id === colId ? updated : c));
      await route.fulfill({ json: updated });
      return;
    }

    if (pathname.startsWith("/api/collections/") && method === "PATCH") {
      const colId = pathname.split("/").pop();
      const body = request.postDataJSON();
      const target = state.collections.find((c) => c.id === colId);
      if (!target) {
        await route.fulfill({ status: 404, json: { detail: "Collection not found." } });
        return;
      }
      const updated = {
        ...target,
        name: body.name ?? target.name,
        description: body.description !== undefined ? body.description : target.description,
      };
      state.collections = state.collections.map((c) => (c.id === colId ? updated : c));
      await route.fulfill({ json: updated });
      return;
    }

    if (pathname.startsWith("/api/collections/") && method === "DELETE") {
      const colId = pathname.split("/").pop();
      state.collections = state.collections.filter((c) => c.id !== colId);
      await route.fulfill({ json: { deleted: colId } });
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

    if (pathname === "/api/documents/batch" && method === "POST") {
      state.batchUploadRequests = (state.batchUploadRequests || 0) + 1;
      const documents = [];
      const errors = [];
      while (state.uploads.length) {
        const upload = state.uploads.shift();
        if (upload?.error) {
          errors.push({ filename: upload.filename || "failed.txt", detail: upload.error.detail });
        } else if (upload?.document) {
          state.documents = [...state.documents, upload.document];
          documents.push(upload.document);
          if (upload.people) state.people = upload.people;
        }
      }
      await route.fulfill({ json: { documents, errors } });
      return;
    }

    if (pathname.includes("/file") && method === "GET") {
      const parts = pathname.split("/");
      const docId = parts[parts.indexOf("documents") + 1];
      const doc = state.documents.find((d) => d.id === docId);
      const isPdf = doc?.filename?.endsWith(".pdf");
      const content = state.fileContents?.[docId] || (doc ? `Content of ${doc.filename}: Jordan Lee leads the program and owns the rollout plan.` : "Sample document text.");
      await route.fulfill({
        status: 200,
        headers: {
          "content-type": isPdf ? "application/pdf" : "text/plain",
          "accept-ranges": "bytes",
          "content-length": String(Buffer.byteLength(content)),
        },
        body: content,
      });
      return;
    }

    if (pathname.startsWith("/api/documents/") && method === "GET") {
      const docId = pathname.split("/").pop();
      const doc = state.documents.find((d) => d.id === docId);
      if (!doc) {
        await route.fulfill({ status: 404, json: { detail: "Document not found." } });
        return;
      }
      const fullText = state.fileContents?.[docId] || `Content of ${doc.filename}: Jordan Lee leads the program and owns the rollout plan.`;
      await route.fulfill({
        status: 200,
        json: {
          ...doc,
          chunks: [
            {
              id: 1,
              ordinal: 0,
              page: 1,
              content: fullText,
              people: doc.people,
            },
          ],
        },
      });
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

    if (pathname.startsWith("/api/people/") && pathname.endsWith("/timeline")) {
      const parts = pathname.split("/");
      const personName = decodeURIComponent(parts[3] || "");
      const events = state.timelineEvents || [
        {
          id: "ev-1",
          document_id: state.documents[0]?.id || "doc-1",
          filename: state.documents[0]?.filename || "notes.txt",
          entity_name: personName,
          event_text: `${personName} graduated from Stanford in 2018.`,
          event_date: "2018",
          chunk_id: 1,
          page: 1,
          chunk_content: `${personName} graduated from Stanford in 2018.`,
        },
        {
          id: "ev-2",
          document_id: state.documents[0]?.id || "doc-1",
          filename: state.documents[0]?.filename || "notes.txt",
          entity_name: personName,
          event_text: `In September 2020, ${personName} joined Acme Corp as Principal Architect.`,
          event_date: "September 2020",
          chunk_id: 2,
          page: 2,
          chunk_content: `In September 2020, ${personName} joined Acme Corp as Principal Architect.`,
        },
      ];
      await route.fulfill({ json: events });
      return;
    }

    if (pathname.startsWith("/api/people/") && pathname.endsWith("/dossier")) {
      const parts = pathname.split("/");
      const personName = decodeURIComponent(parts[3] || "");
      const dossier = state.dossier || {
        entity_name: personName,
        generated_at: "2026-10-14T12:00:00Z",
        scope: {
          document_ids: state.documents.map((d) => d.id),
          summary: "1 document",
        },
        executive_summary: `${personName} is a Principal AI Architect leading strategic initiatives [1].`,
        sections: [
          {
            id: "biography",
            title: "Biography & Current Roles",
            content: `- Joined Acme Corp as Principal AI Architect in 2020 [1].`,
            citations: [1],
            excerpt_ids: [101],
          },
          {
            id: "relationships",
            title: "Key Relationships & Network",
            content: `- Collaborates with team leads on architecture [1].`,
            citations: [1],
            excerpt_ids: [101],
          },
          {
            id: "projects",
            title: "Projects & Key Accomplishments",
            content: `- Spearheaded the Quantum Project rollout [1].`,
            citations: [1],
            excerpt_ids: [101],
          },
          {
            id: "quotes",
            title: "Direct Statements & Positions",
            content: `- "Reliability is paramount for scalable systems" [1].`,
            citations: [1],
            excerpt_ids: [101],
          },
        ],
        sources: [
          {
            index: 1,
            id: 101,
            document_id: state.documents[0]?.id || "doc-1",
            filename: state.documents[0]?.filename || "notes.txt",
            page: 1,
            excerpt: `${personName} joined Acme Corp as Principal AI Architect in 2020. Reliability is paramount for scalable systems.`,
            score: 1.0,
          },
        ],
        markdown: `# Executive Briefing: ${personName}\n\n## Executive Summary\n${personName} is a Principal AI Architect leading strategic initiatives [1].\n\n## 1. Biography & Current Roles\n- Joined Acme Corp as Principal AI Architect in 2020 [1].\n\n## 2. Key Relationships & Network\n- Collaborates with team leads on architecture [1].\n\n## 3. Projects & Key Accomplishments\n- Spearheaded the Quantum Project rollout [1].\n\n## 4. Direct Statements & Positions\n- "Reliability is paramount for scalable systems" [1].\n\n---\n### Verified Document Sources\n- [1] **${state.documents[0]?.filename || "notes.txt"}** (page 1, Excerpt ID: \`101\`): "${personName} joined Acme Corp as Principal AI Architect in 2020..."`,
      };
      await route.fulfill({ json: dossier });
      return;
    }

    if (pathname === "/api/graph") {
      const graph = state.graph || {
        nodes: state.people.map((p) => ({
          id: p.name,
          label: p.name,
          type: "person",
          mentions: p.mentions || 1,
        })),
        edges: [],
      };
      await route.fulfill({ json: graph });
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
    await expect(page.getByText("Subjects in scope", { exact: true })).toBeVisible();
    await expect(personButton(page, "Jordan Lee")).toBeVisible();
    await expect(personButton(page, "Maya Patel")).toBeVisible();
    await expect(personButton(page, "Jordan Lee")).toContainText("Appears in 1 document · 1 indexed passage");

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
  for (const filename of ["picture.png", "audio.mp3", "archive.zip"]) {
    test(`rejects unsupported ${filename} before it enters the library`, async ({ page }) => {
      const state = createApiState();
      await openApp(page, state);

      await page.locator('input[type="file"]').setInputFiles({
        name: filename,
        mimeType: "application/octet-stream",
        buffer: Buffer.from("not a supported document"),
      });

      await expect(page.locator(".notice")).toContainText("Choose a supported file");
      await expect(page.getByText("Your uploaded documents will appear here.")).toBeVisible();
      await expect(page.getByRole("textbox", { name: "Your question" })).toBeDisabled();
      expect(state.uploadRequests).toBe(0);
    });
  }

  test("accepts and displays CSV document in library with CSV badge", async ({ page }) => {
    const csvDoc = documentRecord("doc-csv-1", "contacts.csv", ["Alice Walker"], {
      content_type: "text/csv",
    });
    const state = createApiState({
      uploads: [{
        document: csvDoc,
        people: [personRecord("Alice Walker")],
      }],
    });
    await openApp(page, state);

    await page.locator('input[type="file"]').setInputFiles({
      name: "contacts.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("Name,Role\nAlice Walker,Scientist"),
    });

    await expect(documentButton(page, csvDoc.filename)).toBeVisible();
    await expect(page.locator(".document-list .file-badge.is-csv")).toBeVisible();
  });

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

test.describe("Batch and multi-file uploads", () => {
  test("uploads multiple documents in batch and displays upload queue with progress", async ({ page }) => {
    const doc1 = documentRecord("doc-1", "doc1.txt", ["Jordan Lee"]);
    const doc2 = documentRecord("doc-2", "doc2.txt", ["Morgan Diaz"]);
    const state = createApiState({
      uploads: [
        { document: doc1, people: [personRecord("Jordan Lee")] },
        { document: doc2, people: [personRecord("Jordan Lee"), personRecord("Morgan Diaz")] },
      ],
    });
    await openApp(page, state);

    await page.locator('input[type="file"]').setInputFiles([
      { name: "doc1.txt", mimeType: "text/plain", buffer: Buffer.from("First doc content") },
      { name: "doc2.txt", mimeType: "text/plain", buffer: Buffer.from("Second doc content") },
    ]);

    await expect(page.locator(".upload-queue")).toBeVisible();
    await expect(page.locator(".upload-queue")).toContainText("Upload queue");
    await expect(page.locator(".upload-queue")).toContainText("doc1.txt");
    await expect(page.locator(".upload-queue")).toContainText("doc2.txt");
    await expect(page.locator(".document-list")).toContainText("doc1.txt");
    await expect(page.locator(".document-list")).toContainText("doc2.txt");
    expect(state.batchUploadRequests).toBe(1);
    expect(state.documents).toHaveLength(2);
  });

  test("shows error badge and retry button for failed files in batch queue", async ({ page }) => {
    const doc1 = documentRecord("doc-1", "valid.txt", ["Jordan Lee"]);
    const state = createApiState({
      uploads: [
        { document: doc1 },
        { error: { status: 422, detail: "Empty document content" }, filename: "empty.txt" },
      ],
    });
    await openApp(page, state);

    await page.locator('input[type="file"]').setInputFiles([
      { name: "valid.txt", mimeType: "text/plain", buffer: Buffer.from("Valid content") },
      { name: "empty.txt", mimeType: "text/plain", buffer: Buffer.from("") },
    ]);

    await expect(page.locator(".upload-queue")).toBeVisible();
    await expect(page.locator(".upload-queue-status.is-error")).toBeVisible();
    await expect(page.locator(".upload-queue-retry")).toBeVisible();
    await expect(page.locator(".upload-queue")).toContainText("Empty document content");
  });
});

test.describe("Scoped retrieval and citation integrity", () => {
  test("shows a no-evidence answer without inventing citations", async ({ page }) => {
    const notes = documentRecord("notes", "people-notes.txt", ["Jordan Lee"]);
    const state = createApiState({
      documents: [notes],
      people: [personRecord("Jordan Lee")],
      onChat: ({ request }) => {
        expect(request.document_ids).toBeUndefined();
        return {
          answer: "I could not find grounded evidence about Taylor Morgan in your documents.",
          sources: [],
        };
      },
    });
    await openApp(page, state);

    await ask(page, "What does Taylor Morgan do?");

    const assistant = page.locator(".message.assistant").last();
    await expect(assistant.locator(".answer-text")).toContainText("could not find grounded evidence");
    await expect(assistant.locator(".inline-citation")).toHaveCount(0);
    await expect(assistant.locator(".source-card")).toHaveCount(0);
  });

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
    await expect.poll(() => state.chatRequests).toHaveLength(1);

    releaseChat();
    await expect(page.locator(".message.assistant .answer-text")).toContainText("Jordan owns the plan");
    await expect(page.locator(".message.user")).toHaveCount(1);
  });

  test("switches to Persona Graph, renders interactive network nodes, and scopes chat on click", async ({ page }) => {
    const doc = documentRecord("doc-1", "org-chart.txt", ["Robert Smith", "Maya Patel"]);
    const state = createApiState({
      documents: [doc],
      people: [personRecord("Robert Smith"), personRecord("Maya Patel")],
    });
    state.graph = {
      nodes: [
        { id: "Robert Smith", label: "Robert Smith", type: "person", mentions: 4 },
        { id: "Acme Corp", label: "Acme Corp", type: "organization", mentions: 1 },
      ],
      edges: [
        { id: "e1", source: "Robert Smith", target: "Acme Corp", relation: "CTO at", document_id: "doc-1" },
      ],
    };
    await openApp(page, state);

    // Switch to Persona Graph tab
    const graphTab = page.getByRole("tab", { name: /Persona Graph/i });
    await expect(graphTab).toBeVisible();
    await graphTab.click();

    // Verify SVG canvas and nodes are rendered
    await expect(page.locator(".graph-canvas")).toBeVisible();
    await expect(page.locator(".graph-node-group")).toHaveCount(2);
    await expect(page.locator(".graph-node-group", { hasText: "Robert Smith" })).toBeVisible();
    await expect(page.locator(".graph-node-group", { hasText: "Acme Corp" })).toBeVisible();
    await expect(page.locator(".edge-label-text")).toContainText("CTO at");

    // Click on Robert Smith node to scope chat
    await page.locator(".graph-node-group", { hasText: "Robert Smith" }).click();
    await expect(page.locator(".graph-node-group.is-selected")).toBeVisible();

    // Switch back to Subjects tab and verify selection persisted
    await page.getByRole("tab", { name: /Subjects/i }).click();
    await expect(page.locator(".person-card.is-selected")).toBeVisible();
  });

  test("clicking citation badge [n] opens side-by-side citation viewer with deep linking and page navigation", async ({ page }) => {
    const pdfDoc = documentRecord("doc-pdf", "financial-report.pdf", ["Jordan Lee"], { content_type: "application/pdf" });
    const pdfSource = source(1, pdfDoc, "Jordan Lee oversees the rollout budget for 2026.", 0.95, 3);
    const state = createApiState({
      documents: [pdfDoc],
      people: [personRecord("Jordan Lee")],
      onChat: () => ({
        answer: "Jordan Lee oversees the rollout budget [1].",
        sources: [pdfSource],
      }),
    });
    await openApp(page, state);

    await ask(page, "Who oversees the budget?");

    // Verify inline citation badge is rendered
    const citationBadge = page.getByTestId("citation-badge-1");
    await expect(citationBadge).toBeVisible();
    await expect(citationBadge).toHaveText("1");

    // Click the inline citation badge [1]
    await citationBadge.click();

    // Verify citation drawer slides open
    const drawer = page.getByTestId("citation-viewer-drawer");
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText("financial-report.pdf");

    // Verify deep linking to cited page and active citation callout
    const highlightBanner = page.getByTestId("citation-highlight");
    await expect(highlightBanner).toBeVisible();
    await expect(highlightBanner).toContainText("Jordan Lee oversees the rollout budget for 2026.");
    await expect(highlightBanner).toContainText("Page 3");

    // Verify close button dismisses drawer
    const closeBtn = page.getByTestId("close-viewer-btn");
    await expect(closeBtn).toBeVisible();
    await closeBtn.click();
    await expect(drawer).not.toBeVisible();
  });

  test("clicking source card view button opens viewer drawer with matching excerpt", async ({ page }) => {
    const textDoc = documentRecord("doc-notes", "team-charter.txt", ["Maya Patel"], { content_type: "text/plain" });
    const excerpt = "Maya Patel coordinates the security architecture review.";
    const notesSource = source(1, textDoc, excerpt, 0.92);
    const state = createApiState({
      documents: [textDoc],
      people: [personRecord("Maya Patel")],
      onChat: () => ({
        answer: "Maya coordinates the architecture review [1].",
        sources: [notesSource],
      }),
    });
    state.fileContents = {
      "doc-notes": `Team charter.\n\nMaya Patel coordinates the security architecture review.\n\nApproved in 2026.`,
    };
    await openApp(page, state);

    await ask(page, "What is Maya's responsibility?");

    // Expand source card and click View in document button
    const sourceCard = page.getByTestId("source-card-1");
    await expect(sourceCard).toBeVisible();
    await sourceCard.locator("summary").click();
    const viewBtn = page.getByTestId("view-source-btn-1");
    await expect(viewBtn).toBeVisible();
    await viewBtn.click();

    // Verify drawer opened with non-PDF text viewer and passage highlight
    const drawer = page.getByTestId("citation-viewer-drawer");
    await expect(drawer).toBeVisible();
    const nonPdfViewer = page.getByTestId("non-pdf-viewer");
    await expect(nonPdfViewer).toBeVisible();
    const passageHighlight = page.getByTestId("passage-highlight");
    await expect(passageHighlight).toBeVisible();
    await expect(passageHighlight).toContainText("Maya Patel coordinates the security architecture review.");
  });

  test("clicking persona offers timeline view alongside passages and graph with citation triggers", async ({ page }) => {
    const textDoc = documentRecord("doc-notes", "team-charter.txt", ["Maya Patel"], { content_type: "text/plain" });
    const state = createApiState({
      documents: [textDoc],
      people: [personRecord("Maya Patel")],
    });
    state.fileContents = {
      "doc-notes": "Maya Patel graduated from Stanford in 2018.\\nIn September 2020, Maya joined Acme Corp as Principal Architect.",
    };
    await openApp(page, state);

    // 1. Verify Subjects, Graph, and Timeline tabs are visible
    const subjectsTab = page.getByRole("tab", { name: /Subjects/i });
    const graphTab = page.getByRole("tab", { name: /Graph/i });
    const timelineTab = page.getByRole("tab", { name: /Timeline/i });
    await expect(subjectsTab).toBeVisible();
    await expect(graphTab).toBeVisible();
    await expect(timelineTab).toBeVisible();

    // 2. Click persona card to focus on Maya Patel
    const personCard = page.locator(".person-card").filter({ hasText: "Maya Patel" });
    await expect(personCard).toBeVisible();
    await personCard.click();

    // 3. Click Timeline tab to view chronological events
    await timelineTab.click();
    await expect(timelineTab).toHaveAttribute("aria-selected", "true");

    // 4. Verify milestones rendered with dates and descriptions
    const timelineContainer = page.locator(".persona-timeline-container");
    await expect(timelineContainer).toBeVisible();
    await expect(timelineContainer).toContainText("2018");
    await expect(timelineContainer).toContainText("September 2020");
    await expect(timelineContainer).toContainText("Maya Patel graduated from Stanford in 2018.");

    // 5. Test jump to citation trigger slides open the reader drawer
    const citationTrigger = page.locator('[data-testid="timeline-citation-jump"]').first();
    await expect(citationTrigger).toBeVisible();
    await citationTrigger.click();

    const drawer = page.getByTestId("citation-viewer-drawer");
    await expect(drawer).toBeVisible();
  });

  test("creates a collection, assigns documents, scopes chat queries, renames, and deletes while preserving documents", async ({ page }) => {
    const docAlpha = documentRecord("doc-alpha", "alpha-spec.txt", ["Jordan Lee"]);
    const docBeta = documentRecord("doc-beta", "beta-notes.txt", ["Maya Patel"]);
    const state = createApiState({
      documents: [docAlpha, docBeta],
      people: [personRecord("Jordan Lee"), personRecord("Maya Patel")],
      onChat: ({ request }) => {
        expect(request.collection_id).toBe("col-1");
        expect(request.document_ids).toBeUndefined();
        return {
          answer: "Jordan Lee leads the Alpha architecture [1].",
          sources: [source(1, docAlpha, "Jordan Lee leads the Alpha architecture.", 0.96)],
        };
      },
    });
    await openApp(page, state);

    // 1. Create a new collection via the "+ Collection" button
    await page.getByTestId("new-collection-btn").click();
    const createForm = page.getByTestId("create-collection-form");
    await expect(createForm).toBeVisible();
    await page.getByTestId("collection-name-input").fill("Alpha Workspace");
    await page.getByTestId("collection-description-input").fill("Core Alpha specs");
    await page.getByTestId("save-collection-btn").click();

    // 2. Verify collection chip is rendered and active
    const filterBar = page.getByTestId("collection-filter-bar");
    await expect(filterBar).toBeVisible();
    const colChip = page.getByTestId("collection-chip-col-1");
    await expect(colChip).toBeVisible();
    await expect(colChip).toContainText("Alpha Workspace");

    // 3. Assign alpha-spec.txt to the collection (assign list is shown automatically for empty collections)
    const folderCard = page.getByTestId("active-collection-card");
    await expect(folderCard).toBeVisible();
    const assignList = page.getByTestId("collection-assign-list");
    await expect(assignList).toBeVisible();
    await page.getByTestId("assign-doc-doc-alpha").check();

    // 4. Verify document list filters to only alpha-spec.txt and Subjects panel scopes to Jordan Lee
    await expect(documentButton(page, "alpha-spec.txt")).toBeVisible();
    await expect(documentButton(page, "beta-notes.txt")).toHaveCount(0);
    await expect(personButton(page, "Jordan Lee")).toBeVisible();
    await expect(personButton(page, "Maya Patel")).toHaveCount(0);

    // 5. Verify active collection pill in composer and send a scoped chat question
    await expect(page.getByTestId("active-collection-pill")).toContainText("Alpha Workspace");
    await ask(page, "Who leads the Alpha architecture?");
    const assistant = page.locator(".message.assistant").last();
    await expect(assistant.locator(".answer-text")).toContainText("Jordan Lee leads the Alpha architecture");
    await expect(assistant.locator(".source-card")).toHaveCount(1);
    await expect(assistant.locator(".source-card")).toContainText("alpha-spec.txt");

    // 6. Rename the collection
    await page.getByTestId("edit-collection-btn").click();
    const editInput = page.getByTestId("edit-collection-name-input");
    await expect(editInput).toBeVisible();
    await editInput.fill("Alpha Project v2");
    await page.getByTestId("confirm-edit-collection-btn").click();
    await expect(colChip).toContainText("Alpha Project v2");

    // 7. Delete the collection and verify underlying documents are preserved
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByTestId("delete-collection-btn").click();
    await expect(page.getByTestId("collection-chip-col-1")).toHaveCount(0);
    await expect(documentButton(page, "alpha-spec.txt")).toBeVisible();
    await expect(documentButton(page, "beta-notes.txt")).toBeVisible();
  });

  test("generates executive briefing dossier with multi-section tabs, markdown download, and PDF export options", async ({ page }) => {
    const doc = documentRecord("doc-1", "profile.txt", ["Maya Patel"]);
    const state = createApiState({
      documents: [doc],
      people: [personRecord("Maya Patel")],
    });
    await openApp(page, state);

    // 1. Click Generate Dossier quick button on Maya Patel's card
    const dossierBtn = page.locator(".person-dossier-quickbtn").first();
    await expect(dossierBtn).toBeVisible();
    await dossierBtn.click();

    // 2. Verify Dossier modal opens and displays executive briefing
    const modal = page.locator(".dossier-modal");
    await expect(modal).toBeVisible();
    await expect(modal).toContainText("Executive Briefing: Maya Patel");
    await expect(modal).toContainText("100% Grounded");
    await expect(modal).toContainText("Biography & Current Roles");
    await expect(modal).toContainText("Key Relationships & Network");
    await expect(modal).toContainText("Projects & Key Accomplishments");
    await expect(modal).toContainText("Direct Statements & Positions");

    // 3. Verify verified document source and citation jump
    await expect(modal).toContainText("Excerpt ID: #101");
    await expect(modal.locator(".dossier-cite-btn").first()).toBeVisible();

    // 4. Switch to Markdown Source tab
    const markdownTab = modal.getByRole("tab", { name: /Markdown Source/i });
    await markdownTab.click();
    await expect(modal.locator(".dossier-markdown-pre")).toBeVisible();
    await expect(modal.locator(".dossier-markdown-pre")).toContainText("# Executive Briefing: Maya Patel");

    // 5. Test Copy Markdown button
    const copyBtn = modal.locator(".copy-btn");
    await expect(copyBtn).toBeVisible();

    // 6. Test Download .md button
    const downloadBtn = modal.locator(".download-btn");
    await expect(downloadBtn).toBeVisible();

    // 7. Test Export PDF button
    const pdfBtn = modal.locator(".pdf-btn");
    await expect(pdfBtn).toBeVisible();

    // 8. Close modal
    const closeBtn = modal.locator(".dossier-close-btn");
    await closeBtn.click();
    await expect(modal).toHaveCount(0);
  });
});
