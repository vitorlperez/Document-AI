/** Chamadas do modo "e-mail-robô". Único ponto a ajustar se o contrato final (specs/google/drive-sa-api-contract.md) divergir do design §5.2. */
import { api } from "./types-and-api";
import type { FolderLink, VerifyResult } from "./drive-share-logic";

export type DriveShareEnable = { source_id: string; robot_email: string; share_role?: string };
export type InboxFolder = { id: string; name: string; shared_by_email?: string | null; shared_at?: string | null; linked?: boolean };
export type DriveShareState = { source_id: string; status: string; robot_email: string; folders: FolderLink[] };

export type DriveShareApi = {
  enable(organizationId: string): Promise<DriveShareEnable>;
  inbox(sourceId: string): Promise<InboxFolder[]>;
  verify(sourceId: string, urlOrId: string): Promise<VerifyResult>;
  link(sourceId: string, folderId: string): Promise<FolderLink>;
  unlink(sourceId: string, linkId: string, purge?: boolean): Promise<void>;
  recheck(sourceId: string): Promise<DriveShareState>;
  state(sourceId: string): Promise<DriveShareState>;
};

const base = (sourceId: string) => `/data-sources/google-sa/${encodeURIComponent(sourceId)}`;
const post = (body?: unknown): RequestInit => ({ method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const driveShareApi: DriveShareApi = {
  enable: (organizationId) => api<DriveShareEnable>(`/data-sources/google-sa/enable?organization_id=${encodeURIComponent(organizationId)}`, post()),
  inbox: async (sourceId) => { const data = await api<InboxFolder[] | { items: InboxFolder[] }>(`${base(sourceId)}/inbox`, { cache: "no-store" }); return Array.isArray(data) ? data : data.items; },
  verify: (sourceId, urlOrId) => api<VerifyResult>(`${base(sourceId)}/folders/verify`, post({ url_or_id: urlOrId })),
  link: (sourceId, folderId) => api<FolderLink>(`${base(sourceId)}/folders`, post({ folder_id: folderId })),
  unlink: async (sourceId, linkId, purge = false) => { await api<unknown>(`${base(sourceId)}/folders/${encodeURIComponent(linkId)}${purge ? "?purge=true" : ""}`, { method: "DELETE" }); },
  recheck: (sourceId) => api<DriveShareState>(`${base(sourceId)}/recheck`, post()),
  state: (sourceId) => api<DriveShareState>(base(sourceId), { cache: "no-store" }),
};
