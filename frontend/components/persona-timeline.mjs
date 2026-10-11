import React, { useState, useMemo } from "react";

export function PersonaTimeline({
  personName,
  events,
  loading = false,
  onSelectCitation,
  onSelectPerson,
}) {
  const [filterQuery, setFilterQuery] = useState("");
  const [sortOrder, setSortOrder] = useState("asc");

  const filteredEvents = useMemo(() => {
    if (!events) return [];
    let result = [...events];
    if (filterQuery.trim()) {
      const q = filterQuery.toLowerCase();
      result = result.filter(
        (ev) =>
          ev.event_text.toLowerCase().includes(q) ||
          ev.event_date.toLowerCase().includes(q) ||
          ev.entity_name.toLowerCase().includes(q) ||
          ev.filename.toLowerCase().includes(q)
      );
    }
    if (sortOrder === "desc") {
      result.reverse();
    }
    return result;
  }, [events, filterQuery, sortOrder]);

  if (loading) {
    return React.createElement(
      "div",
      { className: "persona-timeline-container is-loading", role: "status", "aria-label": "Loading timeline" },
      React.createElement("span", { className: "state-spinner", "aria-hidden": "true" }),
      React.createElement("p", { className: "timeline-loading-text" }, "Extracting chronological milestones…")
    );
  }

  if (!personName) {
    return React.createElement(
      "div",
      { className: "persona-timeline-container is-empty" },
      React.createElement("div", { className: "timeline-empty-icon", "aria-hidden": "true" }, "⏱"),
      React.createElement("h4", { className: "timeline-empty-title" }, "Select a Subject"),
      React.createElement(
        "p",
        { className: "timeline-empty-sub" },
        "Choose a subject from the library to view their chronological milestone narrative and historical timeline."
      )
    );
  }

  if (!events || events.length === 0) {
    return React.createElement(
      "div",
      { className: "persona-timeline-container is-empty" },
      React.createElement("div", { className: "timeline-empty-icon", "aria-hidden": "true" }, "◇"),
      React.createElement("h4", { className: "timeline-empty-title" }, "No Milestones Extracted"),
      React.createElement(
        "p",
        { className: "timeline-empty-sub" },
        "No dated milestones or temporal events were identified for ",
        React.createElement("strong", null, personName),
        " in the currently indexed passages."
      )
    );
  }

  return React.createElement(
    "div",
    { className: "persona-timeline-container" },
    React.createElement(
      "div",
      { className: "timeline-toolbar" },
      React.createElement(
        "div",
        { className: "timeline-toolbar-info" },
        React.createElement("span", { className: "timeline-subject-badge", title: personName }, personName),
        React.createElement(
          "span",
          { className: "timeline-count-badge" },
          `${filteredEvents.length} ${filteredEvents.length === 1 ? "milestone" : "milestones"}`
        )
      ),
      React.createElement(
        "div",
        { className: "timeline-controls" },
        React.createElement(
          "button",
          {
            type: "button",
            className: "timeline-sort-btn",
            onClick: () => setSortOrder((current) => (current === "asc" ? "desc" : "asc")),
            title: sortOrder === "asc" ? "Sort newest first" : "Sort oldest first",
            "aria-label": "Toggle chronological order",
          },
          sortOrder === "asc" ? "Oldest first ↑" : "Newest first ↓"
        )
      )
    ),
    React.createElement(
      "div",
      { className: "timeline-search-row" },
      React.createElement("input", {
        type: "search",
        className: "timeline-search-input",
        placeholder: "Filter milestones or dates…",
        value: filterQuery,
        onChange: (e) => setFilterQuery(e.target.value),
        "aria-label": "Filter timeline events",
      })
    ),
    React.createElement(
      "div",
      { className: "timeline-scroll-area" },
      React.createElement(
        "div",
        { className: "timeline-track", role: "feed", "aria-label": `Timeline for ${personName}` },
        filteredEvents.map((ev, index) => {
          const hasChunk = ev.chunk_id !== null;
          return React.createElement(
            "article",
            { key: ev.id || `${ev.event_date}-${index}`, className: "timeline-item" },
            React.createElement(
              "div",
              { className: "timeline-marker-col", "aria-hidden": "true" },
              React.createElement("div", { className: "timeline-marker-dot" }),
              React.createElement("div", { className: "timeline-marker-line" })
            ),
            React.createElement(
              "div",
              { className: "timeline-content-card" },
              React.createElement(
                "div",
                { className: "timeline-card-header" },
                React.createElement("span", { className: "timeline-date-chip" }, ev.event_date),
                ev.entity_name.toLowerCase() !== personName.toLowerCase()
                  ? React.createElement(
                      "button",
                      {
                        type: "button",
                        className: "timeline-entity-chip",
                        onClick: () => onSelectPerson?.(ev.entity_name),
                        title: `Focus on ${ev.entity_name}`,
                      },
                      ev.entity_name
                    )
                  : null
              ),
              React.createElement("p", { className: "timeline-event-description" }, ev.event_text),
              React.createElement(
                "div",
                { className: "timeline-card-footer" },
                React.createElement(
                  "span",
                  { className: "timeline-doc-tag", title: ev.filename },
                  `📄 ${ev.filename}${ev.page ? ` · p. ${ev.page}` : ""}`
                ),
                hasChunk && onSelectCitation
                  ? React.createElement(
                      "button",
                      {
                        type: "button",
                        className: "timeline-citation-trigger",
                        "data-testid": "timeline-citation-jump",
                        onClick: () =>
                          onSelectCitation({
                            index: index + 1,
                            document_id: ev.document_id,
                            filename: ev.filename,
                            page: ev.page,
                            excerpt: ev.chunk_content || ev.event_text,
                            score: 1.0,
                          }),
                        title: "Jump to source citation in reader",
                        "aria-label": `Jump to citation in ${ev.filename}`,
                      },
                      "Jump to citation ↗"
                    )
                  : null
              )
            )
          );
        })
      )
    )
  );
}
