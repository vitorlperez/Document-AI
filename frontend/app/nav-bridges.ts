/** Pontes Conversa ↔ Biblioteca: o estado vive na URL (sobrevive a reload) e só carrega ids; nomes e permissões vêm do backend. */
const ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const id = (value: string | null | undefined): string | null => value && ID.test(value.trim()) ? value.trim() : null;
const spacesParam = (spaceIds: readonly string[]) => [...new Set(spaceIds.filter((item) => ID.test(item)))].join(",");

const withQuery = (path: string, entries: [string, string | null | undefined][]) => {
  const query = new URLSearchParams();
  for (const [key, value] of entries) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `${path}?${text}` : path;
};

/** Biblioteca → Conversa: abre o chat com o arquivo/pasta já mencionado (`?mention=`) e o filtro de Espaços da biblioteca (`?spaces=`). */
export const chatMentionPath = (companyId: string, nodeId: string, spaceIds: readonly string[] = []): string =>
  withQuery(`/companies/${companyId}`, [["mention", id(nodeId)], ["spaces", spacesParam(spaceIds)]]);

export type ChatBridge = { mentionNodeIds: string[]; spaceIds: string[] };
/** Lê o estado de ponte da query do chat; ids inválidos são descartados (nunca chegam ao backend). */
export function parseChatBridge(search: string): ChatBridge {
  const query = new URLSearchParams(search.startsWith("?") ? search : `?${search}`);
  const valid = (raw: string) => [...new Set(raw.split(",").map((item) => id(item)).filter((item): item is string => item !== null))];
  return { mentionNodeIds: valid(query.getAll("mention").join(",")), spaceIds: valid(query.get("spaces") ?? "") };
}

/** Remove os parâmetros de ponte já aplicados, preservando o resto da query. */
export function withoutChatBridge(search: string): string {
  const query = new URLSearchParams(search.startsWith("?") ? search : `?${search}`);
  query.delete("mention");
  const text = query.toString();
  return text ? `?${text}` : "";
}

export type LibraryTarget = { nodeId?: string | null; documentId?: string | null };
/** Conversa → Biblioteca: `?focus=<nó>` ou `?focusDoc=<documento citado>`; o backend resolve pasta e permissão. */
export function libraryFocusPath(companyId: string, target: LibraryTarget, spaceIds: readonly string[] = []): string | null {
  const node = id(target.nodeId); const document = id(target.documentId);
  if (!node && !document) return null;
  return withQuery(`/companies/${companyId}/library`, [["focus", node], ["focusDoc", node ? null : document], ["spaces", spacesParam(spaceIds)]]);
}

export type LibraryFocus = { nodeId: string | null; documentId: string | null };
export function parseLibraryFocus(search: string): LibraryFocus | null {
  const query = new URLSearchParams(search.startsWith("?") ? search : `?${search}`);
  const nodeId = id(query.get("focus")); const documentId = nodeId ? null : id(query.get("focusDoc"));
  return nodeId || documentId ? { nodeId, documentId } : null;
}

/** Query do `/library/locate` para o foco (os Espaços entram como `space_ids`, como nos demais endpoints). */
export function locateQuery(organizationId: string, focus: LibraryFocus, spaceIds: readonly string[] = []): string {
  const query = new URLSearchParams({ organization_id: organizationId });
  if (focus.nodeId) query.set("node_id", focus.nodeId); else if (focus.documentId) query.set("document_id", focus.documentId);
  for (const space of new Set(spaceIds.filter((item) => ID.test(item)))) query.append("space_ids", space);
  return query.toString();
}

export const UNAVAILABLE_ITEM_MESSAGE = "Este item não está disponível para você.";
