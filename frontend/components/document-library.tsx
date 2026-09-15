"use client";

import { useState } from "react";
import type { DragEvent, RefObject } from "react";
import { DocumentIndexStatus } from "@/app/document-index-status.mjs";
import type { ChatSession, DocumentRecord } from "@/lib/api";
import { UploadQueue, type QueueItem } from "./upload-queue";

type DocumentLibraryProps = {
  documents: DocumentRecord[];
  peopleCount: number;
  selectedDocument: string;
  loading: boolean;
  uploading: boolean;
  checkingStatus: boolean;
  fileInput: RefObject<HTMLInputElement | null>;
  onUpload: (files: File | File[]) => void;
  onCheckStatus: () => void;
  onSelectDocument: (document: DocumentRecord | "all") => void;
  onRemoveDocument: (document: DocumentRecord) => void;
  sessions: ChatSession[];
  activeSessionId: string | null;
  onNewConversation: () => void;
  onSelectSession: (sessionId: string) => void;
  uploadQueue?: QueueItem[];
  onRetryQueueItem?: (item: QueueItem) => void;
  onClearQueue?: () => void;
  onImportUrl?: (url: string) => void;
};

function humanSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function documentKind(filename: string) {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (ext === "csv") return "CSV";
  if (ext === "xlsx" || ext === "xls") return "XLSX";
  if (ext === "html" || ext === "htm") return "WEB";
  if (ext === "pdf") return "PDF";
  if (ext === "docx" || ext === "doc") return "DOC";
  if (ext === "md") return "MD";
  if (ext === "txt") return "TXT";
  return ext.toUpperCase() || "DOC";
}

async function extractFilesFromDataTransfer(dataTransfer: DataTransfer): Promise<File[]> {
  const items = dataTransfer.items;
  if (items && items.length > 0) {
    const entries: unknown[] = [];
    for (let i = 0; i < items.length; i++) {
      const item = items[i];
      if (item.kind === "file") {
        const entry = (item as unknown as { webkitGetAsEntry?: () => unknown }).webkitGetAsEntry
          ? (item as unknown as { webkitGetAsEntry: () => unknown }).webkitGetAsEntry()
          : null;
        if (entry) {
          entries.push(entry);
        } else {
          const file = item.getAsFile();
          if (file) return Array.from(dataTransfer.files ?? []);
        }
      }
    }

    if (entries.length > 0) {
      const collected: File[] = [];
      async function traverse(entry: unknown): Promise<void> {
        const e = entry as {
          isFile?: boolean;
          isDirectory?: boolean;
          file?: (cb: (f: File) => void, err: () => void) => void;
          createReader?: () => { readEntries: (cb: (r: unknown[]) => void, err: () => void) => void };
        };
        if (e.isFile && e.file) {
          const f = await new Promise<File | null>((res) => {
            e.file!((file: File) => res(file), () => res(null));
          });
          if (f) collected.push(f);
        } else if (e.isDirectory && e.createReader) {
          const reader = e.createReader();
          const batch = await new Promise<unknown[]>((res) => {
            reader.readEntries((r: unknown[]) => res(r), () => res([]));
          });
          for (const child of batch) {
            await traverse(child);
          }
        }
      }
      for (const entry of entries) {
        await traverse(entry);
      }
      if (collected.length > 0) return collected;
    }
  }

  return Array.from(dataTransfer.files ?? []);
}

