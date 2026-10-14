/** Lógica pura do modo "e-mail-robô" do Google Drive (sem React). Design: specs/google/drive-service-account-design.md §1.2–1.4, §5.3 e ajustes do PoC. */

export const DRIVE_SHARE_PROVIDER = "google_drive_sa";
/** Inbox: consulta a cada 5 s por até 5 min; depois pausa e oferece "Retomar". */
export const POLL_INTERVAL_MS = 5000;
export const POLL_MAX_MS = 5 * 60 * 1000;
/** Sem nada no inbox após 90 s → provável bloqueio de compartilhamento externo do Workspace (não detectável pela API). */
export const WORKSPACE_HINT_AFTER_MS = 90 * 1000;
/** PoC (m11): ~6 min por 1.000 arquivos na primeira sincronização. */
export const FIRST_SYNC_MINUTES_PER_1000 = 6;

/** Flag do frontend. Desligada (padrão) = nenhum caminho novo aparece. Aceita 1/true/on/sim. */
export function driveShareEnabled(value: string | boolean | null | undefined): boolean {
  if (typeof value === "boolean") return value;
  return /^(1|true|on|yes|sim)$/i.test(String(value ?? "").trim());
}

export type ParsedDriveLink =
  | { kind: "folder"; id: string }
  | { kind: "ambiguous"; id: string }
  | { kind: "invalid"; code: "invalid_link" | "not_a_folder" };

const ID = /^[A-Za-z0-9_-]{10,128}$/;
const FILE_HOSTS = new Set(["docs.google.com"]);

