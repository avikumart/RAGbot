import React, { useState, useEffect } from "react";

export function PersonaDossierModal({
  isOpen,
  personName,
  dossier,
  loading = false,
  error = null,
  onClose,
  onSelectCitation,
}) {
  const [viewMode, setViewMode] = useState("preview");
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    function handleKeyDown(e) {
      if (e.key === "Escape" && isOpen && onClose) {
        onClose();
      }
    }
    if (typeof window !== "undefined") {
      window.addEventListener("keydown", handleKeyDown);
      return () => window.removeEventListener("keydown", handleKeyDown);
    }
  }, [isOpen, onClose]);

  if (!isOpen) {
    return null;
  }

  function handleCopyMarkdown() {
    if (!dossier?.markdown) return;
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(dossier.markdown).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  }

  function handleDownloadMarkdown() {
    if (!dossier?.markdown || typeof window === "undefined") return;
    const filename = `${(personName || "persona").toLowerCase().replace(/[^a-z0-9_-]+/g, "_")}_dossier.md`;
    const blob = new Blob([dossier.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(url);
  }

  function handleExportPDF() {
    if (typeof window !== "undefined") {
      window.print();
    }
  }

  function handleCitationClick(citationIndex) {
    if (!dossier || !onSelectCitation) return;
    const match = dossier.sources?.find((s) => s.index === citationIndex);
    if (match) {
      onSelectCitation({
        index: match.index,
        document_id: match.document_id,
        filename: match.filename,
        page: match.page,
        excerpt: match.excerpt,
        score: match.score,
      });
    }
  }

  function renderInlineCitations(text) {
    if (!text) return null;
    const parts = text.split(/(\[\d+\])/g);
    return parts.map((part, i) => {
      const match = part.match(/^\[(\d+)\]$/);
      if (match) {
        const index = parseInt(match[1], 10);
        return React.createElement(
          "button",
          {
            key: i,
            type: "button",
            className: "dossier-cite-btn",
            title: `View verified excerpt [${index}]`,
            "aria-label": `View verified excerpt ${index}`,
            onClick: () => handleCitationClick(index),
          },
          `[${index}]`
        );
      }
      return React.createElement("span", { key: i }, part);
    });
  }

  return React.createElement(
    "div",
    {
      className: "dossier-overlay",
      role: "dialog",
      "aria-modal": "true",
      "aria-label": "Executive Briefing Dossier",
    },
    React.createElement(
      "div",
      { className: "dossier-modal" },
      React.createElement(
        "header",
        { className: "dossier-header" },
        React.createElement(
          "div",
          { className: "dossier-title-area" },
          React.createElement("span", { className: "eyebrow" }, "Autonomous Executive Briefing"),
          React.createElement(
            "h2",
            { className: "dossier-title" },
            personName ? `Executive Briefing: ${personName}` : "Executive Dossier"
          ),
          dossier &&
            React.createElement(
              "div",
              { className: "dossier-meta-badges" },
              React.createElement(
                "span",
                { className: "dossier-badge scope-badge" },
                `Scope: ${dossier.scope?.summary || "Entire Library"}`
              ),
              React.createElement(
                "span",
                { className: "dossier-badge provenance-badge" },
                `✓ 100% Grounded (${dossier.sources?.length || 0} ${
                  dossier.sources?.length === 1 ? "excerpt" : "excerpts"
                })`
              )
            )
        ),
        React.createElement(
          "div",
          { className: "dossier-header-actions" },
          React.createElement(
            "div",
            { className: "dossier-view-toggle", role: "tablist", "aria-label": "Dossier format toggle" },
            React.createElement(
              "button",
              {
                type: "button",
                role: "tab",
                "aria-selected": viewMode === "preview",
                className: `dossier-toggle-btn ${viewMode === "preview" ? "is-active" : ""}`,
                onClick: () => setViewMode("preview"),
              },
              "Executive Preview"
            ),
            React.createElement(
              "button",
              {
                type: "button",
                role: "tab",
                "aria-selected": viewMode === "markdown",
                className: `dossier-toggle-btn ${viewMode === "markdown" ? "is-active" : ""}`,
                onClick: () => setViewMode("markdown"),
              },
              "Markdown Source"
            )
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "dossier-action-btn copy-btn",
              onClick: handleCopyMarkdown,
              disabled: !dossier,
              title: "Copy Markdown report to clipboard",
            },
            copied ? "✓ Copied" : "Copy Markdown"
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "dossier-action-btn download-btn",
              onClick: handleDownloadMarkdown,
              disabled: !dossier,
              title: "Download formatted Markdown (.md)",
            },
            "↓ Download .md"
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "dossier-action-btn pdf-btn",
              onClick: handleExportPDF,
              disabled: !dossier,
              title: "Export executive PDF briefing",
            },
            "⎙ Export PDF"
          ),
          React.createElement(
            "button",
            {
              type: "button",
              className: "dossier-close-btn",
              onClick: onClose,
              "aria-label": "Close dossier",
            },
            "✕"
          )
        )
      ),
      React.createElement(
        "div",
        { className: "dossier-body" },
        loading &&
          React.createElement(
            "div",
            { className: "dossier-loading-state", role: "status" },
            React.createElement("div", { className: "state-spinner", "aria-hidden": "true" }),
            React.createElement("h3", null, "Synthesizing Executive Briefing…"),
            React.createElement("p", null, "Autonomous research plan in progress:"),
            React.createElement(
              "ul",
              { className: "dossier-research-stages" },
              React.createElement("li", { className: "stage-item is-done" }, "✓ Identifying entity aliases & canonical resolution"),
              React.createElement("li", { className: "stage-item is-active" }, "◉ Gathering biographical & tenure evidence"),
              React.createElement("li", { className: "stage-item is-active" }, "◉ Correlating network relationships & reporting lines"),
              React.createElement("li", { className: "stage-item is-active" }, "◉ Extracting project milestones & deliverables"),
              React.createElement("li", { className: "stage-item is-active" }, "◉ Attributing direct statements & quotations"),
              React.createElement("li", { className: "stage-item is-active" }, "◉ Grounding all claims against verified excerpt IDs")
            )
          ),
        error &&
          !loading &&
          React.createElement(
            "div",
            { className: "dossier-error-state", role: "alert" },
            React.createElement("h3", null, "Dossier Generation Error"),
            React.createElement("p", null, error),
            React.createElement(
              "button",
              { type: "button", className: "btn-retry", onClick: onClose },
              "Close"
            )
          ),
        dossier &&
          !loading &&
          !error &&
          React.createElement(
            "div",
            { id: "dossier-print-container", className: "dossier-content-container" },
            viewMode === "markdown"
              ? React.createElement(
                  "div",
                  { className: "dossier-markdown-view" },
                  React.createElement(
                    "pre",
                    { className: "dossier-markdown-pre" },
                    React.createElement("code", null, dossier.markdown)
                  )
                )
              : React.createElement(
                  "div",
                  { className: "dossier-preview-view" },
                  React.createElement(
                    "section",
                    { className: "dossier-summary-card" },
                    React.createElement("span", { className: "eyebrow" }, "Executive Summary"),
                    React.createElement(
                      "p",
                      { className: "dossier-summary-text" },
                      renderInlineCitations(dossier.executive_summary)
                    )
                  ),
                  React.createElement(
                    "div",
                    { className: "dossier-sections-grid" },
                    dossier.sections?.map((section) =>
                      React.createElement(
                        "article",
                        { key: section.id, className: `dossier-section-card section-${section.id}` },
                        React.createElement(
                          "header",
                          { className: "dossier-section-header" },
                          React.createElement(
                            "span",
                            { className: "section-icon", "aria-hidden": "true" },
                            section.id === "biography"
                              ? "🏛"
                              : section.id === "relationships"
                              ? "👥"
                              : section.id === "projects"
                              ? "🚀"
                              : "💬"
                          ),
                          React.createElement("h3", { className: "section-title" }, section.title),
                          React.createElement(
                            "span",
                            { className: "section-cite-count" },
                            `${section.citations?.length || 0} ${
                              section.citations?.length === 1 ? "source" : "sources"
                            }`
                          )
                        ),
                        React.createElement(
                          "div",
                          { className: "section-content" },
                          section.content?.split("\n").map((line, idx) => {
                            const trimmed = line.trim();
                            if (trimmed.startsWith("- ")) {
                              return React.createElement(
                                "p",
                                { key: idx, className: "section-claim-item" },
                                React.createElement("span", { className: "claim-bullet", "aria-hidden": "true" }, "•"),
                                React.createElement("span", null, renderInlineCitations(trimmed.slice(2)))
                              );
                            }
                            return React.createElement(
                              "p",
                              { key: idx, className: "section-paragraph" },
                              renderInlineCitations(trimmed)
                            );
                          })
                        )
                      )
                    )
                  ),
                  React.createElement(
                    "section",
                    { className: "dossier-sources-section" },
                    React.createElement(
                      "div",
                      { className: "sources-header" },
                      React.createElement(
                        "h4",
                        { className: "sources-title" },
                        "Verified Document Sources & Provenance"
                      ),
                      React.createElement(
                        "span",
                        { className: "sources-count" },
                        `${dossier.sources?.length || 0} Excerpts`
                      )
                    ),
                    React.createElement(
                      "div",
                      { className: "sources-table" },
                      dossier.sources?.map((src) =>
                        React.createElement(
                          "div",
                          { key: src.index, className: "source-row" },
                          React.createElement(
                            "div",
                            { className: "source-row-meta" },
                            React.createElement("span", { className: "source-index-badge" }, `[${src.index}]`),
                            React.createElement("strong", { className: "source-filename" }, src.filename),
                            src.page && React.createElement("span", { className: "source-page" }, `Page ${src.page}`),
                            React.createElement(
                              "span",
                              { className: "source-excerpt-id" },
                              `Excerpt ID: #${src.id}`
                            ),
                            onSelectCitation &&
                              React.createElement(
                                "button",
                                {
                                  type: "button",
                                  className: "source-view-btn",
                                  onClick: () => handleCitationClick(src.index),
                                  title: "Open excerpt in visual citation viewer",
                                },
                                "View Excerpt ↗"
                              )
                          ),
                          React.createElement(
                            "blockquote",
                            { className: "source-quote-text" },
                            `“${src.excerpt}”`
                          )
                        )
                      )
                    )
                  )
                )
          )
      )
    )
  );
}
