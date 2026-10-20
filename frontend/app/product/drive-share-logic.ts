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

/** Códigos do backend → códigos de verificação da UI (mensagens em drive-share-logic.verifyErrorMessage). */
export function verifyCodeFor(code: string | null, status: number): string {
  switch (code) {
    case "not_shared": return "not_shared";
    case "invalid_folder_link": return "invalid_link";
    case "not_a_folder": return "not_a_folder";
    case "rate_limited": return "rate_limited";
    case "robot_unavailable": case "provider_unavailable": case "pool_empty": case "robot_retired": return "provider_error";
    default: return status === 404 ? "not_shared" : status === 422 ? "invalid_link" : status === 429 ? "rate_limited" : "provider_error";
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
export type VerifyResult = { code: string; folder_id?: string; /** contrato: `name` */ name?: string | null; folder_name?: string | null; shared_by_email?: string | null; file_count?: number; folder_count?: number; blocked_download_count?: number };

/** Checklist da Tela 3. Só os itens alcançados aparecem; `ok`/`download_blocked_partial` completam todos. */
export function verifyChecklist(result: VerifyResult): ChecklistItem[] {
  const name = result.folder_name ? ` “${result.folder_name}”` : "";
  const items: ChecklistItem[] = [{ key: "link", label: "Link reconhecido (pasta, não arquivo)" }, { key: "open", label: `O ArquivIO consegue abrir a pasta${name}` }, { key: "read", label: "Permissão de leitura" }];
  const blocked = result.blocked_download_count ?? 0;
  items.push({ key: "download", label: blocked > 0 ? `Conteúdo pode ser baixado (${blocked} ${blocked === 1 ? "arquivo bloqueado" : "arquivos bloqueados"} pelo dono)` : "Conteúdo pode ser baixado (amostra de 20 arquivos)" });
  const reached = result.code === "ok" || result.code === "download_blocked_partial";
  items.push({ key: "count", label: !reached ? "Contagem de arquivos e subpastas" : `Contagem: ${formatCount(result.file_count ?? 0, "arquivo", "arquivos")}${result.folder_count == null ? "" : ` · ${formatCount(result.folder_count, "subpasta", "subpastas")}`}` });
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
    case "provisioning": return { label: "Preparando", description: "Estamos preparando o e-mail exclusivo da sua empresa. Isso leva até um ou dois minutos.", tone: "pending" };
    case "provisioning_failed": return { label: "Problema técnico", description: "Não conseguimos preparar o e-mail agora. Abra a conexão e tente de novo.", tone: "error" };
    case "disconnected": return { label: "Desconectado", description: "Esta conexão foi encerrada.", tone: "neutral" };
    default: return { label: "Aguardando", description: "Estamos verificando esta conexão.", tone: "pending" };
  }
}

export const driveShareConnectionLabel = (status: DriveShareStatus) => driveShareStatus(status).label;

export type FolderLink = { id: string; /** id do vínculo (necessário para "Apagar agora"); ausente quando só o inbox é conhecido */ link_id?: string; folder_id: string; name: string; status: string; file_count?: number | null; folder_count?: number | null; last_synced_at?: string | null; access_lost_at?: string | null; purge_after?: string | null; blocked_download_count?: number | null; shared_by_email?: string | null };

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


// ---- várias pastas de uma vez (passos 1–3 do fluxo multi-pasta) ----

/** Pasta detectada no inbox do robô (contrato: GET .../inbox). `nested_in` = ancestral mais próximo já visto pelo servidor. */
export type DetectedFolder = { id: string; name: string; shared_by_email?: string | null; shared_at?: string | null; linked?: boolean; parent_ids?: string[]; nested_in?: { id: string; name: string; linked: boolean } | null; /** adicionada por link colado */ via?: "link" };

/** Contador do passo 1 (aria-live). */
export function foundFoldersLabel(count: number): string {
  if (count <= 0) return "Nenhuma pasta encontrada ainda";
  return `${count.toLocaleString("pt-BR")} ${count === 1 ? "pasta encontrada" : "pastas encontradas"}`;
}

/** Pastas que ainda podem ser conectadas (as já vinculadas ficam de fora). */
export const unlinkedFolders = <T extends { linked?: boolean }>(folders: T[]): T[] => folders.filter((f) => !f.linked);

/**
 * Ancestrais de `folder` conhecidos (do mais próximo ao mais distante), seguindo `parent_ids[0]` pelas pastas detectadas
 * (inclui as já vinculadas). Cai em `nested_in` quando o pai não está na lista. Sem ciclos e no máximo 10 saltos.
 */
export function knownAncestors(folder: DetectedFolder, all: DetectedFolder[]): { id: string; name: string; linked: boolean }[] {
  const byId = new Map(all.map((f) => [f.id, f]));
  const chain: { id: string; name: string; linked: boolean }[] = [];
  const seen = new Set([folder.id]);
  let current: DetectedFolder | undefined = folder;
  for (let hop = 0; hop < 10 && current; hop++) {
    const parentId: string | undefined = current.parent_ids?.[0];
    if (!parentId || seen.has(parentId)) break;
    seen.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    chain.push({ id: parent.id, name: parent.name, linked: Boolean(parent.linked) });
    current = parent;
  }
  if (chain.length === 0 && folder.nested_in) chain.push(folder.nested_in);
  return chain;
}

/** Seleção explícita do usuário por id; o que ele não tocou segue o padrão (marcada, exceto pasta dentro de outra pasta detectada). */
export type SelectionChoices = Record<string, boolean>;
export function isSelected(folder: DetectedFolder, all: DetectedFolder[], choices: SelectionChoices): boolean {
  if (folder.id in choices) return choices[folder.id];
  return knownAncestors(folder, all).length === 0;
}

/** Aviso de aninhamento: só para pasta marcada cujo ancestral já está vinculado ou também está marcado. */
export function nestedWarning(folder: DetectedFolder, all: DetectedFolder[], choices: SelectionChoices): { id: string; name: string } | null {
  if (!isSelected(folder, all, choices)) return null;
  const hit = knownAncestors(folder, all).find((a) => a.linked || (() => { const f = all.find((x) => x.id === a.id); return f ? isSelected(f, all, choices) : false; })());
  return hit ? { id: hit.id, name: hit.name } : null;
}
export const nestedWarningText = (parentName: string) => `Esta pasta está dentro de “${parentName}” — os arquivos já serão incluídos.`;

export const nestedSeparationHint = "Para separar por Espaço, compartilhe cada subpasta com o e-mail da sua empresa.";

/** Espaços oferecidos ao ligar pasta ("Quem poderá ver esta pasta?"). */
export type LinkSpaceOption = { id: string; name: string; is_default?: boolean };
/** Pré-marca o Espaço padrão; sem padrão e com um só Espaço, esse; senão nada (a pessoa precisa escolher). */
export function defaultSpaceSelection(spaces: LinkSpaceOption[]): string[] {
  const preset = spaces.filter((space) => space.is_default).map((space) => space.id);
  return preset.length ? preset : spaces.length === 1 ? [spaces[0].id] : [];
}
/** Não liga pasta sem Espaço. `spacesKnown=false` (lista indisponível) não bloqueia: o servidor usa o Espaço padrão. */
export const canLink = ({ spaceIds, spacesKnown = true }: { spaceIds: string[]; spacesKnown?: boolean }) => !spacesKnown || spaceIds.length > 0;
export const toggleSpace = (selected: string[], id: string) => selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id];

