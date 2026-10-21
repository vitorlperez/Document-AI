/**
 * Único ponto de acesso à API de Espaços (ADR-0021). Sem dependências de React/Next para ser testável em node:
 * o transporte (fetch + credenciais + erro tipado) é injetado por `spaces-client.ts`.
 * Contratos "reais" (já no backend): /organizations/{id}/spaces… (T-C1), `spaces` em /workspace-folders (T-C2),
 * `space_ids` em /library/question-contexts e nas perguntas (T-C3).
 * Contratos "do plano" (outras faixas ainda implementando): `spaces`/`space_ids` na biblioteca (T-E1),
 * `spaces` nas citações (T-E2), `reach` nas chaves de API (T-I2), `space_ids` no convite (T-F7) e na ligação de pasta (T-F6b).
 */
import type { SpaceRef } from "../spaces-model";

export type SpaceRole = "member" | "manager";
export type SpaceSummary = { id: string; name: string; description: string | null; is_default: boolean; member_count: number; folder_count: number; my_role: SpaceRole | null };
export type SpaceMemberRow = { user_id: string; email: string; role: SpaceRole };
/** Pasta da biblioteca na árvore do editor de Espaço (só nome e estrutura; GET /spaces/folder-tree/…). */
export type TreeFolder = { id: string; name: string; has_children: boolean; source_id: string };
/** Pasta (qualquer profundidade) concedida ao Espaço. `ancestor_ids` = pai … raiz da conexão, para o estado indeterminado.
 *  `node_id: null` = grant órfão (a pasta saiu do catálogo): não concede nada agora e só se desfaz pelo `grant_id`. */
export type NodeGrant = { grant_id: string; orphan?: boolean; node_id: string | null; source_id: string; name: string; path: string | null; ancestor_ids: string[] };
export type SpaceImpact = { documents_lost: number; conversations_hidden: number; automations_paused: number; followed_queries_cleared?: number };
/** Pasta conectada como a organização a vê (GET /workspace-folders). Para admin, `readable:false` = só metadados operacionais. */
export type SpaceFolder = { id: string; name: string; status: string; spaces: SpaceRef[]; readable?: boolean; source_id?: string; source_provider?: string | null; source_account?: string | null; selection_kind?: string };
/** Candidato a membro: usuário da organização (GET /organizations/{id}/people — só `user_id` e e-mail; owner, admin ou responsável de algum Espaço). */
export type OrgPerson = { user_id: string | null; email: string };
/** Alcance de uma chave de API para quem a cria (T-I2: `reach` em POST/GET /api-keys). */
/** O backend devolve `{id, name}`; nomes soltos continuam aceitos. */
export type KeyReach = { spaces: (string | { id?: string; name: string })[]; documents: number };

export type SpacesErrorCode = "not_found" | "forbidden" | "conflict" | "invalid" | "unknown";
export class SpacesError extends Error {
  readonly code: SpacesErrorCode;
  readonly status?: number;
  constructor(code: SpacesErrorCode, message: string, status?: number) { super(message); this.code = code; this.status = status; }
}
const MESSAGES: Record<SpacesErrorCode, string> = {
  not_found: "Este Espaço não está mais disponível para você.",
  forbidden: "Você não tem permissão para esta ação.",
  conflict: "Já existe um Espaço com esse nome.",
  invalid: "Os dados informados não são válidos.",
  unknown: "Não foi possível concluir esta ação.",
};
export function toSpacesError(error: unknown): SpacesError {
  if (error instanceof SpacesError) return error;
  const status = typeof (error as { status?: unknown } | null)?.status === "number" ? (error as { status: number }).status : undefined;
  const code: SpacesErrorCode = status === 404 ? "not_found" : status === 403 ? "forbidden" : status === 409 ? "conflict" : status === 422 ? "invalid" : "unknown";
  return new SpacesError(code, MESSAGES[code], status);
}

export type Transport = <T>(path: string, init?: { method?: string; body?: string }) => Promise<T>;

const root = (org: string) => `/organizations/${org}/spaces`;
const json = (method: string, body?: unknown) => ({ method, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });

