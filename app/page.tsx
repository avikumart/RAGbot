"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { DocumentLibrary } from "@/components/document-library";
import { api } from "@/lib/api";
import type {
  ChatRequest,
  ChatResponse,
  DocumentRecord,
  PersonRecord,
  Source,
} from "@/lib/api";
import { documentIndexStatus } from "./document-index-status.mjs";

type Message = {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  mode?: string;
};

function citationLabel(source: Source) {
  return source.page ? `${source.filename} · p. ${source.page}` : source.filename;
}

function answerModeLabel(mode: string) {
  if (mode === "local-grounded") return "Local grounded synthesis";
  if (mode.startsWith("cerebras:")) return `Cerebras · ${mode.slice("cerebras:".length)}`;
  return mode;
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
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const scopedDocument = documents.find((document) => document.id === selectedDocument);
  const totalChunks = documents.reduce((total, document) => total + document.chunk_count, 0);
  const hasIndexFailures = documents.some(
    (document) => documentIndexStatus(document.index_status).tone === "repair",
  );
  const allIndexesReady = documents.length > 0
    && documents.every((document) => document.index_status === "ready");
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
    return nextDocuments;
  }

  async function checkDocumentStatus() {
    setCheckingStatus(true);
    setNotice(null);
    try {
      const nextDocuments = await refreshLibrary();
      setConnected(true);
      if (!nextDocuments.length) {
        setNotice("No documents have been uploaded yet.");
        return;
      }
      const failed = nextDocuments.filter(
        (document) => documentIndexStatus(document.index_status).tone === "repair",
      );
      const inProgress = nextDocuments.filter(
        (document) => documentIndexStatus(document.index_status).tone === "indexing",
      );
      const disabled = nextDocuments.filter(
        (document) => documentIndexStatus(document.index_status).tone === "lexical",
      );
      if (failed.length) {
        setNotice(`${nextDocuments.length} document${nextDocuments.length === 1 ? " is" : "s are"} uploaded; ${failed.length} need${failed.length === 1 ? "s" : ""} embeddings reindexed. ${failed[0].index_error ?? ""}`.trim());
      } else if (inProgress.length) {
        setNotice(`${nextDocuments.length} document${nextDocuments.length === 1 ? " is" : "s are"} uploaded; embeddings are still pending for ${inProgress.length}.`);
      } else if (disabled.length) {
        setNotice(`${nextDocuments.length} document${nextDocuments.length === 1 ? " is" : "s are"} uploaded, but embedding indexing is disabled.`);
      } else {
        setNotice(`All ${nextDocuments.length} document${nextDocuments.length === 1 ? " is" : "s are"} uploaded and embeddings are ready.`);
      }
    } catch (error) {
      setConnected(false);
      setNotice(error instanceof Error ? error.message : "Document status could not be checked.");
    } finally {
      setCheckingStatus(false);
    }
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
      const nextDocuments = await refreshLibrary();
      setSelectedDocument(uploaded.id);
      setSelectedPerson(null);
      setConnected(true);
      const indexed = nextDocuments.find((document) => document.id === uploaded.id) ?? uploaded;
      const indexPresentation = documentIndexStatus(indexed.index_status);
      setNotice(
        indexPresentation.tone === "ready"
          ? `${uploaded.filename} is uploaded and ready.`
          : indexPresentation.tone === "lexical"
            ? `${uploaded.filename} is uploaded in lexical-only mode. You can chat with it now.`
            : indexPresentation.tone === "repair"
              ? `${uploaded.filename} is uploaded in lexical-only mode, but its semantic index needs repair. You can still chat with it now.`
              : `${uploaded.filename} is uploaded and indexing.`,
      );
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The document could not be uploaded.");
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
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
      const request: ChatRequest = {
        message,
        document_ids: selectedDocument === "all" ? undefined : [selectedDocument],
        person: selectedPerson || undefined,
      };
      const response = await api<ChatResponse>("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
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

  function selectDocument(document: DocumentRecord | "all") {
    if (document === "all") {
      setSelectedDocument("all");
      return;
    }

    setSelectedDocument(document.id);
    if (selectedPerson && !document.people.includes(selectedPerson)) setSelectedPerson(null);
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
      <DocumentLibrary
        documents={documents}
        peopleCount={people.length}
        selectedDocument={selectedDocument}
        loading={loading}
        uploading={uploading}
        checkingStatus={checkingStatus}
        fileInput={fileInput}
        onUpload={(file) => void uploadDocument(file)}
        onCheckStatus={() => void checkDocumentStatus()}
        onSelectDocument={selectDocument}
        onRemoveDocument={(document) => void removeDocument(document)}
      />

      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <span className="eyebrow">Conversation</span>
            <h1>{scopedDocument?.filename ?? "Your document library"}</h1>
          </div>
          <div className={`connection-pill ${connected ? "is-online" : ""}`}>
            <span />
            {loading
              ? "Connecting"
              : !connected
                ? "API offline"
                : hasIndexFailures
                  ? "Index needs attention"
                  : allIndexesReady
                    ? "Private index ready"
                    : "API connected"}
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
        <details className="side-panel-details" open>
          <summary className="people-header">
            <span className="eyebrow">Library activity</span>
            <span className="details-toggle" aria-hidden="true">⌄</span>
          </summary>
          <div className="library-stats" aria-label="Library activity summary">
            <div><strong>{documents.length}</strong><span>documents</span></div>
            <div><strong>{totalChunks}</strong><span>chunks indexed</span></div>
            <div><strong>{people.length}</strong><span>people found</span></div>
          </div>
          {uploading && <p className="indexing-status" role="status"><span className="state-spinner" aria-hidden="true" /> Indexing your upload</p>}
          <div className="people-heading">
            <span className="eyebrow">People in scope</span>
            <span className="people-count">{visiblePeople.length}</span>
          </div>
          {loading ? (
            <div className="people-empty people-loading" role="status"><span className="state-spinner" aria-hidden="true" /><p>Loading people…</p></div>
          ) : visiblePeople.length ? (
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
              <p>{documents.length ? "No people were found in this document." : "People will appear here after your first document is indexed."}</p>
            </div>
          )}
          <div className="scope-card">
            <span>Retrieval scope</span>
            <strong>{selectedDocument === "all" ? "Entire library" : "One document"}</strong>
            <p title={selectedDocument === "all" ? "Searching every indexed passage." : scopedDocument?.filename}>{selectedDocument === "all" ? "Searching every indexed passage." : scopedDocument?.filename}</p>
          </div>
        </details>
      </aside>
    </main>
  );
}
