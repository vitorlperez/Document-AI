/** Chamadas do modo "e-mail-robô". Único ponto a ajustar se o contrato (specs/google/drive-sa-api-contract.md) mudar.
 * Todas as rotas levam `organization_id` na query; erros chegam como `{detail:{code}}` e viram códigos da UI (drive-share-logic). */
import { API_BASE, ApiError, api } from "./types-and-api";
import { verifyCodeFor, type LinkSpaceOption, type BatchRow, type DetectedFolder, type FolderLink, type VerifyResult } from "./drive-share-logic";

/** `status`: "provisioning" enquanto o worker cria o robô exclusivo da organização (poll em `status`); "ready" já traz o e-mail. */
export type ProvisionStatus = "provisioning" | "ready" | "failed";
export type DriveShareEnable = { source_id: string; robot_email: string | null; status?: ProvisionStatus; share_role?: string };
/** Pasta do inbox: `parent_ids` e `nested_in` descrevem a hierarquia que o robô enxerga (contrato: GET .../inbox). */
export type InboxFolder = DetectedFolder;
export type DriveShareState = { source_id: string; status: string; robot_email: string | null; provision?: ProvisionStatus; folders: FolderLink[] };
/** Linha de `GET .../folders` (contrato): `link_id` é o id do vínculo, `folder_id` o do Drive. */
export type LinkedFolder = { link_id: string; folder_id: string; name: string; workspace_folder_id?: string | null; status: string; purge_after?: string | null; shared_by_email?: string | null; shared_at?: string | null; blocked_download_count?: number | null; last_synced_at?: string | null };
const toFolderLink = (f: LinkedFolder): FolderLink => ({ ...f, id: f.link_id });
export type LinkResult = { link_id: string; folder_id: string; status: string; workspace_folder_id?: string };

export type DriveShareApi = {
  enable(organizationId: string): Promise<DriveShareEnable>;
  /** Estado do provisionamento do robô (leitura pura; use para o polling em vez de chamar enable de novo). */
  provisioning(sourceId: string): Promise<DriveShareEnable>;
  inbox(sourceId: string): Promise<InboxFolder[]>;
  verify(sourceId: string, urlOrId: string): Promise<VerifyResult>;
  /** `spaceIds`: Espaços que passarão a ver a pasta (T-F6b no backend). Omitido ⇒ o servidor usa o Espaço padrão. */
  link(sourceId: string, folderId: string, spaceIds?: string[]): Promise<LinkResult>;
  /** Verifica e conecta várias pastas de uma vez; uma linha por pasta, falha em uma não aborta as demais. */
  linkBatch(sourceId: string, folderIds: string[], spaceIds?: string[]): Promise<BatchRow[]>;
  /** Espaços que a pessoa pode escolher ao ligar uma pasta. Opcional: indisponível ⇒ o passo "Quem poderá ver" é omitido. */
  listSpaces?(organizationId: string): Promise<LinkSpaceOption[]>;
  unlink(sourceId: string, linkId: string, purge?: boolean): Promise<void>;
  recheck(sourceId: string): Promise<void>;
  /** Primeira sincronização da pasta recém-vinculada (rota atual da Biblioteca); falha aqui não desfaz o vínculo. */
  startSync(workspaceFolderId: string): Promise<void>;
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
const asApiError = (error: unknown) => error instanceof DriveShareError ? new ApiError(error.status, error.code === "forbidden" ? "Você não tem permissão para esta ação." : error.code === "unauthenticated" ? "Sua sessão expirou. Entre novamente." : error.code === "invalid_request" ? "Não foi possível processar o pedido. Atualize a página e tente de novo." : error.status >= 500 ? "O serviço está temporariamente indisponível. Tente novamente em instantes." : error.message) : error;

export const driveShareApi: DriveShareApi = {
  enable: async (organizationId) => { organization = organizationId; try { return await call<DriveShareEnable>("/data-sources/google-sa/enable", post(), organizationId); } catch (e) { throw asApiError(e); } },
  provisioning: async (sourceId) => { try { return await call<DriveShareEnable>(`${base(sourceId)}/status`); } catch (e) { throw asApiError(e); } },
  inbox: async (sourceId) => { try { return (await call<{ folders: InboxFolder[] }>(`${base(sourceId)}/inbox`)).folders; } catch (e) { throw asApiError(e); } },
  verify: async (sourceId, urlOrId) => {
    try { return await call<VerifyResult>(`${base(sourceId)}/folders/verify`, post({ url_or_id: urlOrId })); }
    catch (error) {
      // 404/422/429/503 são resultados esperados da verificação, não falhas: viram um `code` que a UI explica em PT-BR.
      if (error instanceof DriveShareError && [404, 409, 422, 429, 503].includes(error.status)) return { code: verifyCodeFor(error.code, error.status) };
      throw asApiError(error);
    }
  },
  link: async (sourceId, folderId, spaceIds) => { try { return await call<LinkResult>(`${base(sourceId)}/folders`, post({ folder_id: folderId, ...(spaceIds?.length ? { space_ids: spaceIds } : {}) })); } catch (e) { throw asApiError(e); } },
  linkBatch: async (sourceId, folderIds, spaceIds) => { try { return (await call<{ results: BatchRow[] }>(`${base(sourceId)}/folders/batch`, post({ folder_ids: folderIds, ...(spaceIds?.length ? { space_ids: spaceIds } : {}) }))).results; } catch (e) { throw asApiError(e); } },
  unlink: async (sourceId, linkId, purge = false) => { try { await call<unknown>(`${base(sourceId)}/folders/${encodeURIComponent(linkId)}?purge=${purge ? "true" : "false"}`, { method: "DELETE" }); } catch (e) { throw asApiError(e); } },
  recheck: async (sourceId) => { try { await call<unknown>(`${base(sourceId)}/recheck`, post()); } catch (e) { throw asApiError(e); } },
  listSpaces: async (organizationId) => { try { return await api<LinkSpaceOption[]>(`/organizations/${encodeURIComponent(organizationId)}/spaces`); } catch (e) { throw asApiError(e); } },
  startSync: async (workspaceFolderId) => { try { await call<unknown>(`/library/workspaces/${encodeURIComponent(workspaceFolderId)}/reprocess`, post()); } catch (e) { throw asApiError(e); } },
  state: async (sourceId, status = "connected") => {
    // `GET .../status` devolve o e-mail do robô sem criar nada (não chama enable); `GET .../folders` lista os vínculos (inclui suspect/access_lost/removed).
    try {
      const robot = await call<DriveShareEnable>(`${base(sourceId)}/status`);
      if (robot.status === "provisioning" || robot.status === "failed") return { source_id: sourceId, status, robot_email: null, provision: robot.status, folders: [] };
      const { folders } = await call<{ folders: LinkedFolder[] }>(`${base(sourceId)}/folders`);
      return { source_id: sourceId, status, robot_email: robot.robot_email, provision: "ready", folders: folders.filter((f) => f.status !== "removed").map(toFolderLink) };
    } catch (e) { throw asApiError(e); }
  },
};
