/** Google Drive unificado: as conexões "pasta compartilhada" (google_drive_sa) e "conta Google" (google_drive) são uma
 * ferramenta só para o usuário. Lógica pura (testada em tests/drive-unified.test.mjs); o backend segue com dois providers. */
type SourceLike = { id: string; provider: string; status: string; account_email?: string | null };
type FolderLinkLike = { id: string; link_id?: string; folder_id?: string; name: string; status: string; file_count?: number | null; last_synced_at?: string | null; purge_after?: string | null };
type WorkspaceFolderLike = { id: string; name: string; status: string; last_synced_at: string | null; source_id?: string };

export type DriveMethodKey = "share" | "oauth";
const DAY = 86_400_000;
const alive = (source: SourceLike | undefined) => (source && source.status !== "disconnected" ? source : null);

export function driveConnections<T extends SourceLike>(sources: T[]): { oauth: T | null; share: T | null } {
  return {
    oauth: alive(sources.find((item) => item.provider === "google_drive")) as T | null,
    share: alive(sources.find((item) => item.provider === "google_drive_sa")) as T | null,
  };
}

export type CardStatus = { tone: "ok" | "pending" | "warning" | "error" | "neutral"; label: string; description: string };

export function driveCardStatus({ oauth, share }: { oauth: SourceLike | null; share: SourceLike | null }): CardStatus {
  if (oauth?.status === "connected" || share?.status === "connected") return { tone: "ok", label: "Conectado", description: "O ArquivIO lê as pastas conectadas e as mantém atualizadas." };
  switch (share?.status) {
    case "awaiting_share": return { tone: "pending", label: "Aguardando compartilhamento", description: "Compartilhe uma pasta do Google Drive com o e-mail do ArquivIO para começar." };
    case "provisioning": return { tone: "pending", label: "Preparando", description: "Estamos preparando o e-mail exclusivo da sua empresa. Isso leva até um ou dois minutos." };
    case "access_lost": return { tone: "warning", label: "Acesso removido", description: "O compartilhamento foi removido. Paramos de sincronizar e escondemos o conteúdo; para voltar, compartilhe de novo." };
    case "provider_error": case "provisioning_failed": return { tone: "error", label: "Problema técnico", description: "Estamos com um problema para acessar o Google Drive. Já fomos avisados; você não precisa reconectar." };
    default:
  }
  if (oauth?.status === "reauth_required") return { tone: "warning", label: "Reconexão necessária", description: "O acesso à conta Google expirou ou foi revogado. Reconecte para voltar a sincronizar." };
  if (share) return { tone: "pending", label: "Aguardando", description: "Estamos verificando esta conexão." };
  return { tone: "neutral", label: "Disponível", description: "Conecte pastas do Google Drive para a base de conhecimento da sua organização." };
}

export type UnifiedFolder = { key: string; name: string; method: DriveMethodKey; lost: boolean; meta: string | null; fileCount: number | null; lastSyncedAt: string | null; linkId: string | null; canUnlink: boolean; status: string };
const LOST = new Set(["suspect", "access_lost", "purge_scheduled"]);

export function unifiedDriveFolders({ shareFolders, oauthFolders, oauthSourceId, now }: { shareFolders: FolderLinkLike[]; oauthFolders: WorkspaceFolderLike[]; oauthSourceId: string | null; now: number }): UnifiedFolder[] {
  const share: UnifiedFolder[] = shareFolders.map((f) => {
    const lost = LOST.has(f.status);
    const days = f.purge_after && !Number.isNaN(Date.parse(f.purge_after)) ? Math.max(0, Math.ceil((Date.parse(f.purge_after) - now) / DAY)) : null;
    return { key: `share:${f.id}`, name: f.name, method: "share", lost, meta: lost ? `acesso removido${days !== null ? ` · apagando em ${days} ${days === 1 ? "dia" : "dias"}` : ""}` : null, fileCount: f.file_count ?? null, lastSyncedAt: f.last_synced_at ?? null, linkId: f.link_id ?? null, canUnlink: Boolean(f.link_id), status: f.status };
  });
  const oauth: UnifiedFolder[] = oauthSourceId ? oauthFolders.filter((f) => f.source_id === oauthSourceId).map((f) => ({ key: `oauth:${f.id}`, name: f.name, method: "oauth", lost: false, meta: null, fileCount: null, lastSyncedAt: f.last_synced_at, linkId: null, canUnlink: false, status: f.status })) : [];
  return [...share, ...oauth];
}

export type DriveCardActions<T extends SourceLike = SourceLike> = {
  primary: { kind: "start-share" | "add-folders"; label: string };
  disconnect: { method: DriveMethodKey; source: T }[];
  reconnectOauth: boolean;
  manage: T | null;
};

export function driveCardActions<T extends SourceLike>({ oauth, share }: { oauth: T | null; share: T | null }): DriveCardActions<T> {
  const nothing = !oauth && !share;
  const waiting = !oauth && share?.status !== "connected" && share?.status !== "access_lost";
  return {
    primary: nothing ? { kind: "start-share", label: "Conectar" } : { kind: "add-folders", label: waiting ? "Compartilhar pastas" : "Adicionar pastas" },
    disconnect: [...(share ? [{ method: "share" as const, source: share }] : []), ...(oauth ? [{ method: "oauth" as const, source: oauth }] : [])],
    reconnectOauth: oauth?.status === "reauth_required",
    manage: oauth?.status === "connected" ? oauth : share?.status === "connected" ? share : null,
  };
}