export function selectedIds(folders: DetectedFolder[], choices: SelectionChoices): string[] {
  return folders.filter((f) => isSelected(f, folders, choices)).map((f) => f.id);
}
/** “Selecionar todas”: se tudo já está marcado, desmarca tudo; senão marca tudo (inclusive as aninhadas, que continuam com aviso). */
export function toggleAll(folders: DetectedFolder[], choices: SelectionChoices): SelectionChoices {
  const allOn = folders.every((f) => isSelected(f, folders, choices));
  return Object.fromEntries(folders.map((f) => [f.id, !allOn]));
}
export const connectLabel = (count: number) => count === 0 ? "Conectar pastas" : count === 1 ? "Conectar 1 pasta" : `Conectar ${count} pastas`;

/** Linha do resultado em lote (contrato: POST .../folders/batch). */
export type BatchRow = { folder_id: string; name?: string | null; status: "ok" | "nested" | "error"; code: string; link_id?: string; workspace_folder_id?: string; file_count?: number; blocked_download_count?: number; parent_name?: string };
export type BatchRowView = { tone: "ok" | "warn" | "info" | "error"; label: string; hint?: string; retry: boolean };

export function batchRowView(row: BatchRow, robotEmail: string | null = null): BatchRowView {
  if (row.status === "ok") {
    const blocked = row.blocked_download_count ?? 0;
    return row.code === "download_blocked_partial" || blocked > 0
      ? { tone: "warn", label: `Conectada — ${blocked} ${blocked === 1 ? "arquivo com download bloqueado" : "arquivos com download bloqueado"} pelo dono`, hint: verifyErrorMessage("download_blocked_partial", null, blocked).hint, retry: false }
      : { tone: "ok", label: `Conectada${row.file_count != null ? ` · ${formatCount(row.file_count, "arquivo", "arquivos")}` : ""}`, retry: false };
  }
  if (row.status === "nested") return { tone: "info", label: `Já incluída em “${row.parent_name ?? "outra pasta"}” — os arquivos já estão lá`, retry: false };
  const message = verifyErrorMessage(verifyCodeFor(row.code, 0), robotEmail);
  return { tone: "error", label: message.title, hint: message.hint, retry: message.retryLater || message.share };
}

