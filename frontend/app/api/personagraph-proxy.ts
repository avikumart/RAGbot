import { headers } from "next/headers";

const AUTH_USER_ID_HEADER = "oai-authenticated-user-id";
const AUTH_EMAIL_HEADER = "oai-authenticated-user-email";
const API_URL = (
  process.env.PERSONAGRAPH_API_URL
  ?? process.env.NEXT_PUBLIC_API_URL
  ?? "http://localhost:8000"
).replace(/\/$/, "");

function hex(bytes: ArrayBuffer) {
  return [...new Uint8Array(bytes)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function digest(value: string) {
  return hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(value)));
}

async function sign(value: string, secret: string) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  return hex(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(value)));
}

/** Forward only owner-scoped chat APIs after deriving identity server-side. */
export async function proxyPersonagraph(request: Request, path: string) {
  const requestHeaders = await headers();
  // The authenticated user ID is stable for this Site; email is only a
  // backwards-compatible fallback for local/proxy environments that do not
  // provide it.
  const identity = requestHeaders.get(AUTH_USER_ID_HEADER)
    ?? requestHeaders.get(AUTH_EMAIL_HEADER)
    ?? process.env.LOCAL_DEVELOPMENT_OWNER
    ?? "local-development-user";
  const owner = await digest(`personagraph-owner:v1:${identity}`);
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const secret = process.env.AUTH_PROXY_SECRET ?? "";
  const forwardedHeaders = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) forwardedHeaders.set("content-type", contentType);
  const accept = request.headers.get("accept");
  if (accept) forwardedHeaders.set("accept", accept);
  if (secret) {
    forwardedHeaders.set("x-personagraph-owner", owner);
    forwardedHeaders.set("x-personagraph-owner-timestamp", timestamp);
    forwardedHeaders.set(
      "x-personagraph-owner-signature",
      await sign(`${owner}:${timestamp}`, secret),
    );
  }

  const body = request.method === "GET" || request.method === "DELETE"
    ? undefined
    : await request.arrayBuffer();
  const upstream = await fetch(`${API_URL}${path}`, {
    method: request.method,
    headers: forwardedHeaders,
    body,
  });
  const responseHeaders = new Headers();
  const upstreamContentType = upstream.headers.get("content-type");
  if (upstreamContentType) responseHeaders.set("content-type", upstreamContentType);
  const cacheControl = upstream.headers.get("cache-control");
  if (cacheControl) responseHeaders.set("cache-control", cacheControl);
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}
