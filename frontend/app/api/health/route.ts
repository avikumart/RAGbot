import { proxyPersonagraph } from "../personagraph-proxy";

export async function GET(request: Request) {
  return proxyPersonagraph(request, "/api/health");
}
