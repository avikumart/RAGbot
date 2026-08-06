"use client";

import { useState } from "react";
import type { DragEvent, RefObject } from "react";
import { DocumentIndexStatus } from "@/app/document-index-status.mjs";
import type { DocumentRecord } from "@/lib/api";

type DocumentLibraryProps = {
  documents: DocumentRecord[];
  peopleCount: number;
  selectedDocument: string;
  loading: boolean;
  uploading: boolean;
  checkingStatus: boolean;
  fileInput: RefObject<HTMLInputElement | null>;
  onUpload: (file: File) => void;
  onCheckStatus: () => void;
  onSelectDocument: (document: DocumentRecord | "all") => void;
  onRemoveDocument: (document: DocumentRecord) => void;
};

function humanSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function documentKind(filename: string) {
  return filename.split(".").pop()?.toUpperCase() || "DOC";
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
}: DocumentLibraryProps) {
  const [dragging, setDragging] = useState(false);

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) onUpload(file);
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
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onUpload(file);
          }}
        />
      </div>

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
              <span className="file-badge">{documentKind(document.filename)}</span>
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
