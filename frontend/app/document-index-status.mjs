import React from "react";

export function documentIndexStatus(status) {
  switch (status) {
    case "ready":
      return { label: "Ready", tone: "ready" };
    case "pending":
    case "indexing":
      return { label: "Indexing", tone: "indexing" };
    case "disabled":
      return { label: "Lexical only", tone: "lexical" };
    case "needs_reindex":
    default:
      // Unknown states must never imply that semantic indexing succeeded.
      return { label: "Needs repair", tone: "repair" };
  }
}

export function DocumentIndexStatus({ status }) {
  const presentation = documentIndexStatus(status);

  return React.createElement(
    "small",
    {
      className: `document-index-status is-${presentation.tone}`,
      "data-index-status": presentation.tone,
    },
    React.createElement("span", { "aria-hidden": "true" }),
    presentation.label,
  );
}
