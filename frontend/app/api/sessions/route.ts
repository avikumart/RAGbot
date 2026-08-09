import { proxyPersonagraph } from "../personagraph-proxy";

export async function GET(request: Request) {
  return proxyPersonagraph(request, "/api/sessions" + new URL(request.url).search);
}

export async function POST(request: Request) {
  return proxyPersonagraph(request, "/api/sessions");
}
