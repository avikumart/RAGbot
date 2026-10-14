import { proxyPersonagraph } from "../../../personagraph-proxy";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ name: string }> | { name: string } }
) {
  const resolvedParams = await params;
  const url = new URL(request.url);
  const search = url.search;
  return proxyPersonagraph(
    request,
    `/api/people/${encodeURIComponent(resolvedParams.name)}/dossier${search}`
  );
}