export function DocumentLibrary({
  documents,
  peopleCount,
  selectedDocument,
  loading,
  uploading,
  checkingStatus,
  fileInput,
  onUpload,
  onCheckStatus,
  onSelectDocument,
  onRemoveDocument,
  sessions,
  activeSessionId,
  onNewConversation,
  onSelectSession,
  uploadQueue = [],
  onRetryQueueItem,
  onClearQueue,
  onImportUrl,
}: DocumentLibraryProps) {
  const [dragging, setDragging] = useState(false);
  const [urlInput, setUrlInput] = useState("");

  async function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const files = await extractFilesFromDataTransfer(event.dataTransfer);
    if (files.length) onUpload(files);
  }

  return (
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
        onDrop={(event) => void onDrop(event)}
      >
        <span className="upload-symbol" aria-hidden="true">↑</span>
        <div>
          <p>{uploading ? "Indexing your documents…" : "Add a document"}</p>
          <span>PDF, DOCX, TXT, MD, CSV, XLSX · Up to 50 files</span>
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
          multiple
          accept=".pdf,.docx,.txt,.md,.csv,.xlsx,.xls,.html,.htm"
          onChange={(event) => {
            const files = Array.from(event.target.files ?? []);
            if (files.length) onUpload(files);
          }}
        />
      </div>

      {onImportUrl && (
        <form
          className="url-import-form"
          onSubmit={(e) => {
            e.preventDefault();
            if (urlInput.trim()) {
              onImportUrl(urlInput.trim());
              setUrlInput("");
            }
          }}
        >
          <input
            type="url"
            className="url-import-input"
            placeholder="Import URL (e.g. https://...)"
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            disabled={uploading}
            aria-label="Web URL to import"
          />
          <button
            className="url-import-button"
            type="submit"
            disabled={uploading || !urlInput.trim()}
          >
            Import
          </button>
        </form>
      )}

      {uploadQueue.length > 0 && (
        <UploadQueue
          items={uploadQueue}
          onRetry={onRetryQueueItem ?? (() => {})}
          onClear={onClearQueue ?? (() => {})}
        />
      )}

      <div className="section-heading">
        <span>Library</span>
        <div className="section-actions">
          <span>{documents.length}</span>
          <button
            className="status-check-button"
            type="button"
            onClick={onCheckStatus}
            disabled={loading || uploading || checkingStatus}
          >
            {checkingStatus ? "Checking…" : "Check status"}
          </button>
        </div>
      </div>

      <nav className="document-list" aria-label="Document scope">
        <button
          type="button"
          className={`document-item all-documents ${selectedDocument === "all" ? "is-active" : ""}`}
          onClick={() => onSelectDocument("all")}
          aria-current={selectedDocument === "all" ? "true" : undefined}
        >
          <span className="document-icon">◎</span>
          <span className="document-copy">
            <strong>All documents</strong>
            <small>{peopleCount} people in scope</small>
          </span>
        </button>
        {loading ? (
          <div className="document-state" role="status">
            <span className="state-spinner" aria-hidden="true" />
            <span>Loading your library…</span>
          </div>
        ) : uploading ? (
          <div className="document-state is-indexing" role="status">
            <span className="state-spinner" aria-hidden="true" />
            <span>Indexing document…</span>
          </div>
        ) : !documents.length ? (
          <div className="document-state">
            <span aria-hidden="true">◇</span>
            <span>Your uploaded documents will appear here.</span>
          </div>
        ) : documents.map((document) => (
          <div className={`document-row ${selectedDocument === document.id ? "is-active" : ""}`} key={document.id}>
            <button
              type="button"
              className="document-item"
              onClick={() => onSelectDocument(document)}
              aria-current={selectedDocument === document.id ? "true" : undefined}
              title={document.filename}
            >
              <span className={`file-badge is-${documentKind(document.filename).toLowerCase()}`}>{documentKind(document.filename)}</span>
              <span className="document-copy">
                <strong title={document.filename}>{document.filename}</strong>
                <small className="document-meta">
                  <span>{documentKind(document.filename)}</span>
                  <span>{humanSize(document.size_bytes)}</span>
                  <span>{document.people.length} {document.people.length === 1 ? "person" : "people"}</span>
                </small>
                <DocumentIndexStatus status={document.index_status} />
              </span>
            </button>
            <button
              className="remove-button"
              type="button"
              aria-label={`Remove ${document.filename}`}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={(event) => {
                event.stopPropagation();
                onRemoveDocument(document);
              }}
            >
              ×
            </button>
          </div>
        ))}
      </nav>

      <div className="conversation-history-heading">
        <span>Conversations</span>
        <button type="button" onClick={onNewConversation}>New</button>
      </div>
      <nav className="conversation-history" aria-label="Conversation history">
        {sessions.length ? sessions.map((session) => (
          <button
            key={session.id}
            type="button"
            className={activeSessionId === session.id ? "is-active" : ""}
            onClick={() => onSelectSession(session.id)}
          >
            <strong>{session.topic}</strong>
            <small>{new Date(session.updated_at).toLocaleString()}</small>
          </button>
        )) : <p>No saved conversations yet.</p>}
      </nav>

      <div className="privacy-note">
        <span className="privacy-dot" aria-hidden="true" />
        <div>
          <strong>Local by design</strong>
          <p>Files stay inside your Docker volume.</p>
        </div>
      </div>
    </aside>
  );
}