export type BatchSummary = { connected: number; nested: number; failed: number; text: string };
export function batchSummary(rows: BatchRow[]): BatchSummary {
  const connected = rows.filter((r) => r.status === "ok").length;
  const nested = rows.filter((r) => r.status === "nested").length;
  const failed = rows.filter((r) => r.status === "error").length;
  const parts = [connected > 0 ? `${connected} ${connected === 1 ? "pasta conectada" : "pastas conectadas"} · sincronizando` : "Nenhuma pasta conectada"];
  if (nested > 0) parts.push(`${nested} já ${nested === 1 ? "incluída" : "incluídas"} em outra`);
  if (failed > 0) parts.push(`${failed} com problema`);
  return { connected, nested, failed, text: parts.join(" · ") };
}
/** Pastas a sincronizar depois do lote (somente as recém-conectadas com workspace). */
export const syncTargets = (rows: BatchRow[]): string[] => [...new Set(rows.filter((r) => r.status === "ok" && r.workspace_folder_id).map((r) => r.workspace_folder_id as string))];
/** Pastas do lote que vale tentar de novo (erros transitórios ou de compartilhamento). */
export const retryableIds = (rows: BatchRow[]): string[] => rows.filter((r) => r.status === "error" && batchRowView(r).retry).map((r) => r.folder_id);

/** Textos da confirmação de “Desvincular” (§ card conectado). */
export function unlinkConfirmCopy(name: string) {
  return {
    title: `Desvincular “${name}”?`,
    body: "O conteúdo desta pasta some das respostas e da Biblioteca agora. Os arquivos indexados são apagados definitivamente em 14 dias; se você compartilhar a pasta de novo antes disso, tudo volta.",
    keep: "Desvincular (apagar em 14 dias)",
    purge: "Apagar agora",
    purgeHint: "Remove já os documentos indexados desta pasta. Não pode ser desfeito.",
  };
}
