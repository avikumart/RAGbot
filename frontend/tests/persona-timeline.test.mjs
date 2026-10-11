import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { PersonaTimeline } from "../components/persona-timeline.mjs";

test("PersonaTimeline renders loading state when loading is true", () => {
  const html = renderToStaticMarkup(
    React.createElement(PersonaTimeline, {
      personName: "Maya Patel",
      events: null,
      loading: true,
    })
  );
  assert.match(html, /is-loading/);
  assert.match(html, /Extracting chronological milestones…/);
});

test("PersonaTimeline renders prompt when no person is selected", () => {
  const html = renderToStaticMarkup(
    React.createElement(PersonaTimeline, {
      personName: null,
      events: null,
      loading: false,
    })
  );
  assert.match(html, /Select a Subject/);
  assert.match(html, /Choose a subject from the library/);
});

test("PersonaTimeline renders empty state when events list is empty", () => {
  const html = renderToStaticMarkup(
    React.createElement(PersonaTimeline, {
      personName: "Maya Patel",
      events: [],
      loading: false,
    })
  );
  assert.match(html, /No Milestones Extracted/);
  assert.match(html, /Maya Patel/);
});

test("PersonaTimeline renders milestone events with date markers, descriptions, and citation trigger", () => {
  const events = [
    {
      id: "ev-1",
      document_id: "doc-1",
      filename: "stanford-records.pdf",
      entity_name: "Maya Patel",
      event_text: "Graduated from Stanford University with a Ph.D. in Computer Science.",
      event_date: "2018",
      chunk_id: 10,
      page: 3,
      chunk_content: "Maya Patel graduated in 2018...",
    },
    {
      id: "ev-2",
      document_id: "doc-1",
      filename: "stanford-records.pdf",
      entity_name: "Maya Patel",
      event_text: "Appointed as Principal AI Architect at Acme Corp.",
      event_date: "September 2020",
      chunk_id: 14,
      page: 5,
      chunk_content: "In September 2020...",
    },
  ];

  const html = renderToStaticMarkup(
    React.createElement(PersonaTimeline, {
      personName: "Maya Patel",
      events,
      loading: false,
      onSelectCitation: () => {},
    })
  );

  assert.match(html, /2 milestones/);
  assert.match(html, />2018<\/span>/);
  assert.match(html, /Graduated from Stanford University/);
  assert.match(html, />September 2020<\/span>/);
  assert.match(html, /Appointed as Principal AI Architect/);
  assert.match(html, /stanford-records\.pdf/);
  assert.match(html, /p\. 3/);
  assert.match(html, /p\. 5/);
  assert.match(html, /Jump to citation ↗/);
  assert.match(html, /data-testid="timeline-citation-jump"/);
});
