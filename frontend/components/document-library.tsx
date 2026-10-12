"use client";

import { useState } from "react";
import type { DragEvent, FormEvent, RefObject } from "react";
import { DocumentIndexStatus } from "@/app/document-index-status.mjs";
import type { ChatSession, CollectionRecord, DocumentRecord } from "@/lib/api";
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
  collections?: CollectionRecord[];
  selectedCollection?: string | null;
  onSelectCollection?: (collectionId: string | null) => void;
  onCreateCollection?: (name: string, description?: string | null) => Promise<void> | void;
  onUpdateCollection?: (collectionId: string, name: string, description?: string | null) => Promise<void> | void;
  onDeleteCollection?: (collection: CollectionRecord) => Promise<void> | void;
  onToggleCollectionDocument?: (collectionId: string, documentId: string, shouldInclude: boolean) => Promise<void> | void;
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
  collections = [],
  selectedCollection = null,
  onSelectCollection,
  onCreateCollection,
  onUpdateCollection,
  onDeleteCollection,
  onToggleCollectionDocument,
}: DocumentLibraryProps) {
  const [dragging, setDragging] = useState(false);
  const [urlInput, setUrlInput] = useState("");
  const [creatingCollection, setCreatingCollection] = useState(false);
  const [newCollectionName, setNewCollectionName] = useState("");
  const [newCollectionDesc, setNewCollectionDesc] = useState("");
  const [editingCollectionId, setEditingCollectionId] = useState<string | null>(null);
  const [editCollectionName, setEditCollectionName] = useState("");
  const [editCollectionDesc, setEditCollectionDesc] = useState("");
  const [managingDocsForId, setManagingDocsForId] = useState<string | null>(null);

  const activeCollection = collections.find((c) => c.id === selectedCollection) ?? null;
  const displayedDocuments = activeCollection
    ? documents.filter((d) => activeCollection.document_ids.includes(d.id))
    : documents;

  async function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const files = await extractFilesFromDataTransfer(event.dataTransfer);
    if (files.length) onUpload(files);
  }

  async function handleCreateSubmit(event: FormEvent) {
    event.preventDefault();
    const trimmed = newCollectionName.trim();
    if (!trimmed || !onCreateCollection) return;
    await onCreateCollection(trimmed, newCollectionDesc.trim() || null);
    setNewCollectionName("");
    setNewCollectionDesc("");
    setCreatingCollection(false);
  }

  async function handleEditSubmit(event: FormEvent) {
    event.preventDefault();
    if (!editingCollectionId || !onUpdateCollection) return;
    const trimmed = editCollectionName.trim();
    if (!trimmed) return;
    await onUpdateCollection(editingCollectionId, trimmed, editCollectionDesc.trim() || null);
    setEditingCollectionId(null);
  }

  function startEditing(col: CollectionRecord) {
    setEditingCollectionId(col.id);
    setEditCollectionName(col.name);
    setEditCollectionDesc(col.description ?? "");
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
          {onCreateCollection && (
            <button
              className="status-check-button new-collection-button"
              type="button"
              onClick={() => setCreatingCollection((prev) => !prev)}
              aria-label="New collection"
              data-testid="new-collection-btn"
            >
              + Collection
            </button>
          )}
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

      {creatingCollection && (
        <form
          className="collection-form"
          onSubmit={(e) => void handleCreateSubmit(e)}
          data-testid="create-collection-form"
        >
          <input
            type="text"
            className="collection-input"
            placeholder="Collection name (e.g. Q3 Due Diligence)"
            value={newCollectionName}
            onChange={(e) => setNewCollectionName(e.target.value)}
            aria-label="Collection name"
            data-testid="collection-name-input"
            maxLength={120}
            required
          />
          <input
            type="text"
            className="collection-input"
            placeholder="Description (optional)"
            value={newCollectionDesc}
            onChange={(e) => setNewCollectionDesc(e.target.value)}
            aria-label="Collection description"
            data-testid="collection-description-input"
            maxLength={500}
          />
          <div className="collection-form-actions">
            <button
              type="submit"
              className="collection-submit-btn"
              disabled={!newCollectionName.trim()}
              data-testid="save-collection-btn"
            >
              Create
            </button>
            <button
              type="button"
              className="collection-cancel-btn"
              onClick={() => {
                setCreatingCollection(false);
                setNewCollectionName("");
                setNewCollectionDesc("");
              }}
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {collections.length > 0 && (
        <div className="collection-filter-bar" role="group" aria-label="Collection filters" data-testid="collection-filter-bar">
          <button
            type="button"
            className={`collection-chip ${!selectedCollection ? "is-active" : ""}`}
            onClick={() => {
              onSelectCollection?.(null);
              onSelectDocument("all");
            }}
            aria-pressed={!selectedCollection}
            data-testid="collection-chip-all"
          >
            <span>All</span>
            <small>{documents.length}</small>
          </button>
          {collections.map((col) => (
            <button
              key={col.id}
              type="button"
              className={`collection-chip ${selectedCollection === col.id ? "is-active" : ""}`}
              onClick={() => {
                const next = selectedCollection === col.id ? null : col.id;
                onSelectCollection?.(next);
              }}
              aria-pressed={selectedCollection === col.id}
              data-testid={`collection-chip-${col.id}`}
              title={col.description || col.name}
            >
              <span aria-hidden="true">📁</span>
              <span className="collection-chip-name">{col.name}</span>
              <small>{col.document_ids.length}</small>
            </button>
          ))}
        </div>
      )}

      {activeCollection && (
        <div className="collection-folder-card" data-testid="active-collection-card">
          {editingCollectionId === activeCollection.id ? (
            <form className="collection-edit-form" onSubmit={(e) => void handleEditSubmit(e)}>
              <input
                type="text"
                className="collection-input"
                value={editCollectionName}
                onChange={(e) => setEditCollectionName(e.target.value)}
                aria-label="Edit collection name"
                data-testid="edit-collection-name-input"
                maxLength={120}
                required
              />
              <input
                type="text"
                className="collection-input"
                value={editCollectionDesc}
                onChange={(e) => setEditCollectionDesc(e.target.value)}
                placeholder="Description (optional)"
                aria-label="Edit collection description"
                data-testid="edit-collection-description-input"
                maxLength={500}
              />
              <div className="collection-form-actions">
                <button
                  type="submit"
                  className="collection-submit-btn"
                  disabled={!editCollectionName.trim()}
                  data-testid="confirm-edit-collection-btn"
                >
                  Save
                </button>
                <button
                  type="button"
                  className="collection-cancel-btn"
                  onClick={() => setEditingCollectionId(null)}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <div className="collection-folder-header">
              <div className="collection-folder-title">
                <strong>📁 {activeCollection.name}</strong>
                {activeCollection.description && <small>{activeCollection.description}</small>}
              </div>
              <div className="collection-folder-actions">
                <button
                  type="button"
                  className="collection-action-btn"
                  onClick={() =>
                    setManagingDocsForId((prev) => (prev === activeCollection.id ? null : activeCollection.id))
                  }
                  aria-label={`Assign documents to ${activeCollection.name}`}
                  data-testid="manage-collection-docs-btn"
                >
                  Assign ({activeCollection.document_ids.length})
                </button>
                <button
                  type="button"
                  className="collection-action-btn"
                  onClick={() => startEditing(activeCollection)}
                  aria-label={`Edit ${activeCollection.name}`}
                  data-testid="edit-collection-btn"
                >
                  Edit
                </button>
                <button
                  type="button"
                  className="collection-action-btn is-danger"
                  onClick={() => onDeleteCollection?.(activeCollection)}
                  aria-label={`Delete ${activeCollection.name}`}
                  data-testid="delete-collection-btn"
                >
                  Delete
                </button>
              </div>
            </div>
          )}

          {(managingDocsForId === activeCollection.id || activeCollection.document_ids.length === 0) && documents.length > 0 && (
            <div className="collection-assign-list" data-testid="collection-assign-list">
              <span className="collection-assign-title">Assign documents to folder:</span>
              {documents.map((doc) => {
                const isMember = activeCollection.document_ids.includes(doc.id);
                return (
                  <label key={doc.id} className="collection-assign-item">
                    <input
                      type="checkbox"
                      checked={isMember}
                      onChange={(e) => {
                        setManagingDocsForId(activeCollection.id);
                        onToggleCollectionDocument?.(activeCollection.id, doc.id, e.target.checked);
                      }}
                      aria-label={`Include ${doc.filename} in ${activeCollection.name}`}
                      data-testid={`assign-doc-${doc.id}`}
                    />
                    <span title={doc.filename}>{doc.filename}</span>
                  </label>
                );
              })}
            </div>
          )}
        </div>
      )}

      <nav className="document-list" aria-label="Document scope">
        <button
          type="button"
          className={`document-item all-documents ${selectedDocument === "all" && !selectedCollection ? "is-active" : ""}`}
          onClick={() => {
            onSelectCollection?.(null);
            onSelectDocument("all");
          }}
          aria-current={selectedDocument === "all" && !selectedCollection ? "true" : undefined}
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
        ) : !displayedDocuments.length ? (
          <div className="document-state" data-testid="empty-collection-state">
            <span aria-hidden="true">📁</span>
            <span>No documents assigned to this collection yet.</span>
          </div>
        ) : displayedDocuments.map((document) => {
          const memberCollections = collections.filter((c) => c.document_ids.includes(document.id));
          return (
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
                  {memberCollections.length > 0 && (
                    <span className="document-collection-tags">
                      {memberCollections.map((c) => (
                        <span key={c.id} className="document-collection-tag">📁 {c.name}</span>
                      ))}
                    </span>
                  )}
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
          );
        })}
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

