import { proxyPersonagraph } from "../../personagraph-proxy";

export async function DELETE(
  request: Request,
  props: { params: Promise<{ documentId: string }> },
) {
  const { documentId } = await props.params;
  return proxyPersonagraph(request, `/api/documents/${documentId}`);
}
