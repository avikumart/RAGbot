import { proxyPersonagraph } from "../personagraph-proxy";

export async function GET(request: Request) {
  return proxyPersonagraph(request, "/api/documents");
}

export async function POST(request: Request) {
  return proxyPersonagraph(request, "/api/documents");
}
