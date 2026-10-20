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
export type SpaceImpact = { documents_lost: number; conversations_hidden: number; automations_paused: number; followed_queries_cleared?: number };
/** Pasta conectada como a organização a vê (GET /workspace-folders). Para admin, `readable:false` = só metadados operacionais. */
export type SpaceFolder = { id: string; name: string; status: string; spaces: SpaceRef[]; readable?: boolean };
/** Candidato a membro: usuário da organização (GET /organizations/{id}/people — só `user_id` e e-mail; owner, admin ou responsável de algum Espaço). */
export type OrgPerson = { user_id: string | null; email: string };
/** Alcance de uma chave de API para quem a cria (T-I2: `reach` em POST/GET /api-keys). */
export type KeyReach = { spaces: string[]; documents: number };

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
    enter: (org: string, id: string) => call<{ space_id: string; role: SpaceRole }>(`${root(org)}/${id}/enter`, json("POST")),
    folders: (org: string) => call<SpaceFolder[]>(`/organizations/${org}/workspace-folders`),
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
  return `Esta chave alcançará ${docs} em: ${reach.spaces.join(", ")}.`;
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
export const spaceRoleLabel = (role: SpaceRole | null) => role === "manager" ? "Responsável" : role === "member" ? "Membro" : "Sem acesso";

/** Espaços de que a pessoa participa — os únicos que podem filtrar leitura. Admin que não entrou num Espaço o gerencia, mas filtrar por ele daria 404. */
export const memberSpaces = (spaces: Pick<SpaceSummary, "id" | "name" | "my_role">[]): SpaceRef[] =>
  spaces.filter((space) => space.my_role !== null).map((space) => ({ id: space.id, name: space.name }));

/** Dica antes de criar a chave (a contagem de documentos só vem do servidor, depois da criação): a chave lê o que o criador lê. */
export const creatorReachHint = (spaceNames: string[]): string | null =>
  spaceNames.length ? `Esta chave lerá apenas o que está nos seus Espaços: ${spaceNames.join(", ")}.` : null;
