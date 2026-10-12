import { proxyPersonagraph } from "../../../personagraph-proxy";

type RouteContext = { params: Promise<{ collectionId: string }> };

function endpoint(collectionId: string) {
  return `/api/collections/${encodeURIComponent(collectionId)}/documents`;
}

export async function POST(request: Request, { params }: RouteContext) {
  return proxyPersonagraph(request, endpoint((await params).collectionId));
}