/** Aceita as variantes cobertas no PoC (m13): /drive/folders/, /u/N/, /a/dominio/, /mobile/, folderview?id=, open?id= e ID cru. */
export function parseDriveFolderLink(input: string): ParsedDriveLink {
  const text = input.trim();
  if (!text) return { kind: "invalid", code: "invalid_link" };
  if (!/[/:?.]/.test(text)) return ID.test(text) ? { kind: "ambiguous", id: text } : { kind: "invalid", code: "invalid_link" };
  let url: URL;
  try { url = new URL(/^https?:\/\//i.test(text) ? text : `https://${text}`); } catch { return { kind: "invalid", code: "invalid_link" }; }
  if (!/^https?:$/.test(url.protocol)) return { kind: "invalid", code: "invalid_link" };
  const host = url.hostname.toLowerCase();
  if (FILE_HOSTS.has(host)) return { kind: "invalid", code: "not_a_folder" };
  if (host !== "drive.google.com") return { kind: "invalid", code: "invalid_link" };
  const path = url.pathname;
  const folder = path.match(/\/folders\/([^/?#]+)/);
  if (folder) return ID.test(folder[1]) ? { kind: "folder", id: folder[1] } : { kind: "invalid", code: "invalid_link" };
  if (/\/file\/d\//.test(path)) return { kind: "invalid", code: "not_a_folder" };
  if (/\/(folderview|open)$/.test(path)) { const id = url.searchParams.get("id") ?? ""; return ID.test(id) ? { kind: "ambiguous", id } : { kind: "invalid", code: "invalid_link" }; }
  return { kind: "invalid", code: "invalid_link" };
}

export const SAMPLE_FOLDER_LINK = "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz";
export const driveFolderUrl = (folderId: string) => `https://drive.google.com/drive/folders/${encodeURIComponent(folderId)}`;

export type VerifyCode = "ok" | "download_blocked_partial" | "invalid_link" | "not_a_folder" | "not_shared" | "trashed" | "public_link_blocked" | "provider_error" | "rate_limited";
export type DriveErrorMessage = { title: string; hint?: string; /** mostrar Copiar e-mail + "Já compartilhei, verificar de novo" */ share: boolean; example?: boolean; retryLater?: boolean };

/** Textos do §1.3 (PT-BR). `not_shared` é propositalmente igual para "não existe" e "sem acesso". */
export function verifyErrorMessage(code: string, robotEmail: string | null, blockedCount = 0): DriveErrorMessage {
  const email = robotEmail ?? "o e-mail do ArquivIO";
  switch (code) {
    case "invalid_link": return { title: "Esse link não parece ser de uma pasta do Google Drive.", hint: "Abra a pasta no Drive e copie o endereço da barra do navegador.", share: false, example: true };
    case "not_a_folder": return { title: "Esse link não parece ser de uma pasta do Google Drive.", hint: "O endereço colado é de um arquivo. Abra a pasta que contém o arquivo e copie o link dela.", share: false, example: true };
    case "not_shared": return { title: `Ainda não conseguimos abrir essa pasta. Ela precisa estar compartilhada com ${email} como Leitor.`, hint: "Pode levar alguns segundos para o Google liberar o acesso depois de compartilhar.", share: true };
    case "public_link_blocked": return { title: `Essa pasta só está aberta por “qualquer pessoa com o link”. Compartilhe-a diretamente com ${email} como Leitor.`, hint: "Se for uma subpasta de uma pasta já compartilhada com o ArquivIO, o link da subpasta também funciona.", share: true };
    case "trashed": return { title: "Essa pasta está na lixeira do Google Drive.", hint: "Restaure a pasta no Drive e verifique de novo.", share: true };
    case "download_blocked_partial": return { title: `Encontramos ${blockedCount} ${blockedCount === 1 ? "arquivo com download bloqueado" : "arquivos com download bloqueado"} pelo proprietário. O ArquivIO não consegue ler o conteúdo ${blockedCount === 1 ? "dele" : "deles"}.`, hint: "A restrição é por arquivo: peça ao dono para liberar “Leitores podem baixar, imprimir e copiar” em cada um. A pasta pode ser conectada mesmo assim.", share: false };
    case "provider_error": return { title: "Estamos com um problema técnico para acessar o Google Drive. Já fomos avisados.", hint: "Você não precisa reconectar nada. Tente de novo mais tarde.", share: false, retryLater: true };
    case "rate_limited": return { title: "O Google pediu para aguardarmos. Vamos tentar de novo automaticamente.", share: false, retryLater: true };
    default: return { title: "Não foi possível verificar a pasta agora.", hint: "Tente novamente em instantes.", share: false, retryLater: true };
  }
}

export const WORKSPACE_BLOCK_MESSAGE = "Parece que sua empresa não permite compartilhar com endereços de fora. Peça ao administrador do Google Workspace para liberar (texto pronto abaixo) ou use o modo “Entrar com a conta Google”.";

/** Texto pronto para o TI do cliente (§1.4). */
export function itRequestText(robotEmail: string, organizationName?: string): string {
  return [
    "Olá, equipe de TI.",
    "",
    `Precisamos conectar pastas do Google Drive ${organizationName ? `da ${organizationName} ` : ""}ao ArquivIO, plataforma de busca e respostas sobre os documentos da empresa.`,
    `Para isso, precisamos que o compartilhamento externo permita o endereço ${robotEmail}.`,
    "",
    "Esse endereço é exclusivo da nossa empresa no ArquivIO e terá somente permissão de leitura, apenas nas pastas que escolhermos compartilhar. Podemos remover o acesso a qualquer momento.",
    "",
    "Obrigado!",
  ].join("\n");
}

export type ChecklistItem = { key: string; label: string };
export type VerifyResult = { code: string; folder_id?: string; folder_name?: string | null; shared_by_email?: string | null; file_count?: number; folder_count?: number; blocked_download_count?: number };

/** Checklist da Tela 3. Só os itens alcançados aparecem; `ok`/`download_blocked_partial` completam todos. */
export function verifyChecklist(result: VerifyResult): ChecklistItem[] {
  const name = result.folder_name ? ` “${result.folder_name}”` : "";
  const items: ChecklistItem[] = [{ key: "link", label: "Link reconhecido (pasta, não arquivo)" }, { key: "open", label: `O ArquivIO consegue abrir a pasta${name}` }, { key: "read", label: "Permissão de leitura" }];
  const blocked = result.blocked_download_count ?? 0;
  items.push({ key: "download", label: blocked > 0 ? `Conteúdo pode ser baixado (${blocked} ${blocked === 1 ? "arquivo bloqueado" : "arquivos bloqueados"} pelo dono)` : "Conteúdo pode ser baixado (amostra de 20 arquivos)" });
  items.push({ key: "count", label: `Contagem: ${formatCount(result.file_count ?? 0, "arquivo", "arquivos")} · ${formatCount(result.folder_count ?? 0, "subpasta", "subpastas")}` });
  return items;
}
export const formatCount = (n: number, one: string, many: string) => `${n.toLocaleString("pt-BR")} ${n === 1 ? one : many}`;

/** Quantas etapas do checklist aparecem antes do erro. */
export function checklistReach(code: string): number {
  if (code === "ok" || code === "download_blocked_partial") return 5;
  if (code === "invalid_link" || code === "not_a_folder") return 0;
  return 1;
}

/** Aviso de tempo da primeira sincronização (~6 min / 1.000 arquivos, PoC m11). */
export function firstSyncEstimate(fileCount: number): string {
  const minutes = Math.max(1, Math.ceil((fileCount / 1000) * FIRST_SYNC_MINUTES_PER_1000));
  if (fileCount <= 0) return "A primeira sincronização começa assim que você escolher o que sincronizar.";
  if (minutes <= 1) return "A primeira sincronização deve levar cerca de 1 minuto.";
  return `A primeira sincronização deve levar cerca de ${minutes} minutos (aprox. 6 min a cada 1.000 arquivos). Você pode fechar esta janela.`;
}

/** Dica de papel: o Drive sugere "Editor" por padrão; aceitamos Editor/Comentador (drive.readonly já bloqueia escrita). */
export const ROLE_HINT = "O Drive costuma sugerir “Editor”. Troque para Leitor — é tudo de que o ArquivIO precisa. Se você já enviou como Editor, tudo bem: o ArquivIO só consegue ler.";

// ---- polling ----

export type PollState = { phase: "polling" | "paused"; elapsedMs: number; emptyHint: boolean };
export const initialPollState = (): PollState => ({ phase: "polling", elapsedMs: 0, emptyHint: false });
/** Avança o relógio do polling por um tick; pausa ao passar de 5 min; liga a dica de Workspace após 90 s sem pastas. */
export function pollTick(state: PollState, hasFolders: boolean, step = POLL_INTERVAL_MS): PollState {
  if (state.phase === "paused") return state;
  const elapsedMs = state.elapsedMs + step;
  if (hasFolders) return { phase: "polling", elapsedMs, emptyHint: false };
  return { phase: elapsedMs >= POLL_MAX_MS ? "paused" : "polling", elapsedMs, emptyHint: state.emptyHint || elapsedMs >= WORKSPACE_HINT_AFTER_MS };
}
export const resumePoll = (state: PollState): PollState => ({ phase: "polling", elapsedMs: 0, emptyHint: state.emptyHint });

// ---- status do card (Tela 4) e Biblioteca ----

export type DriveShareStatus = "connected" | "awaiting_share" | "access_lost" | "provider_error" | "disconnected" | "reauth_required" | string;
export type StatusTone = "ok" | "pending" | "warning" | "error" | "neutral";
export type StatusPresentation = { label: string; description: string; tone: StatusTone };

export function driveShareStatus(status: DriveShareStatus): StatusPresentation {
  switch (status) {
    case "connected": return { label: "Conectado", description: "O ArquivIO lê as pastas compartilhadas e as mantém atualizadas.", tone: "ok" };
    case "awaiting_share": return { label: "Aguardando compartilhamento", description: "Compartilhe uma pasta do Google Drive com o e-mail abaixo para começar.", tone: "pending" };
    case "access_lost": return { label: "Acesso removido", description: "O compartilhamento foi removido. Paramos de sincronizar e escondemos o conteúdo; para voltar, compartilhe de novo.", tone: "warning" };
    case "provider_error": return { label: "Problema técnico", description: "Estamos com um problema para acessar o Google Drive. Já fomos avisados; você não precisa reconectar.", tone: "error" };
    case "disconnected": return { label: "Desconectado", description: "Esta conexão foi encerrada.", tone: "neutral" };
    default: return { label: "Aguardando", description: "Estamos verificando esta conexão.", tone: "pending" };
  }
}

export const driveShareConnectionLabel = (status: DriveShareStatus) => driveShareStatus(status).label;

export type FolderLink = { id: string; folder_id: string; name: string; status: string; file_count?: number | null; folder_count?: number | null; last_synced_at?: string | null; access_lost_at?: string | null; purge_after?: string | null; blocked_download_count?: number | null; shared_by_email?: string | null };

const DAY = 86_400_000;
export const daysUntil = (iso: string | null | undefined, now: number): number | null => { if (!iso) return null; const t = Date.parse(iso); return Number.isNaN(t) ? null : Math.max(0, Math.ceil((t - now) / DAY)); };

export type AccessBadge = { label: string; description: string; tone: "warning" | "error" };
/** Badge da Biblioteca: "acesso removido" ou "apagando em N dias". `purge_after` nulo = só "acesso removido". */
export function libraryAccessBadge(item: { access_state?: string | null; purge_after?: string | null }, now = Date.now()): AccessBadge | null {
  if (item.access_state !== "access_lost" && item.access_state !== "purge_scheduled") return null;
  const days = daysUntil(item.purge_after, now);
  if (days === null) return { label: "Acesso removido", description: "O compartilhamento da pasta foi removido. O conteúdo está oculto das respostas e será apagado se o acesso não voltar.", tone: "warning" };
  const label = days === 0 ? "Apagando hoje" : days === 1 ? "Apagando em 1 dia" : `Apagando em ${days} dias`;
  return { label: `Acesso removido · ${label.toLowerCase()}`, description: `O compartilhamento foi removido: o conteúdo está oculto das respostas e será apagado definitivamente ${days === 0 ? "hoje" : `em ${days} ${days === 1 ? "dia" : "dias"}`}. Compartilhe a pasta de novo para reativar, ou use “Apagar agora” em Integrações.`, tone: days <= 2 ? "error" : "warning" };
}

export function relativeSync(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "ainda não sincronizada";
  const t = Date.parse(iso); if (Number.isNaN(t)) return "ainda não sincronizada";
  const min = Math.max(0, Math.round((now - t) / 60000));
  if (min < 1) return "sync agora há pouco";
  if (min < 60) return `sync há ${min} min`;
  const h = Math.round(min / 60); if (h < 24) return `sync há ${h} h`;
  const d = Math.round(h / 24); return `sync há ${d} ${d === 1 ? "dia" : "dias"}`;
}
