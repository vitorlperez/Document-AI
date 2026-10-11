/** Pure helpers for the in-chat file viewer: which renderer a file gets, the resizable width, source highlight and error copy. */

export const PDF_MIME = "application/pdf";
export const DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
const GOOGLE_DOC = "application/vnd.google-apps.document";

export type DocumentView = {
  document_id: string; name: string; mime_type: string; source_provider: string; source_url: string | null;
  file_available: boolean; file_content_type: string | null; office_preview: boolean;
};
export type ViewerKind = "pdf" | "docx" | "text";

/**
 * Original-file renderers exist for PDF (any provider, Google Docs exported as PDF) and DOCX. Spreadsheets, slides, Notion and
 * ClickUp stay on the extracted text (no download), which is also where any failed original falls back to.
 */
export function viewerFor(view: Pick<DocumentView, "mime_type" | "file_available" | "file_content_type">): ViewerKind {
  if (!view.file_available) return "text";
  if (view.mime_type === GOOGLE_DOC || view.file_content_type === PDF_MIME && view.mime_type === PDF_MIME) return "pdf";
  if (view.file_content_type === DOCX_MIME) return "docx";
  return "text";
}

export type FileErrorCode =
  | "source_access_denied" | "source_file_missing" | "source_file_unavailable" | "file_too_large" | "viewer_not_supported" | "source_throttled" | "source_unavailable"
  | "network_error" | "session_expired" | "forbidden" | "render_password" | "render_invalid" | "render_viewer_unavailable" | "render_failed";

const FILE_ERRORS: Record<FileErrorCode, string> = {
  source_access_denied: "A conexão com a ferramenta de origem não permite abrir este arquivo agora. Reconecte a ferramenta ou abra o original.",
  source_file_missing: "O arquivo não foi encontrado na ferramenta de origem — pode ter sido movido ou excluído.",
  source_file_unavailable: "A ferramenta de origem não liberou este arquivo para visualização.",
  file_too_large: "O arquivo é grande demais para visualizar aqui.",
  viewer_not_supported: "Este tipo de arquivo não tem visualização completa; mostramos o texto extraído.",
  source_throttled: "A ferramenta de origem pediu um intervalo. Tente novamente em instantes.",
  source_unavailable: "Não foi possível falar com a ferramenta de origem agora.",
  network_error: "Falha de conexão ao carregar o arquivo. Verifique sua internet e tente novamente.",
  forbidden: "Você não tem permissão para visualizar este arquivo.",
  session_expired: "Sua sessão expirou. Entre novamente para visualizar o arquivo.",
  render_password: "Este PDF é protegido por senha e não pode ser exibido aqui. Abra o original.",
  render_invalid: "O arquivo baixado não é um documento válido ou está corrompido. Abra o original.",
  render_viewer_unavailable: "Não foi possível carregar o visualizador de documentos neste navegador.",
  render_failed: "Não foi possível exibir o arquivo original aqui.",
};

/** Maps a failure thrown by pdf.js / docx-preview to a stable code, so the UI can say why instead of a generic apology. */
export function renderFailureCode(error: unknown): FileErrorCode {
  const name = typeof error === "object" && error !== null && "name" in error ? String((error as { name: unknown }).name) : "";
  const message = error instanceof Error ? error.message : typeof error === "string" ? error : "";
  if (name === "PasswordException") return "render_password";
  if (name === "InvalidPDFException" || name === "FormatError" || /not a (valid )?(pdf|zip)|corrupt|end of central directory|invalid pdf/i.test(message)) return "render_invalid";
  if (/worker|dynamically imported module|importing a module script|load failed|Not allowed to load local resource/i.test(message)) return "render_viewer_unavailable";
  return "render_failed";
}

/** What the response status of GET /file means when the body carries no `detail` code. */
export function httpFileErrorCode(status: number): FileErrorCode | string {
  if (status === 401) return "session_expired";
  if (status === 403) return "forbidden";
  if (status === 404) return "source_file_missing";
  if (status === 415) return "viewer_not_supported";
  if (status === 413) return "file_too_large";
  return `http_${status}`;
}

export function fileErrorMessage(code: string | null | undefined): string {
  return (code && FILE_ERRORS[code as FileErrorCode]) || "Não foi possível carregar a visualização deste arquivo.";
}

/** Failures where the extracted text is still a useful substitute for the original. */
export const fallsBackToText = (code: string | null | undefined) => code === "file_too_large" || code === "viewer_not_supported" || code === "source_file_unavailable";

export const VIEWER_MIN_WIDTH = 340;
export const VIEWER_DEFAULT_RATIO = 0.46;
export const CHAT_MIN_WIDTH = 360;
export const VIEWER_WIDTH_KEY = "arquivio:file-viewer-width";

/** Keeps the viewer readable and the chat usable: `available` is the width of the chat + viewer area. */
export function clampViewerWidth(width: number, available: number): number {
  const max = Math.max(VIEWER_MIN_WIDTH, available - CHAT_MIN_WIDTH);
  return Math.round(Math.min(Math.max(Number.isFinite(width) ? width : 0, VIEWER_MIN_WIDTH), max));
}
export const defaultViewerWidth = (available: number) => clampViewerWidth(available * VIEWER_DEFAULT_RATIO, available);

