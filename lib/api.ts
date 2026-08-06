export const API_ERROR_MESSAGE = "Something went wrong. Please try again.";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type DocumentRecord = {
  id: string;
  filename: string;
  content_type: string;
  size_bytes: number;
  uploaded_at: string;
  chunk_count: number;
  people: string[];
  index_status: string;
  index_error: string | null;
  index_updated_at: string | null;
};

export type PersonRecord = {
  normalized: string;
  name: string;
  mentions: number;
  document_count: number;
};

export type Source = {
  index: number;
  document_id: string;
  filename: string;
  page: number | null;
  excerpt: string;
  score: number;
};

export type ChatRequest = {
  message: string;
  document_ids?: string[];
  person?: string;
};

export type ChatResponse = {
  answer: string;
  sources: Source[];
  mode: string;
};

function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail.trim() || null;

  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item.trim();
        if (!item || typeof item !== "object") return "";

        const message = "msg" in item ? item.msg : "message" in item ? item.message : null;
        return typeof message === "string" ? message.trim() : "";
      })
      .filter(Boolean);
    return messages.length ? messages.join(" ") : null;
  }

  if (detail && typeof detail === "object" && "message" in detail) {
    const message = detail.message;
    return typeof message === "string" ? message.trim() || null : null;
  }

  return null;
}

export async function parseApiError(response: Response): Promise<string> {
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return API_ERROR_MESSAGE;
  }

  if (!payload || typeof payload !== "object") return API_ERROR_MESSAGE;

  const detail = "detail" in payload ? detailMessage(payload.detail) : null;
  if (detail) return detail;

  const message = "message" in payload ? detailMessage(payload.message) : null;
  return message ?? API_ERROR_MESSAGE;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, options);
  if (!response.ok) throw new Error(await parseApiError(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
