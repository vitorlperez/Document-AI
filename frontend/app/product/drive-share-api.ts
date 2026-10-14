/** Chamadas do modo "e-mail-robô". Único ponto a ajustar se o contrato (specs/google/drive-sa-api-contract.md) mudar.
 * Todas as rotas levam `organization_id` na query; erros chegam como `{detail:{code}}` e viram códigos da UI (drive-share-logic). */
import { API_BASE, ApiError } from "./types-and-api";
import { verifyCodeFor, type FolderLink, type VerifyResult } from "./drive-share-logic";

export type DriveShareEnable = { source_id: string; robot_email: string; share_role?: string };
export type InboxFolder = { id: string; name: string; shared_by_email?: string | null; shared_at?: string | null; linked?: boolean };
export type DriveShareState = { source_id: string; status: string; robot_email: string; folders: FolderLink[] };
export type LinkResult = { link_id: string; folder_id: string; status: string; workspace_folder_id?: string };

export type DriveShareApi = {
  enable(organizationId: string): Promise<DriveShareEnable>;
  inbox(sourceId: string): Promise<InboxFolder[]>;
  verify(sourceId: string, urlOrId: string): Promise<VerifyResult>;
  link(sourceId: string, folderId: string): Promise<LinkResult>;
  unlink(sourceId: string, linkId: string, purge?: boolean): Promise<void>;
  recheck(sourceId: string): Promise<void>;
  /** Dados do card: e-mail do robô (enable é idempotente) + vínculos. */
  state(sourceId: string, status?: string): Promise<DriveShareState>;
};

export class DriveShareError extends Error { constructor(public readonly status: number, public readonly code: string | null, message: string) { super(message); } }

let organization = "";
/** A tela de Integrações informa a organização ativa (rotas do card chamam sem passar por enable). */
export const setDriveShareOrganization = (id: string) => { organization = id; };
async function call<T>(path: string, init: RequestInit = {}, org = organization): Promise<T> {
  const url = `${API_BASE}${path}${path.includes("?") ? "&" : "?"}organization_id=${encodeURIComponent(org)}`;
  const response = await fetch(url, { credentials: "include", cache: "no-store", ...init, headers: { "Content-Type": "application/json", ...(init.headers ?? {}) } });
  if (response.status === 204) return undefined as T;
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = (body as { detail?: unknown } | null)?.detail;
    const code = typeof detail === "object" && detail !== null && "code" in detail ? String((detail as { code: unknown }).code) : null;
    throw new DriveShareError(response.status, code, typeof detail === "string" ? detail : code ?? `HTTP ${response.status}`);
  }
  return body as T;
}
const base = (sourceId: string) => `/data-sources/google-sa/${encodeURIComponent(sourceId)}`;
const post = (body?: unknown): RequestInit => ({ method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
const asApiError = (error: unknown) => error instanceof DriveShareError ? new ApiError(error.status, error.code === "forbidden" ? "Você não tem permissão para esta ação." : error.status >= 500 ? "O serviço está temporariamente indisponível. Tente novamente em instantes." : error.message) : error;

export const driveShareApi: DriveShareApi = {
  enable: async (organizationId) => { organization = organizationId; try { return await call<DriveShareEnable>("/data-sources/google-sa/enable", post(), organizationId); } catch (e) { throw asApiError(e); } },
  inbox: async (sourceId) => { try { return (await call<{ folders: InboxFolder[] }>(`${base(sourceId)}/inbox`)).folders; } catch (e) { throw asApiError(e); } },
  verify: async (sourceId, urlOrId) => {
    try { return await call<VerifyResult>(`${base(sourceId)}/folders/verify`, post({ url_or_id: urlOrId })); }
    catch (error) {
      // 404/422/429/503 são resultados esperados da verificação, não falhas: viram um `code` que a UI explica em PT-BR.
      if (error instanceof DriveShareError && [404, 409, 422, 429, 503].includes(error.status)) return { code: verifyCodeFor(error.code, error.status) };
      throw asApiError(error);
    }
  },
  link: async (sourceId, folderId) => { try { return await call<LinkResult>(`${base(sourceId)}/folders`, post({ folder_id: folderId })); } catch (e) { throw asApiError(e); } },
  unlink: async (sourceId, linkId, purge = false) => { try { await call<unknown>(`${base(sourceId)}/folders/${encodeURIComponent(linkId)}?purge=${purge ? "true" : "false"}`, { method: "DELETE" }); } catch (e) { throw asApiError(e); } },
  recheck: async (sourceId) => { try { await call<unknown>(`${base(sourceId)}/recheck`, post()); } catch (e) { throw asApiError(e); } },
  state: async (sourceId, status = "connected") => {
    // O contrato ainda não lista vínculos. Tentamos `GET .../folders` (proposto: link_id, folder_id, name, status, purge_after, file_count,
    // last_synced_at); se a rota não existir, caímos para o e-mail de `enable` (idempotente) + pastas `linked:true` do inbox (sem link_id).
    try {
      const robot = await call<DriveShareEnable>("/data-sources/google-sa/enable", post());
      const listed = await call<FolderLink[] | { folders?: FolderLink[]; links?: FolderLink[] }>(`${base(sourceId)}/folders`).then((r) => (Array.isArray(r) ? r : r.folders ?? r.links ?? null)).catch(() => null);
      if (listed) return { source_id: sourceId, status, robot_email: robot.robot_email, folders: listed };
      const inbox = await call<{ folders: InboxFolder[] }>(`${base(sourceId)}/inbox`).then((r) => r.folders).catch(() => [] as InboxFolder[]);
      return { source_id: sourceId, status, robot_email: robot.robot_email, folders: inbox.filter((f) => f.linked).map((f) => ({ id: f.id, folder_id: f.id, name: f.name, status: "verified", shared_by_email: f.shared_by_email ?? null })) };
    } catch (e) { throw asApiError(e); }
  },
};
