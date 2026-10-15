import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { PersonaDossierModal } from "../components/persona-dossier-modal.mjs";

test("PersonaDossierModal renders null when isOpen is false", () => {
  const html = renderToStaticMarkup(
    React.createElement(PersonaDossierModal, {
      isOpen: false,
      personName: "Maya Patel",
      dossier: null,
      loading: false,
      error: null,
      onClose: () => {},
    })
  );
  assert.equal(html, "");
});

test("PersonaDossierModal renders loading state with research stages", () => {
  const html = renderToStaticMarkup(
    React.createElement(PersonaDossierModal, {
      isOpen: true,
      personName: "Maya Patel",
      dossier: null,
      loading: true,
      error: null,
      onClose: () => {},
    })
  );
  assert.match(html, /Synthesizing Executive Briefing…/);
  assert.match(html, /Gathering biographical &amp; tenure evidence/);
  assert.match(html, /Grounding all claims against verified excerpt IDs/);
});

test("PersonaDossierModal renders error state", () => {
  const html = renderToStaticMarkup(
    React.createElement(PersonaDossierModal, {
      isOpen: true,
      personName: "Maya Patel",
      dossier: null,
      loading: false,
      error: "Document scope expired.",
      onClose: () => {},
    })
  );
  assert.match(html, /Dossier Generation Error/);
  assert.match(html, /Document scope expired\./);
});

test("PersonaDossierModal renders executive briefing with sections, citations, sources and export buttons", () => {
  const mockDossier = {
    entity_name: "Maya Patel",
    generated_at: "2026-10-14T00:00:00Z",
    scope: {
      document_ids: ["doc-1"],
      summary: "1 document",
    },
    executive_summary: "Principal AI Architect at Acme Corp [1] leading the Quantum Project [2].",
    sections: [
      {
        id: "biography",
        title: "Biography & Current Roles",
        content: "- Joined Acme Corp as Principal AI Architect in 2020 [1].",
        citations: [1],
        excerpt_ids: [101],
      },
      {
        id: "relationships",
        title: "Key Relationships & Network",
        content: "- Maya Patel collaborates with Jordan Lee [1].",
        citations: [1],
        excerpt_ids: [101],
      },
      {
        id: "projects",
        title: "Projects & Key Accomplishments",
        content: "- Launched the Quantum Project in 2023 [2].",
        citations: [2],
        excerpt_ids: [102],
      },
      {
        id: "quotes",
        title: "Direct Statements & Positions",
        content: "- \"Reliability must precede rollout\" [2].",
        citations: [2],
        excerpt_ids: [102],
      },
    ],
    sources: [
      {
        index: 1,
        id: 101,
        document_id: "doc-1",
        filename: "bio.pdf",
        page: 1,
        excerpt: "Maya joined Acme Corp as Principal AI Architect in 2020.",
        score: 1.0,
      },
      {
        index: 2,
        id: 102,
        document_id: "doc-1",
        filename: "quantum.pdf",
        page: 2,
        excerpt: "Launched the Quantum Project in 2023. Reliability must precede rollout.",
        score: 0.95,
      },
    ],
    markdown: "# Executive Briefing: Maya Patel\n\n## Executive Summary\n...",
  };

  const html = renderToStaticMarkup(
    React.createElement(PersonaDossierModal, {
      isOpen: true,
      personName: "Maya Patel",
      dossier: mockDossier,
      loading: false,
      error: null,
      onClose: () => {},
    })
  );

  // Title and provenance
  assert.match(html, /Executive Briefing: Maya Patel/);
  assert.match(html, /100% Grounded/);
  assert.match(html, /Scope: 1 document/);

  // Action buttons
  assert.match(html, /Copy Markdown/);
  assert.match(html, /Download \.md/);
  assert.match(html, /Export PDF/);

  // Sections
  assert.match(html, /Biography &amp; Current Roles/);
  assert.match(html, /Key Relationships &amp; Network/);
  assert.match(html, /Projects &amp; Key Accomplishments/);
  assert.match(html, /Direct Statements &amp; Positions/);

  // Inline citations and Excerpt IDs
  assert.match(html, /dossier-cite-btn/);
  assert.match(html, /Excerpt ID: #101/);
  assert.match(html, /Excerpt ID: #102/);
  assert.match(html, /bio\.pdf/);
  assert.match(html, /quantum\.pdf/);
});
