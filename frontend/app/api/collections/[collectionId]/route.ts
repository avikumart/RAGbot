import { proxyPersonagraph } from "../../personagraph-proxy";

type RouteContext = { params: Promise<{ collectionId: string }> };

function endpoint(collectionId: string) {
  return `/api/collections/${encodeURIComponent(collectionId)}`;
}

export async function GET(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).collectionId));
}

export async function PATCH(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).collectionId));
}

export async function DELETE(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).collectionId));
}