export function createSpacesApi(transport: Transport) {
  const call = async <T>(path: string, init?: { method?: string; body?: string }) => {
    try { return await transport<T>(path, init); } catch (error) { throw toSpacesError(error); }
  };
  return {
    listSpaces: (org: string) => call<SpaceSummary[]>(root(org)),
    createSpace: (org: string, input: { name: string; description?: string | null; is_default?: boolean }) => call<SpaceSummary>(root(org), json("POST", input)),
    renameSpace: (org: string, id: string, input: { name: string; description?: string | null }) => call<SpaceSummary>(`${root(org)}/${id}`, json("PATCH", input)),
    archiveSpace: (org: string, id: string) => call<void>(`${root(org)}/${id}`, json("DELETE")),
    members: (org: string, id: string) => call<SpaceMemberRow[]>(`${root(org)}/${id}/members`),
    addMember: (org: string, id: string, userId: string, role: SpaceRole = "member") => call<{ user_id: string; role: SpaceRole }>(`${root(org)}/${id}/members`, json("POST", { user_id: userId, role })),
    setRole: (org: string, id: string, userId: string, role: SpaceRole) => call<{ user_id: string; role: SpaceRole }>(`${root(org)}/${id}/members/${userId}`, json("PATCH", { role })),
    removeMember: (org: string, id: string, userId: string) => call<void>(`${root(org)}/${id}/members/${userId}`, json("DELETE")),
    impact: (org: string, id: string, userId: string) => call<SpaceImpact>(`${root(org)}/${id}/members/${userId}/impact`),
    grant: (org: string, id: string, folderId: string, disclosure: Record<string, unknown> = { text_version: DISCLOSURE_VERSION }) => call<{ space_id: string; workspace_folder_id: string }>(`${root(org)}/${id}/folders/${folderId}`, json("POST", { disclosure })),
    revoke: (org: string, id: string, folderId: string) => call<void>(`${root(org)}/${id}/folders/${folderId}`, json("DELETE")),
    /** Aplica o diff de pastas (sincronizações inteiras e pastas da biblioteca) numa transação só. Idempotente; só owner/admin da organização. */
    changeFolders: (org: string, id: string, input: { grant: string[]; revoke: string[]; grant_nodes?: string[]; revoke_nodes?: string[]; revoke_node_grants?: string[] }) => call<{ granted: string[]; revoked: string[]; granted_nodes?: string[]; revoked_nodes?: string[]; revoked_node_grants?: string[] }>(`${root(org)}/${id}/folders`, json("PUT", { ...input, ...(input.grant.length || input.grant_nodes?.length ? { disclosure: { text_version: DISCLOSURE_VERSION } } : {}) })),
    /** Pastas da biblioteca concedidas ao Espaço (membros e administradores). */
    nodeGrants: (org: string, id: string) => call<NodeGrant[]>(`${root(org)}/${id}/node-grants`),
    /** Administradores: as pastas de onde cada sincronização foi montada (por id da sincronização) e as subpastas de qualquer pasta. */
    folderRoots: (org: string) => call<Record<string, TreeFolder[]>>(`${root(org)}/folder-tree/roots`),
    folderChildren: async (org: string, nodeId: string) => (await call<{ items: TreeFolder[] }>(`${root(org)}/folder-tree/nodes/${nodeId}/children`)).items,
    enter: (org: string, id: string) => call<{ space_id: string; role: SpaceRole }>(`${root(org)}/${id}/enter`, json("POST")),
    folders: (org: string) => call<SpaceFolder[]>(`/workspace-folders?organization_id=${org}`),
    orgPeople: async (org: string): Promise<OrgPerson[]> => {
      const rows = await call<{ user_id?: string | null; email: string }[]>(`/organizations/${org}/people`);
      return rows.map((row) => ({ user_id: row.user_id ?? null, email: row.email }));
    },
  };
}
export type SpacesApi = ReturnType<typeof createSpacesApi>;

/** Versão do texto de ciência exibido ao ligar uma pasta (gravada na concessão como `disclosure`). */
export const DISCLOSURE_VERSION = "2026-10";
export const DISCLOSURE_TEXT = "Todas as pessoas desses Espaços poderão ver o conteúdo desta pasta, e as respostas do assistente poderão citá-lo. Você pode mudar isso depois.";

