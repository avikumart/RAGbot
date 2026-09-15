"use client";

export type QueueItemStatus = "queued" | "uploading" | "indexing" | "ready" | "error";

export type QueueItem = {
  id: string;
  file: File;
  name: string;
  size: number;
  status: QueueItemStatus;
  error?: string | null;
  progress?: number;
  documentId?: string | null;
};

export { UploadQueue } from "./upload-queue.mjs";