export function parseStoredWidth(raw: string | null): number | null {
  const value = raw === null ? Number.NaN : Number(raw);
  return Number.isFinite(value) && value >= VIEWER_MIN_WIDTH && value <= 4000 ? value : null;
}
export function readStoredWidth(storage: Pick<Storage, "getItem"> | undefined = typeof window === "undefined" ? undefined : window.localStorage): number | null {
  try { return storage ? parseStoredWidth(storage.getItem(VIEWER_WIDTH_KEY)) : null; } catch { return null; }
}
export function storeWidth(width: number, storage?: Pick<Storage, "setItem">): void {
  try { (storage ?? window.localStorage).setItem(VIEWER_WIDTH_KEY, String(Math.round(width))); } catch { /* private mode / blocked storage: the width just isn't remembered */ }
}

/** Width after dragging the divider: the handle sits on the viewer's left edge, so moving left makes it wider. */
export const widthAfterDrag = (startWidth: number, startX: number, currentX: number, available: number) => clampViewerWidth(startWidth + (startX - currentX), available);

/** Highlight shown on a source row after clicking its [N]: cleared after a few seconds or when another is picked. */
export const HIGHLIGHT_MS = 6000;
export type SourceHighlight = { number: number; nonce: number } | null;
export function nextHighlight(current: SourceHighlight, number: number): NonNullable<SourceHighlight> {
  return { number, nonce: (current?.nonce ?? 0) + 1 };
}
export const isHighlighted = (current: SourceHighlight, number: number) => current !== null && current.number === number;
export const highlightAnnouncement = (number: number, name: string) => `Fonte ${number} destacada na lista de fontes: ${name}`;

/** Which sources a [N] can point to (1-based, within the list). */
export const citationTarget = (number: number, total: number): number | null => Number.isInteger(number) && number >= 1 && number <= total ? number : null;

/** Spreadsheet/slide chunks come as `Header: value | Header: value` lines; turn them into a table when they all do. */
export function parseRowTable(text: string): { headers: string[]; rows: string[][] } | null {
  const lines = text.split("\n").map((line) => line.trim()).filter(Boolean);
  if (lines.length === 0) return null;
  const parsed = lines.map((line) => line.split(" | ").map((cell) => { const match = /^([^:|]{1,60}): (.*)$/.exec(cell); return match ? { key: match[1].trim(), value: match[2] } : null; }));
  if (parsed.some((cells) => cells.length === 0 || cells.some((cell) => cell === null)) || !parsed.some((cells) => cells.length > 1)) return null;
  const headers: string[] = [];
  for (const cells of parsed) for (const cell of cells) if (cell && !headers.includes(cell.key)) headers.push(cell.key);
  if (headers.length > 24) return null;
  return { headers, rows: parsed.map((cells) => headers.map((header) => cells.find((cell) => cell?.key === header)?.value ?? "")) };
}

export type ViewerChunk = { id: string; position: number; page_number: number | null; text: string };
/** Groups consecutive chunks of the same page/slide so a slide cited by number is shown (and highlighted) as one unit. */
export function groupByPage(chunks: readonly ViewerChunk[]): { page: number | null; chunks: ViewerChunk[] }[] {
  const groups: { page: number | null; chunks: ViewerChunk[] }[] = [];
  for (const chunk of chunks) {
    const last = groups[groups.length - 1];
    if (last && last.page === chunk.page_number) last.chunks.push(chunk);
    else groups.push({ page: chunk.page_number, chunks: [chunk] });
  }
  return groups;
}

/** Splits the passage around the cited excerpt (ignoring a trailing ellipsis) so the evidence can be highlighted. */
export function splitHighlight(text: string, excerpt: string): [string, string, string] | null {
  const needle = excerpt.replace(/…$/, "").trim();
  if (needle.length < 8) return null;
  const at = text.toLowerCase().indexOf(needle.toLowerCase());
  return at < 0 ? null : [text.slice(0, at), text.slice(at, at + needle.length), text.slice(at + needle.length)];
}

const squash = (value: string) => value.replace(/\s+/g, " ").trim();

/**
 * Finds the cited excerpt inside the text-layer spans of a PDF page: returns the inclusive span range to mark.
 * Whitespace is normalised on both sides (PDF line breaks differ from the extracted chunk); a long excerpt falls back to its opening.
 */
export function locateInSpans(spanTexts: readonly string[], excerpt: string): { from: number; to: number } | null {
  const starts: number[] = [];
  let joined = "";
  spanTexts.forEach((text, index) => { const piece = squash(text); starts[index] = joined.length + (joined && piece ? 1 : 0); joined += (joined && piece ? " " : "") + piece; });
  const wanted = squash(excerpt.replace(/…$/, ""));
  for (const needle of [wanted, wanted.slice(0, 80), wanted.slice(0, 40), wanted.slice(0, 24)]) {
    const parts = splitHighlight(joined, needle);
    if (!parts) continue;
    const begin = parts[0].length;
    const end = begin + parts[1].length;
    let from = -1; let to = -1;
    spanTexts.forEach((text, index) => {
      const length = squash(text).length;
      if (length === 0) return;
      if (starts[index] + length > begin && starts[index] < end) { if (from < 0) from = index; to = index; }
    });
    if (from >= 0) return { from, to };
  }
  return null;
}
