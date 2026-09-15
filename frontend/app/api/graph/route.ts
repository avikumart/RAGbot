import { proxyPersonagraph } from "../personagraph-proxy";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const search = url.search;
  return proxyPersonagraph(request, `/api/graph${search}`);
}
