"use client";

import { useEffect, useRef, useState } from "react";
import type { Source } from "../lib/api";

export type PDFViewerProps = {
  source: Source | null;
  onClose: () => void;
};

type HighlightRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

interface PDFPageProxy {
  view: number[];
  getViewport: (options: { scale: number }) => { width: number; height: number };
  render: (options: { canvasContext: CanvasRenderingContext2D; viewport: unknown }) => { promise: Promise<unknown> };
  getTextContent: () => Promise<{ items: unknown[] }>;
}

interface PDFDocProxy {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PDFPageProxy>;
  destroy?: () => void;
}

export function PDFViewer({ source, onClose }: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(1);
  const [currentPage, setCurrentPage] = useState<number>(source?.page || 1);
  const [scale, setScale] = useState<number>(1.15);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [pdfDoc, setPdfDoc] = useState<PDFDocProxy | null>(null);
  const [highlightRects, setHighlightRects] = useState<HighlightRect[]>([]);
  const [nonPdfText, setNonPdfText] = useState<string | null>(null);
  const [viewportSize, setViewportSize] = useState<{ width: number; height: number }>({ width: 0, height: 0 });

  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const textContainerRef = useRef<HTMLDivElement | null>(null);
  const drawerRef = useRef<HTMLElement | null>(null);

  const filename = source?.filename || "Document";
  const isPdf = filename.toLowerCase().endsWith(".pdf");

  // Handle ESC key to close
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        onClose();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  // Load Document (PDF or Non-PDF Fallback)
  useEffect(() => {
    if (!source) return;

    let active = true;
    const fileUrl = `/api/documents/${source.document_id}/file`;

    if (!isPdf) {
      const isOffice = filename.endsWith(".docx") || filename.endsWith(".xlsx");
      if (isOffice) {
        fetch(`/api/documents/${source.document_id}`)
          .then((res) => {
            if (!res.ok) throw new Error(`Failed to load document (${res.status})`);
            return res.json();
          })
          .then((data) => {
            if (!active) return;
            const fullText = (data.chunks || [])
              .map((c: { content: string }) => c.content)
              .join("\n\n");
            setNonPdfText(fullText || source.excerpt);
            setLoading(false);
          })
          .catch(() => {
            if (!active) return;
            setNonPdfText(source.excerpt);
            setLoading(false);
          });
      } else {
        fetch(fileUrl)
          .then((res) => {
            if (!res.ok) throw new Error(`Failed to load file (${res.status})`);
            return res.text();
          })
          .then((text) => {
            if (!active) return;
            setNonPdfText(text || source.excerpt);
            setLoading(false);
          })
          .catch(() => {
            if (!active) return;
            setNonPdfText(source.excerpt);
            setLoading(false);
          });
      }
      return () => {
        active = false;
      };
    }

    // PDF loading via PDF.js
    let currentLoadingTask: { promise: Promise<PDFDocProxy>; destroy: () => void } | null = null;

    async function loadPdf() {
      try {
        const pdfjs = await import("pdfjs-dist");
        if (typeof window !== "undefined" && !pdfjs.GlobalWorkerOptions.workerSrc) {
          pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
        }

        const task = pdfjs.getDocument({
          url: fileUrl,
          cMapUrl: "https://unpkg.com/pdfjs-dist@6.4.299/cmaps/",
          cMapPacked: true,
        });
        currentLoadingTask = task as unknown as { promise: Promise<PDFDocProxy>; destroy: () => void };

        const doc = await currentLoadingTask.promise;
        if (!active) return;
        setPdfDoc(doc);
        setNumPages(doc.numPages);
        setLoading(false);
      } catch (loadErr) {
        if (!active) return;
        console.warn("PDF loading encountered an error, falling back to excerpt view:", loadErr);
        setError("Could not render PDF directly. Falling back to excerpt view.");
        setNonPdfText(source?.excerpt || "No excerpt available.");
        setLoading(false);
      }
    }

    void loadPdf();

    return () => {
      active = false;
      if (currentLoadingTask) {
        try {
          currentLoadingTask.destroy();
        } catch {}
      }
    };
  }, [source, isPdf, filename]);

  // Render Canvas Page & Compute Highlighting
  useEffect(() => {
    if (!pdfDoc || !isPdf || !source) return;
    let cancelled = false;

    async function doRender() {
      if (!pdfDoc) return;
      try {
        const page = await pdfDoc.getPage(currentPage);
        if (cancelled) return;
        const viewport = page.getViewport({ scale });
        setViewportSize({ width: viewport.width, height: viewport.height });

        const canvas = canvasRef.current;
        if (!canvas) return;
        const context = canvas.getContext("2d");
        if (!context) return;

        canvas.width = viewport.width;
        canvas.height = viewport.height;

        await page.render({
          canvasContext: context,
          viewport,
        }).promise;
        if (cancelled) return;

        // Extract text content to locate excerpt highlights
        const textContent = await page.getTextContent();
        if (cancelled) return;

        const rects: HighlightRect[] = [];
        const excerptWords = source.excerpt
          .toLowerCase()
          .replace(/[^a-z0-9\s]/g, " ")
          .split(/\s+/)
          .filter((w) => w.length > 2);

        if (excerptWords.length > 0 && Array.isArray(textContent.items)) {
          for (const rawItem of textContent.items) {
            const item = rawItem as { str?: string; transform?: number[]; width?: number; height?: number };
            if (!item.str) continue;
            const itemText = item.str.toLowerCase();
            const matches = excerptWords.some((word) => itemText.includes(word));
            if (matches && item.transform) {
              const [, , , , tx, ty] = item.transform;
              // PDF.js coordinate conversion: y is inverted from bottom
              const x = tx * scale;
              const y = (page.view[3] - ty) * scale;
              const w = (item.width || 40) * scale;
              const h = ((item.height || 12) * scale) * 1.2;

              rects.push({
                left: Math.max(0, x),
                top: Math.max(0, y - h),
                width: Math.max(10, w),
                height: Math.max(12, h),
              });
            }
          }
        }

        setHighlightRects(rects);
      } catch (renderErr) {
        console.warn("Error rendering PDF page:", renderErr);
      }
    }

    void doRender();

    return () => {
      cancelled = true;
    };
  }, [pdfDoc, currentPage, scale, isPdf, source]);

  // Scroll highlighted text into view in non-PDF mode
  useEffect(() => {
    if (nonPdfText && textContainerRef.current) {
      const mark = textContainerRef.current.querySelector("mark");
      if (mark) {
        mark.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }
  }, [nonPdfText]);

  if (!source) return null;

  return (
    <>
      <div
        className="citation-viewer-backdrop"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside
        ref={drawerRef}
        className="citation-viewer-drawer open"
        role="dialog"
        aria-label={`Citation Document Viewer: ${filename}`}
        aria-modal="true"
        data-testid="citation-viewer-drawer"
      >
        {/* Top Header & Controls */}
        <header className="viewer-header">
          <div className="viewer-title-group">
            <span className="viewer-type-badge">
              {filename.split(".").pop()?.toUpperCase() || "DOC"}
            </span>
            <div className="viewer-title-text">
              <h2 title={filename}>{filename}</h2>
              <small>
                {source.page ? `Cited on Page ${source.page}` : "Cited passage"} · {Math.round(source.score * 100)}% match
              </small>
            </div>
          </div>

          <div className="viewer-actions">
            {isPdf && !error && (
              <>
                <div className="viewer-pagination" role="group" aria-label="Page navigation">
                  <button
                    type="button"
                    className="viewer-btn"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage <= 1}
                    aria-label="Previous page"
                    data-testid="prev-page-btn"
                  >
                    ‹
                  </button>
                  <span className="viewer-page-indicator" data-testid="page-indicator">
                    {currentPage} / {numPages}
                  </span>
                  <button
                    type="button"
                    className="viewer-btn"
                    onClick={() => setCurrentPage((p) => Math.min(numPages, p + 1))}
                    disabled={currentPage >= numPages}
                    aria-label="Next page"
                    data-testid="next-page-btn"
                  >
                    ›
                  </button>
                </div>

                <div className="viewer-zoom" role="group" aria-label="Zoom controls">
                  <button
                    type="button"
                    className="viewer-btn"
                    onClick={() => setScale((s) => Math.max(0.6, s - 0.2))}
                    disabled={scale <= 0.6}
                    aria-label="Zoom out"
                    data-testid="zoom-out-btn"
                  >
                    -
                  </button>
                  <span className="viewer-zoom-label">
                    {Math.round(scale * 100)}%
                  </span>
                  <button
                    type="button"
                    className="viewer-btn"
                    onClick={() => setScale((s) => Math.min(2.5, s + 0.2))}
                    disabled={scale >= 2.5}
                    aria-label="Zoom in"
                    data-testid="zoom-in-btn"
                  >
                    +
                  </button>
                  <button
                    type="button"
                    className="viewer-btn viewer-fit-btn"
                    onClick={() => setScale(1.15)}
                    aria-label="Reset zoom"
                    data-testid="zoom-fit-btn"
                  >
                    Fit
                  </button>
                </div>
              </>
            )}

            <button
              type="button"
              className="viewer-close-btn"
              onClick={onClose}
              aria-label="Close viewer"
              data-testid="close-viewer-btn"
            >
              ✕
            </button>
          </div>
        </header>

        {/* Citation Excerpt Callout Banner */}
        <div className="viewer-excerpt-banner" data-testid="citation-highlight">
          <div className="excerpt-banner-header">
            <span className="excerpt-banner-tag">ACTIVE CITATION [{source.index}]</span>
            {source.page && <span className="excerpt-page-tag">Page {source.page}</span>}
          </div>
          <p className="excerpt-text">
            “{source.excerpt}”
          </p>
        </div>

        {/* Main Body */}
        <div className="viewer-body">
          {loading && (
            <div className="viewer-loading" role="status">
              <span className="state-spinner" aria-hidden="true" />
              <p>Loading document content…</p>
            </div>
          )}

          {error && (
            <div className="viewer-error-banner" role="alert">
              <span>{error}</span>
            </div>
          )}

          {/* PDF Canvas View */}
          {isPdf && !error && (
            <div className="viewer-canvas-scroll">
              <div
                className="viewer-canvas-wrapper"
                style={{
                  width: viewportSize.width || "auto",
                  height: viewportSize.height || "auto",
                }}
              >
                <canvas ref={canvasRef} data-testid="pdf-canvas" />

                {/* Visual Highlight Overlay Boxes */}
                {highlightRects.map((rect, idx) => (
                  <div
                    key={`hl-${idx}`}
                    className="pdf-highlight-box"
                    style={{
                      left: `${rect.left}px`,
                      top: `${rect.top}px`,
                      width: `${rect.width}px`,
                      height: `${rect.height}px`,
                    }}
                    title="Cited excerpt match"
                  />
                ))}
              </div>
            </div>
          )}

          {/* Non-PDF Fallback Text View */}
          {(!isPdf || error) && nonPdfText && (
            <div className="viewer-text-container" ref={textContainerRef} data-testid="non-pdf-viewer">
              <div className="text-viewer-card">
                <div className="text-viewer-content">
                  {renderHighlightedPassage(nonPdfText, source.excerpt)}
                </div>
              </div>
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

function renderHighlightedPassage(fullText: string, excerpt: string) {
  if (!excerpt || !fullText) {
    return <pre className="raw-document-text">{fullText}</pre>;
  }

  const cleanExcerpt = excerpt.trim();
  const lowerFull = fullText.toLowerCase();
  const lowerExcerpt = cleanExcerpt.toLowerCase();
  const index = lowerFull.indexOf(lowerExcerpt);

  if (index === -1) {
    return (
      <div className="text-content-wrapper">
        <div className="fuzzy-highlight-block">
          <strong>Cited Excerpt:</strong>
          <p>{cleanExcerpt}</p>
        </div>
        <pre className="raw-document-text">{fullText}</pre>
      </div>
    );
  }

  const before = fullText.slice(0, index);
  const match = fullText.slice(index, index + cleanExcerpt.length);
  const after = fullText.slice(index + cleanExcerpt.length);

  return (
    <pre className="raw-document-text">
      {before}
      <mark className="passage-highlight" data-testid="passage-highlight">
        {match}
      </mark>
      {after}
    </pre>
  );
}
