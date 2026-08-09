import { proxyPersonagraph } from "../personagraph-proxy";

export async function POST(request: Request) {
  return proxyPersonagraph(request, "/api/chat");
}
