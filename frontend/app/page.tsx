"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { DocumentLibrary } from "@/components/document-library";
import type { QueueItem } from "@/components/upload-queue";
import { api, streamChat } from "@/lib/api";
import type {
  BatchUploadResponse,
  ChatMessage,
  ChatRequest,
  ChatSession,
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
  mode?: string | null;
  retrievalMode?: string | null;
  clientMessageId?: string;
  status?: "pending" | "failed";
};

type ConversationCache = {
  version: 1;
  activeSessionId: string | null;
  draft: string;
  selectedDocument: string;
  selectedPerson: string | null;
  messages: Message[];
  updatedAt: string;
};

const CONVERSATION_CACHE_KEY = "personagraph.conversation-cache.v1";

function readConversationCache(): ConversationCache | null {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(CONVERSATION_CACHE_KEY) ?? "null");
    if (!parsed || typeof parsed !== "object" || !("version" in parsed) || parsed.version !== 1) {
      localStorage.removeItem(CONVERSATION_CACHE_KEY);
      return null;
    }
    const cache = parsed as ConversationCache;
    if (typeof cache.draft !== "string" || !Array.isArray(cache.messages)) {
      localStorage.removeItem(CONVERSATION_CACHE_KEY);
      return null;
    }
    return cache;
  } catch {
    localStorage.removeItem(CONVERSATION_CACHE_KEY);
    return null;
  }
}

function asMessage(message: ChatMessage): Message {
  return {
    id: message.id,
    role: message.role,
    content: message.content,
    sources: message.sources,
    mode: message.mode,
    retrievalMode: message.retrieval_mode,
  };
}

function citationLabel(source: Source) {
  return source.page ? `${source.filename} · p. ${source.page}` : source.filename;
}

function subjectDescription(subject: PersonRecord) {
  const documentLabel = `${subject.document_count} ${subject.document_count === 1 ? "document" : "documents"}`;
  const passageLabel = `${subject.mentions} indexed ${subject.mentions === 1 ? "passage" : "passages"}`;
  return `Appears in ${documentLabel} · ${passageLabel}`;
}