/** Texto da prévia de alcance de uma chave de API (T-F8). `reach` ausente (backend antigo) ⇒ null: não afirma nada. */
export function reachSentence(reach: KeyReach | null | undefined): string | null {
  if (!reach) return null;
  if (reach.spaces.length === 0) return "Esta chave não lerá nenhum documento: quem a criou não participa de nenhum Espaço.";
  const docs = `${reach.documents.toLocaleString("pt-BR")} ${reach.documents === 1 ? "documento" : "documentos"}`;
  return `Esta chave alcançará ${docs} em: ${reach.spaces.map((space) => typeof space === "string" ? space : space.name).join(", ")}.`;
}
/** Aviso para quem cria a chave sendo admin sem nenhum Espaço (o admin não lê conteúdo por ser admin — D-2). */
export const adminWithoutSpacesWarning = (orgRole: "owner" | "admin" | "member", mySpaceCount: number | null) =>
  orgRole !== "member" && mySpaceCount === 0 ? "Você é administrador mas não participa de nenhum Espaço: uma chave criada agora não lerá nenhum documento. Entre em um Espaço antes de criá-la." : null;

/** Quem lê o nome de pessoas para o botão "Entrar neste Espaço": admin da organização que ainda não é membro. */
export const canEnterSpace = (orgRole: "owner" | "admin" | "member", space: Pick<SpaceSummary, "my_role">) => orgRole !== "member" && space.my_role === null;

/** Pessoas que ainda não estão no Espaço, filtradas por texto (acentos/maiúsculas ignorados). Só quem tem `user_id` pode ser adicionado. */
export function addableCandidates(people: OrgPerson[], members: Pick<SpaceMemberRow, "user_id">[], term: string): OrgPerson[] {
  const taken = new Set(members.map((member) => member.user_id));
  const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const needle = fold(term.trim());
  return people.filter((person) => person.user_id && !taken.has(person.user_id) && (!needle || fold(person.email).includes(needle)));
}
const foldText = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();

/**
 * Lista única da aba Pessoas: quem está no Espaço (papel; responsáveis primeiro, depois por e-mail) e as demais pessoas da
 * organização (convidados sem `user_id` por último). `term` só filtra (e-mail, sem acento/caixa); não decide quem entra.
 */
export function partitionPeople<M extends Pick<SpaceMemberRow, "user_id" | "email">>(people: OrgPerson[], members: M[], term: string): { inSpace: M[]; others: OrgPerson[]; totalInSpace: number; totalOthers: number } {
  const taken = new Set(members.map((member) => member.user_id));
  const needle = foldText(term.trim());
  const match = (email: string) => !needle || foldText(email).includes(needle);
  const byEmail = (a: { email: string }, b: { email: string }) => a.email.localeCompare(b.email, "pt-BR", { sensitivity: "base" });
  const isManager = (member: M) => (member as unknown as { role?: SpaceRole }).role === "manager";
  const sortedMembers = [...members].sort((a, b) => Number(isManager(b)) - Number(isManager(a)) || byEmail(a, b));
  const rest = people.filter((person) => !person.user_id || !taken.has(person.user_id));
  const sortedOthers = [...rest].sort((a, b) => Number(!a.user_id) - Number(!b.user_id) || byEmail(a, b));
  return {
    inSpace: sortedMembers.filter((member) => match(member.email)),
    others: sortedOthers.filter((person) => match(person.email)),
    totalInSpace: members.length,
    totalOthers: rest.length,
  };
}
export const spaceRoleLabel = (role: SpaceRole | null) => role === "manager" ? "Responsável" : role === "member" ? "Membro" : "Sem acesso";

/** Espaços de que a pessoa participa — os únicos que podem filtrar leitura. Admin que não entrou num Espaço o gerencia, mas filtrar por ele daria 404. */
export const memberSpaces = (spaces: Pick<SpaceSummary, "id" | "name" | "my_role">[]): SpaceRef[] =>
  spaces.filter((space) => space.my_role !== null).map((space) => ({ id: space.id, name: space.name }));

/** Dica antes de criar a chave (a contagem de documentos só vem do servidor, depois da criação): a chave lê o que o criador lê. */
export const creatorReachHint = (spaceNames: string[]): string | null =>
  spaceNames.length ? `Esta chave lerá apenas o que está nos seus Espaços: ${spaceNames.join(", ")}.` : null;
