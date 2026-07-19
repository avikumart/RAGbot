"use client";

import { ChangeEvent, DragEvent, FormEvent, useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type DocumentRecord = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
  chunk_count: number;
  people: string[];
};

type PersonRecord = {
  normalized: string;
  name: string;
  mentions: number;
  document_count: number;
};

type Source = {
  index: number;
  document_id: string;
  filename: string;
  page: number | null;
  excerpt: string;
  score: number;
};

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  mode?: string;
};

function humanSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function documentKind(filename: string) {
  return filename.split(".").pop()?.toUpperCase() || "DOC";
}

function citationLabel(source: Source) {
  return source.page ? `${source.filename} · p. ${source.page}` : source.filename;
}

function answerModeLabel(mode: string) {
  if (mode === "local-grounded") return "Local grounded synthesis";
  if (mode.startsWith("cerebras:")) return `Cerebras · ${mode.slice("cerebras:".length)}`;
  return mode;
}

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Something went wrong. Please try again.");
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

function AnswerText({ text }: { text: string }) {
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p className="answer-text">
      {parts.map((part, index) => {
        const match = part.match(/^\[(\d+)\]$/);
        return match ? (
          <span className="inline-citation" key={`${part}-${index}`}>{match[1]}</span>
        ) : (
          <span key={`${part}-${index}`}>{part}</span>
        );
      })}
    </p>
  );
}

