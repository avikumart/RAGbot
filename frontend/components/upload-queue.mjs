import React from "react";

function humanSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function documentKind(filename) {
  return filename.split(".").pop()?.toUpperCase() || "DOC";
}

export function UploadQueue({ items = [], onRetry = () => {}, onClear = () => {} }) {
  if (!items.length) return null;

  const completedCount = items.filter((i) => i.status === "ready").length;
  const errorCount = items.filter((i) => i.status === "error").length;
  const isBusy = items.some((i) => i.status === "uploading" || i.status === "indexing" || i.status === "queued");

  return React.createElement(
    "section",
    { className: "upload-queue", "aria-label": "Upload queue", role: "region" },
    React.createElement(
      "div",
      { className: "upload-queue-header" },
      React.createElement(
        "div",
        { className: "upload-queue-title-row" },
        React.createElement("strong", null, "Upload queue"),
        React.createElement(
          "span",
          { className: "upload-queue-count" },
          isBusy
            ? `${completedCount} of ${items.length} completed`
            : errorCount > 0
              ? `${errorCount} failed, ${completedCount} ready`
              : `${completedCount} uploaded`
        )
      ),
      !isBusy &&
        React.createElement(
          "button",
          {
            type: "button",
            className: "upload-queue-clear",
            onClick: onClear,
            "aria-label": "Clear upload queue",
          },
          "Clear"
        )
    ),
    React.createElement(
      "div",
      { className: "upload-queue-list", role: "list" },
      items.map((item) =>
        React.createElement(
          "div",
          {
            className: `upload-queue-item is-${item.status}`,
            key: item.id,
            role: "listitem",
          },
          React.createElement(
            "span",
            { className: "file-badge upload-queue-badge" },
            documentKind(item.name)
          ),
          React.createElement(
            "div",
            { className: "upload-queue-file-info" },
            React.createElement(
              "span",
              { className: "upload-queue-filename", title: item.name },
              item.name
            ),
            React.createElement(
              "span",
              { className: "upload-queue-size" },
              humanSize(item.size)
            ),
            item.error &&
              React.createElement(
                "span",
                { className: "upload-queue-error-detail", title: item.error },
                item.error
              )
          ),
          React.createElement(
            "div",
            { className: "upload-queue-status-col" },
            item.status === "queued" &&
              React.createElement(
                "span",
                { className: "upload-queue-status is-queued" },
                "Queued"
              ),
            item.status === "uploading" &&
              React.createElement(
                "span",
                { className: "upload-queue-status is-uploading" },
                React.createElement("span", { className: "state-spinner", "aria-hidden": "true" }),
                "Uploading…"
              ),
            item.status === "indexing" &&
              React.createElement(
                "span",
                { className: "upload-queue-status is-indexing" },
                React.createElement("span", { className: "state-spinner", "aria-hidden": "true" }),
                "Indexing…"
              ),
            item.status === "ready" &&
              React.createElement(
                "span",
                { className: "upload-queue-status is-ready", "aria-label": "Upload complete" },
                "✓ Ready"
              ),
            item.status === "error" &&
              React.createElement(
                "div",
                { className: "upload-queue-error-actions" },
                React.createElement(
                  "span",
                  { className: "upload-queue-status is-error" },
                  "Failed"
                ),
                React.createElement(
                  "button",
                  {
                    type: "button",
                    className: "upload-queue-retry",
                    onClick: () => onRetry(item),
                    "aria-label": `Retry uploading ${item.name}`,
                  },
                  "Retry"
                )
              )
          )
        )
      )
    )
  );
}