function answerModeLabel(mode: string) {
  if (mode === "local-grounded") return "Local grounded synthesis";
  if (mode.startsWith("cerebras:")) return `Cerebras · ${mode.slice("cerebras:".length)}`;
  if (mode.startsWith("openai:")) return `OpenAI · ${mode.slice("openai:".length)}`;
  if (mode.startsWith("gemini:")) return `Gemini · ${mode.slice("gemini:".length)}`;
  if (mode.startsWith("anthropic:")) return `Anthropic · ${mode.slice("anthropic:".length)}`;
  if (mode.startsWith("ollama:")) return `Ollama · ${mode.slice("ollama:".length)}`;
  if (mode.startsWith("groq:")) return `Groq · ${mode.slice("groq:".length)}`;
  if (mode.includes(":")) {
    const [provider, ...modelParts] = mode.split(":");
    const capitalized = provider.charAt(0).toUpperCase() + provider.slice(1);
    return `${capitalized} · ${modelParts.join(":")}`;
  }
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
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [selectedDocument, setSelectedDocument] = useState<string>("all");
  const [selectedPerson, setSelectedPerson] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadQueue, setUploadQueue] = useState<QueueItem[]>([]);
  const [checkingStatus, setCheckingStatus] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [cacheHydrated, setCacheHydrated] = useState(false);

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
    const timer = window.setTimeout(() => {
      const cached = readConversationCache();
      if (cached) {
        setActiveSessionId(cached.activeSessionId);
        setQuestion(cached.draft);
        setSelectedDocument(cached.selectedDocument);
        setSelectedPerson(cached.selectedPerson);
        setMessages(cached.messages);
      }
      setCacheHydrated(true);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (!cacheHydrated) return;
    let cancelled = false;

    async function initialize() {
      try {
        const [, nextDocuments, nextPeople, history] = await Promise.all([
          api("/api/health"),
          api<DocumentRecord[]>("/api/documents"),
          api<PersonRecord[]>("/api/people"),
          api<{ sessions: ChatSession[] }>("/api/sessions?limit=30"),
        ]);
        if (cancelled) return;
        setDocuments(nextDocuments);
        setPeople(nextPeople);
        setSessions(history.sessions);
        const cached = readConversationCache();
        if (cached?.activeSessionId) {
          try {
            const session = await api<ChatSession>(`/api/sessions/${cached.activeSessionId}`);
            if (!cancelled) {
              setActiveSessionId(session.id);
              setMessages((session.messages ?? []).map(asMessage));
              setSelectedDocument(session.document_ids[0] ?? "all");
              setSelectedPerson(session.person);
            }
          } catch {
            // Cached messages remain useful when offline; the server wins whenever it responds.
          }
        }
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
  }, [cacheHydrated]);

  useEffect(() => {
    if (!cacheHydrated) return;
    const cache: ConversationCache = {
      version: 1,
      activeSessionId,
      draft: question,
      selectedDocument,
      selectedPerson,
      messages,
      updatedAt: new Date().toISOString(),
    };
    try {
      localStorage.setItem(CONVERSATION_CACHE_KEY, JSON.stringify(cache));
    } catch {
      // Storage quota or privacy settings must never prevent chatting.
    }
  }, [activeSessionId, cacheHydrated, messages, question, selectedDocument, selectedPerson]);

  useEffect(() => {
    messageEnd.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages, thinking]);

  async function uploadDocuments(filesInput: File | File[]) {
    const rawFiles = Array.isArray(filesInput) ? filesInput : [filesInput];
    if (!rawFiles.length) return;

    const allowed = [".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".xls", ".html", ".htm"];
    const MAX_FILES = 50;
    let files = rawFiles;
    if (files.length > MAX_FILES) {
      setNotice(`Maximum ${MAX_FILES} files can be uploaded at once. Processing the first ${MAX_FILES} files.`);
      files = files.slice(0, MAX_FILES);
    }

    const newQueueItems: QueueItem[] = files.map((file) => {
      const isAllowed = allowed.some((ext) => file.name.toLowerCase().endsWith(ext));
      return {
        id: crypto.randomUUID(),
        file,
        name: file.name,
        size: file.size,
        status: isAllowed ? "queued" : "error",
        error: isAllowed ? null : "Choose a supported file (PDF, DOCX, TXT, MD, CSV, XLSX, HTML).",
      };
    });

    setUploadQueue((current) => [...newQueueItems, ...current]);
    setNotice(null);

    const validFiles = newQueueItems.filter((item) => item.status === "queued");
    if (!validFiles.length) {
      setNotice("Choose a supported file (PDF, DOCX, TXT, MD, CSV, XLSX, HTML).");
      return;
    }

    setUploading(true);

    if (validFiles.length === 1 && files.length === 1) {
      const item = validFiles[0];
      setUploadQueue((current) =>
        current.map((q) => (q.id === item.id ? { ...q, status: "uploading" } : q))
      );
      const form = new FormData();
      form.append("file", item.file);
      try {
        const uploaded = await api<DocumentRecord>("/api/documents", { method: "POST", body: form });
        const nextDocuments = await refreshLibrary();
        setSelectedDocument(uploaded.id);
        setSelectedPerson(null);
        setConnected(true);
        setUploadQueue((current) =>
          current.map((q) =>
            q.id === item.id ? { ...q, status: "ready", documentId: uploaded.id } : q
          )
        );
        const indexed = nextDocuments.find((doc) => doc.id === uploaded.id) ?? uploaded;
        const indexPresentation = documentIndexStatus(indexed.index_status);
        setNotice(
          indexPresentation.tone === "ready"
            ? `${uploaded.filename} is uploaded and ready.`
            : indexPresentation.tone === "lexical"
              ? `${uploaded.filename} is uploaded in lexical-only mode. You can chat with it now.`
              : indexPresentation.tone === "repair"
                ? `${uploaded.filename} is uploaded in lexical-only mode, but its semantic index needs repair. You can still chat with it now.`
                : `${uploaded.filename} is uploaded and indexing.`
        );
      } catch (error) {
        const msg = error instanceof Error ? error.message : "The document could not be uploaded.";
        setNotice(msg);
        setUploadQueue((current) =>
          current.map((q) => (q.id === item.id ? { ...q, status: "error", error: msg } : q))
        );
      } finally {
        setUploading(false);
        if (fileInput.current) fileInput.current.value = "";
      }
      return;
    }

    const validIds = new Set(validFiles.map((v) => v.id));
    setUploadQueue((current) =>
      current.map((q) => (validIds.has(q.id) ? { ...q, status: "uploading" } : q))
    );

    const form = new FormData();
    for (const item of validFiles) {
      form.append("files", item.file);
    }

    try {
      const result = await api<BatchUploadResponse>("/api/documents/batch", {
        method: "POST",
        body: form,
      });

      await refreshLibrary();
      setConnected(true);

      const returnedDocMap = new Map(result.documents.map((d) => [d.filename, d]));
      const errorMap = new Map(result.errors.map((e) => [e.filename, e.detail]));

      setUploadQueue((current) =>
        current.map((q) => {
          if (!validIds.has(q.id)) return q;
          const doc = returnedDocMap.get(q.name);
          if (doc) {
            return { ...q, status: "ready", documentId: doc.id };
          }
          const errDetail = errorMap.get(q.name);
          if (errDetail) {
            return { ...q, status: "error", error: errDetail };
          }
          return { ...q, status: "ready" };
        })
      );

      if (result.documents.length > 0) {
        setSelectedDocument(result.documents[result.documents.length - 1].id);
        setSelectedPerson(null);
      }

      if (result.errors.length > 0) {
        setNotice(
          `${result.documents.length} document${result.documents.length === 1 ? "" : "s"} uploaded, ${result.errors.length} failed.`
        );
      } else {
        setNotice(`All ${result.documents.length} documents uploaded and indexed.`);
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Batch upload failed.";
      setNotice(msg);
      setUploadQueue((current) =>
        current.map((q) => (validIds.has(q.id) ? { ...q, status: "error", error: msg } : q))
      );
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function retryQueueItem(item: QueueItem) {
    setUploadQueue((current) =>
      current.map((q) => (q.id === item.id ? { ...q, status: "uploading", error: null } : q))
    );
    const form = new FormData();
    form.append("file", item.file);
    try {
      const uploaded = await api<DocumentRecord>("/api/documents", { method: "POST", body: form });
      await refreshLibrary();
      setConnected(true);
      setUploadQueue((current) =>
        current.map((q) => (q.id === item.id ? { ...q, status: "ready", documentId: uploaded.id } : q))
      );
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Retry failed.";
      setUploadQueue((current) =>
        current.map((q) => (q.id === item.id ? { ...q, status: "error", error: msg } : q))
      );
    }
  }

  function clearQueue() {
    setUploadQueue((current) =>
      current.filter((item) => item.status === "uploading" || item.status === "queued")
    );
  }

  async function submitMessage(message: string, clientMessageId = crypto.randomUUID()) {
    if (thinking || !documents.length) return;
    const optimistic: Message = { id: clientMessageId, role: "user", content: message, clientMessageId, status: "pending" };
    const assistantPlaceholderId = crypto.randomUUID();
    setMessages((current) => current.some((item) => item.clientMessageId === clientMessageId)
      ? current.map((item) => item.clientMessageId === clientMessageId ? { ...item, status: "pending" } : item)
      : [...current, optimistic]);
    setThinking(true);
    setNotice(null);
    try {
      let sessionId = activeSessionId;
      if (!sessionId) {
        const session = await api<ChatSession>("/api/sessions", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            document_ids: selectedDocument === "all" ? [] : [selectedDocument],
            person: selectedPerson,
          }),
        });
        sessionId = session.id;
        setActiveSessionId(session.id);
        setSessions((current) => [session, ...current]);
      }
      const request: ChatRequest = {
        message,
        document_ids: selectedDocument === "all" ? undefined : [selectedDocument],
        person: selectedPerson || undefined,
        session_id: sessionId,
        client_message_id: clientMessageId,
      };
      await streamChat(request, {
        onMetadata: (meta) => {
          setMessages((current) => {
            const existing = current.find((item) => item.id === assistantPlaceholderId);
            if (existing) {
              return current.map((item) =>
                item.id === assistantPlaceholderId
                  ? { ...item, sources: meta.sources, mode: meta.mode, retrievalMode: meta.retrieval_mode }
                  : item
              );
            }
            const newAssistant: Message = {
              id: assistantPlaceholderId,
              role: "assistant",
              content: "",
              sources: meta.sources,
              mode: meta.mode,
              retrievalMode: meta.retrieval_mode,
              status: "pending",
            };
            return [...current, newAssistant];
          });
        },
        onToken: (delta) => {
          setMessages((current) => {
            const existing = current.find((item) => item.id === assistantPlaceholderId);
            if (existing) {
              return current.map((item) =>
                item.id === assistantPlaceholderId
                  ? { ...item, content: item.content + delta }
                  : item
              );
            }
            const newAssistant: Message = {
              id: assistantPlaceholderId,
              role: "assistant",
              content: delta,
              sources: [],
              mode: null,
              retrievalMode: null,
              status: "pending",
            };
            return [...current, newAssistant];
          });
        },
        onComplete: (data) => {
          setMessages((current) => [
            ...current.filter((item) => item.clientMessageId !== clientMessageId && item.id !== assistantPlaceholderId),
            asMessage(data.user_message),
            asMessage(data.assistant_message),
          ]);
          setActiveSessionId(data.session_id);
          setSessions((current) => {
            const next = {
              id: data.session_id,
              topic: data.topic,
              document_ids: request.document_ids ?? [],
              person: request.person ?? null,
              created_at: data.user_message.created_at,
              updated_at: data.assistant_message.created_at,
            };
            return [next, ...current.filter((session) => session.id !== next.id)];
          });
        },
        onError: (err) => {
          setMessages((current) =>
            current
              .filter((item) => item.id !== assistantPlaceholderId)
              .map((item) =>
                item.clientMessageId === clientMessageId
                  ? { ...item, status: "failed" }
                  : item
              )
          );
          setNotice(err.message || "I could not answer that question.");
        },
      });
    } catch (error) {
      setMessages((current) =>
        current
          .filter((item) => item.id !== assistantPlaceholderId)
          .map((item) =>
            item.clientMessageId === clientMessageId
              ? { ...item, status: "failed" }
              : item
          )
      );
      setNotice(error instanceof Error ? error.message : "I could not answer that question.");
    } finally {
      setThinking(false);
    }
  }

  async function sendMessage(event: FormEvent) {
    event.preventDefault();
    const message = question.trim();
    if (!message || thinking || !documents.length) return;
    setQuestion("");
    await submitMessage(message);
  }

  async function selectSession(sessionId: string) {
    if (sessionId === activeSessionId || thinking) return;
    try {
      const session = await api<ChatSession>(`/api/sessions/${sessionId}`);
      setActiveSessionId(session.id);
      setMessages((session.messages ?? []).map(asMessage));
      setSelectedDocument(session.document_ids[0] ?? "all");
      setSelectedPerson(session.person);
      setQuestion("");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "That conversation could not be loaded.");
    }
  }

  function newConversation() {
    if (thinking) return;
    setActiveSessionId(null);
    setMessages([]);
    setQuestion("");
  }

  async function renameConversation() {
    if (!activeSessionId || thinking) return;
    const current = sessions.find((session) => session.id === activeSessionId);
    const topic = window.prompt("Conversation topic", current?.topic ?? "New conversation")?.trim();
    if (!topic || topic === current?.topic) return;
    try {
      const updated = await api<ChatSession>(`/api/sessions/${activeSessionId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic }),
      });
      setSessions((currentSessions) => [updated, ...currentSessions.filter((session) => session.id !== updated.id)]);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "The conversation could not be renamed.");
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

  async function importUrl(url: string) {
    if (!url.trim()) return;
    setUploading(true);
    setNotice(null);
    try {
      const doc = await api<DocumentRecord>("/api/documents/url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: url.trim() }),
      });
      await refreshLibrary();
      setSelectedDocument(doc.id);
      setSelectedPerson(null);
      setConnected(true);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Failed to import URL.";
      setNotice(msg);
    } finally {
      setUploading(false);
    }
  }

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
        onUpload={(files) => void uploadDocuments(files)}
        onImportUrl={(url) => void importUrl(url)}
        onCheckStatus={() => void checkDocumentStatus()}
        onSelectDocument={selectDocument}
        onRemoveDocument={(document) => void removeDocument(document)}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onNewConversation={newConversation}
        onSelectSession={(sessionId) => void selectSession(sessionId)}
        uploadQueue={uploadQueue}
        onRetryQueueItem={(item) => void retryQueueItem(item)}
        onClearQueue={clearQueue}
      />

      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <span className="eyebrow">Conversation</span>
            <h1>{sessions.find((session) => session.id === activeSessionId)?.topic ?? scopedDocument?.filename ?? "Your document library"}</h1>
          </div>
          <div className="chat-header-actions">
            {activeSessionId && <button className="rename-conversation" type="button" onClick={() => void renameConversation()}>Rename</button>}
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
                    {message.status === "failed" && message.role === "user" && (
                      <button className="retry-message" type="button" onClick={() => void submitMessage(message.content, message.clientMessageId ?? message.id)}>
                        Couldn’t send. Retry
                      </button>
                    )}
                  </div>
                </article>
              ))}
              {thinking && !messages.some((m) => m.role === "assistant" && m.status === "pending" && m.content) && (
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
            <div><strong>{people.length}</strong><span>subjects found</span></div>
          </div>
          {uploading && <p className="indexing-status" role="status"><span className="state-spinner" aria-hidden="true" /> Indexing your upload</p>}
          <div className="people-heading">
            <span className="eyebrow">Subjects in scope</span>
            <span className="people-count">{visiblePeople.length}</span>
          </div>
          {loading ? (
            <div className="people-empty people-loading" role="status"><span className="state-spinner" aria-hidden="true" /><p>Loading subjects…</p></div>
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
                    <small>{subjectDescription(person)}</small>
                  </span>
                  <b aria-hidden="true">›</b>
                </button>
              ))}
            </div>
          ) : (
            <div className="people-empty">
              <span>◇</span>
              <p>{documents.length ? "No subjects were found in this document." : "Subjects will appear here after your first document is indexed."}</p>
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
