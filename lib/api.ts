export const API_ERROR_MESSAGE = "Something went wrong. Please try again.";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
// Session and chat traffic must stay same-origin so the server-side proxy can
// derive and sign the authenticated owner. Document-library traffic remains on
// the configured FastAPI URL for the existing local deployment shape.
const AUTHENTICATED_API_URL = "";

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
  session_id?: string;
  client_message_id: string;
};

export type ChatMessage = {
  id: string;
  ordinal: number;
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  mode: string | null;
  retrieval_mode: string | null;
  created_at: string;
};

export type ChatSession = {
  id: string;
  topic: string;
  document_ids: string[];
  person: string | null;
  created_at: string;
  updated_at: string;
  messages?: ChatMessage[];
};

export type ChatResponse = {
  answer: string;
  sources: Source[];
  mode: string;
  retrieval_mode: string;
  session_id: string;
  topic: string;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
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
  const authenticated = path === "/api/chat" || path.startsWith("/api/sessions");
  const baseUrl = authenticated ? AUTHENTICATED_API_URL : API_URL;
  const response = await fetch(`${baseUrl}${path}`, options);
  if (!response.ok) throw new Error(await parseApiError(response));
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}