export default function Home() {
  const fileInput = useRef<HTMLInputElement>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [people, setPeople] = useState<PersonRecord[]>([]);
  const [messages, setMessages] = useState<Message[]>([]);
  const [selectedDocument, setSelectedDocument] = useState<string>("all");
  const [selectedPerson, setSelectedPerson] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const scopedDocument = documents.find((document) => document.id === selectedDocument);
  const visiblePeople = selectedDocument === "all"
    ? people
    : people.filter((person) => scopedDocument?.people.includes(person.name));

  async function refreshLibrary() {
    const [nextDocuments, nextPeople] = await Promise.all([
      api<DocumentRecord[]>("/api/documents"),
      api<PersonRecord[]>("/api/people"),
    ]);
    setDocuments(nextDocuments);
    setPeople(nextPeople);
  }

  useEffect(() => {
    let cancelled = false;

    async function initialize() {
      try {
        const [, nextDocuments, nextPeople] = await Promise.all([
          api("/api/health"),
          api<DocumentRecord[]>("/api/documents"),
          api<PersonRecord[]>("/api/people"),
        ]);
        if (cancelled) return;
        setDocuments(nextDocuments);
        setPeople(nextPeople);
        setConnected(true);
      } catch (error) {
        if (!cancelled) {
          setNotice(error instanceof Error ? error.message : "Could not connect to the API.");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void initialize();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, thinking]);

  async function uploadDocument(file: File) {
    const allowed = [".pdf", ".docx", ".txt", ".md"];
    if (!allowed.some((extension) => file.name.toLowerCase().endsWith(extension))) {
      setNotice("Choose a PDF, DOCX, TXT, or Markdown file.");
      return;
    }
    setUploading(true);
    setNotice(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const uploaded = await api<DocumentRecord>("/api/documents", { method: "POST", body: form });
      await refreshLibrary();
      setSelectedDocument(uploaded.id);
      setSelectedPerson(null);
      setConnected(true);
      setNotice(`${uploaded.filename} is indexed and ready to ask about.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The document could not be uploaded.");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) void uploadDocument(file);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void uploadDocument(file);
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = question.trim();
    if (!message || thinking || !documents.length) return;

    setMessages((current) => [
      ...current,
      { id: crypto.randomUUID(), role: "user", content: message },
    ]);
    setQuestion("");
    setThinking(true);
    setNotice(null);
    try {
      const response = await api<{ answer: string; sources: Source[]; mode: string }>("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message,
          document_ids: selectedDocument === "all" ? undefined : [selectedDocument],
          person: selectedPerson || undefined,
        }),
      });
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: response.answer,
          sources: response.sources,
          mode: response.mode,
        },
      ]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "I could not answer that question.");
    } finally {
      setThinking(false);
    }
  }

  async function removeDocument(document: DocumentRecord) {
    if (!window.confirm(`Remove ${document.filename} from this local library?`)) return;
    try {
      await api(`/api/documents/${document.id}`, { method: "DELETE" });
      if (selectedDocument === document.id) setSelectedDocument("all");
      await refreshLibrary();
      setNotice(`${document.filename} was removed.`);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The document could not be removed.");
    }
  }

  function choosePerson(name: string) {
    setSelectedPerson((current) => current === name ? null : name);
    if (!question) setQuestion(`What should I know about ${name}?`);
  }

  const suggestions = visiblePeople.slice(0, 3).map((person) => ({
    label: person.name,
    question: `What should I know about ${person.name}?`,
  }));

  return (
    <main className="app-shell">
      <aside className="library-panel">
        <div className="brand-row">
          <span className="brand-mark" aria-hidden="true">P</span>
          <div>
            <p className="brand-name">Personagraph</p>
            <p className="brand-subtitle">Private people intelligence</p>
          </div>
        </div>

        <div
          className={`upload-card ${dragging ? "is-dragging" : ""}`}
          onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <span className="upload-symbol" aria-hidden="true">↑</span>
          <div>
            <p>{uploading ? "Indexing your document…" : "Add a document"}</p>
            <span>PDF, DOCX, TXT or MD · 10 MB max</span>
          </div>
          <button
            className="upload-button"
            type="button"
            onClick={() => fileInput.current?.click()}
            disabled={uploading}
          >
            Browse
          </button>
          <input
            ref={fileInput}
            className="visually-hidden"
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={onFileChange}
          />
        </div>

        <div className="section-heading">
          <span>Library</span>
          <span>{documents.length}</span>
        </div>

        <nav className="document-list" aria-label="Document scope">
          <button
            type="button"
            className={`document-item all-documents ${selectedDocument === "all" ? "is-active" : ""}`}
            onClick={() => setSelectedDocument("all")}
          >
            <span className="document-icon">◎</span>
            <span className="document-copy">
              <strong>All documents</strong>
              <small>{people.length} people in scope</small>
            </span>
          </button>
          {documents.map((document) => (
            <div className={`document-row ${selectedDocument === document.id ? "is-active" : ""}`} key={document.id}>
              <button
                type="button"
                className="document-item"
                onClick={() => {
                  setSelectedDocument(document.id);
                  if (selectedPerson && !document.people.includes(selectedPerson)) setSelectedPerson(null);
                }}
              >
                <span className="file-badge">{documentKind(document.filename)}</span>
                <span className="document-copy">
                  <strong>{document.filename}</strong>
                  <small>{humanSize(document.size_bytes)} · {document.people.length} people</small>
                </span>
              </button>
              <button
                className="remove-button"
                type="button"
                aria-label={`Remove ${document.filename}`}
                onClick={() => void removeDocument(document)}
              >
                ×
              </button>
            </div>
          ))}
        </nav>

        <div className="privacy-note">
          <span className="privacy-dot" aria-hidden="true" />
          <div>
            <strong>Local by design</strong>
            <p>Files stay inside your Docker volume.</p>
          </div>
        </div>
      </aside>

      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <span className="eyebrow">Conversation</span>
            <h1>{scopedDocument?.filename ?? "Your document library"}</h1>
          </div>
          <div className={`connection-pill ${connected ? "is-online" : ""}`}>
            <span />
            {loading ? "Connecting" : connected ? "Private index ready" : "API offline"}
          </div>
        </header>

        {notice && (
          <div className="notice" role="status">
            <span>{notice}</span>
            <button type="button" onClick={() => setNotice(null)} aria-label="Dismiss message">×</button>
          </div>
        )}

        <div className="conversation" aria-live="polite">
          {!messages.length ? (
            <div className="welcome-state">
              <span className="welcome-kicker">PERSON-AWARE RETRIEVAL</span>
              <h2>Ask the people<br />in your documents.</h2>
              <p>
                Upload notes, profiles, or reports. Personagraph finds the right person,
                retrieves their context, and answers with traceable evidence.
              </p>

              {!documents.length ? (
                <button className="primary-action" type="button" onClick={() => fileInput.current?.click()}>
                  <span>↑</span> Upload your first document
                </button>
              ) : (
                <div className="suggestion-grid">
                  {(suggestions.length ? suggestions : [
                    { label: "People", question: "Who are the key people in these documents?" },
                    { label: "Roles", question: "What roles and responsibilities are described?" },
                  ]).map((suggestion) => (
                    <button
                      type="button"
                      key={suggestion.question}
                      onClick={() => setQuestion(suggestion.question)}
                    >
                      <span>{suggestion.label}</span>
                      <small>{suggestion.question}</small>
                      <b aria-hidden="true">↗</b>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="message-stack">
              {messages.map((message) => (
                <article className={`message ${message.role}`} key={message.id}>
                  <div className="avatar" aria-hidden="true">{message.role === "assistant" ? "P" : "You"}</div>
                  <div className="message-body">
                    <span className="message-author">{message.role === "assistant" ? "Personagraph" : "You"}</span>
                    {message.role === "assistant" ? <AnswerText text={message.content} /> : <p>{message.content}</p>}
                    {!!message.sources?.length && (
                      <div className="source-list">
                        {message.sources.map((source) => (
                          <details className="source-card" key={`${message.id}-${source.index}`}>
                            <summary>
                              <span className="source-number">{source.index}</span>
                              <span>{citationLabel(source)}</span>
                              <small>{Math.round(source.score * 100)}% match</small>
                            </summary>
                            <p>{source.excerpt}</p>
                          </details>
                        ))}
                      </div>
                    )}
                    {message.mode && <span className="answer-mode">{answerModeLabel(message.mode)}</span>}
                  </div>
                </article>
              ))}
              {thinking && (
                <article className="message assistant thinking-message">
                  <div className="avatar">P</div>
                  <div className="thinking-dots" aria-label="Searching documents"><span /><span /><span /></div>
                </article>
              )}
              <div ref={messageEnd} />
            </div>
          )}
        </div>

        <form className="composer" onSubmit={sendMessage}>
          {selectedPerson && (
            <button className="active-person" type="button" onClick={() => setSelectedPerson(null)}>
              <span>Person</span> {selectedPerson} ×
            </button>
          )}
          <div className="composer-row">
            <textarea
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={documents.length ? "Ask about a person, role, relationship, or event…" : "Upload a document to begin…"}
              disabled={!documents.length || thinking}
              rows={2}
              aria-label="Your question"
            />
            <button
              className="send-button"
              type="submit"
              disabled={!question.trim() || !documents.length || thinking}
              aria-label="Send question"
            >
              ↑
            </button>
          </div>
          <p>Answers use only retrieved document evidence. Check citations before relying on them.</p>
        </form>
      </section>

      <aside className="people-panel">
        <div className="people-header">
          <span className="eyebrow">People in scope</span>
          <span className="people-count">{visiblePeople.length}</span>
        </div>
        {visiblePeople.length ? (
          <div className="people-list">
            {visiblePeople.map((person, index) => (
              <button
                type="button"
                className={`person-card ${selectedPerson === person.name ? "is-selected" : ""}`}
                key={person.normalized}
                onClick={() => choosePerson(person.name)}
              >
                <span className={`person-avatar tone-${index % 5}`}>{person.name.split(" ").map((part) => part[0]).slice(0, 2).join("")}</span>
                <span>
                  <strong>{person.name}</strong>
                  <small>{person.mentions} indexed {person.mentions === 1 ? "passage" : "passages"}</small>
                </span>
                <b aria-hidden="true">›</b>
              </button>
            ))}
          </div>
        ) : (
          <div className="people-empty">
            <span>◇</span>
            <p>People will appear here after your first document is indexed.</p>
          </div>
        )}

        <div className="scope-card">
          <span>Retrieval scope</span>
          <strong>{selectedDocument === "all" ? "Entire library" : "One document"}</strong>
          <p>{selectedDocument === "all" ? "Searching every indexed passage." : scopedDocument?.filename}</p>
        </div>
      </aside>
    </main>
  );
}
