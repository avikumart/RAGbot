import { proxyPersonagraph } from "../../personagraph-proxy";

type RouteContext = { params: Promise<{ sessionId: string }> };

function endpoint(sessionId: string) {
  return `/api/sessions/${encodeURIComponent(sessionId)}`;
}

export async function GET(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).sessionId));
}

export async function PATCH(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).sessionId));
}

export async function DELETE(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).sessionId));
}
