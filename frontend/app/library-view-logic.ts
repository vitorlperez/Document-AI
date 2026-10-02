export type LibraryViewMode = "list" | "grid";
export type LibraryGridSize = "s" | "m" | "l";
export type LibraryView = { mode: LibraryViewMode; size: LibraryGridSize };
export type FileKind = "pdf" | "doc" | "sheet" | "slides" | "image" | "generic";

export const LIBRARY_VIEW_KEY = "arquivio:library-view";
export const DEFAULT_LIBRARY_VIEW: LibraryView = { mode: "list", size: "m" };

const EXTENSIONS: Record<string, FileKind> = {
  pdf: "pdf",
  doc: "doc", docx: "doc", odt: "doc", rtf: "doc", txt: "doc", md: "doc", pages: "doc",
  xls: "sheet", xlsx: "sheet", xlsm: "sheet", csv: "sheet", ods: "sheet", tsv: "sheet", numbers: "sheet",
  ppt: "slides", pptx: "slides", odp: "slides", key: "slides",
  png: "image", jpg: "image", jpeg: "image", gif: "image", webp: "image", svg: "image", bmp: "image", heic: "image", tiff: "image",
};

/** Maps a file name and/or mime type to the icon family used by the grid cards. The extension wins over the mime type. */
export function fileKind(name: string | null | undefined, mime: string | null | undefined): FileKind {
  const dot = (name ?? "").lastIndexOf(".");
  const extension = dot >= 0 ? (name ?? "").slice(dot + 1).trim().toLowerCase() : "";
  if (extension && EXTENSIONS[extension]) return EXTENSIONS[extension];
  const type = (mime ?? "").toLowerCase();
  if (!type) return "generic";
  if (type === "application/pdf") return "pdf";
  if (type.startsWith("image/")) return "image";
  if (type.includes("spreadsheet") || type.includes("excel") || type === "text/csv" || type === "application/x-notion-database" || type === "application/x-notion-data_source") return "sheet";
  if (type.includes("presentation") || type.includes("powerpoint")) return "slides";
  if (type.includes("wordprocessing") || type.includes("msword") || type === "text/plain" || type === "text/markdown" || type === "application/rtf" || type.includes("opendocument.text")) return "doc";
  return "generic";
}

export const FILE_KIND_LABEL: Record<FileKind, string> = { pdf: "PDF", doc: "Documento", sheet: "Planilha", slides: "Apresentação", image: "Imagem", generic: "Arquivo" };

/** Validates a stored preference; anything unexpected falls back to the defaults field by field. */
export function parseLibraryView(raw: string | null | undefined): LibraryView {
  if (!raw) return { ...DEFAULT_LIBRARY_VIEW };
  try {
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== "object") return { ...DEFAULT_LIBRARY_VIEW };
    const { mode, size } = value as { mode?: unknown; size?: unknown };
    return {
      mode: mode === "grid" || mode === "list" ? mode : DEFAULT_LIBRARY_VIEW.mode,
      size: size === "s" || size === "m" || size === "l" ? size : DEFAULT_LIBRARY_VIEW.size,
    };
  } catch {
    return { ...DEFAULT_LIBRARY_VIEW };
  }
}

export const serializeLibraryView = (view: LibraryView) => JSON.stringify({ mode: view.mode, size: view.size });

export const LIBRARY_BATCH_SIZE = 50;
export type ProgressiveLibraryPage<T> = { items: T[]; page?: number; pages?: number };
export type LibraryLoadState<T> = { items: T[]; nextPage: number; hasMore: boolean; loading: boolean; error: unknown | null };

/** One in-flight batch per listing; reset invalidates even transports that ignore abort. */
export class LibraryPager<T extends { id: string }> {
  state: LibraryLoadState<T> = { items: [], nextPage: 1, hasMore: true, loading: false, error: null };
  private controller: AbortController | null = null;
  private generation = 0;
  private retryRefresh = false;
  private fetchPage: (page: number, signal: AbortSignal) => Promise<ProgressiveLibraryPage<T>>;
  private publish: (state: LibraryLoadState<T>) => void;

  constructor(fetchPage: (page: number, signal: AbortSignal) => Promise<ProgressiveLibraryPage<T>>, publish: (state: LibraryLoadState<T>) => void) {
    this.fetchPage = fetchPage;
    this.publish = publish;
  }

  reset() {
    this.generation += 1;
    this.controller?.abort();
    this.retryRefresh = false;
    this.state = { items: [], nextPage: 1, hasMore: true, loading: false, error: null };
    this.publish(this.state);
  }

  /** Refresh the loaded range atomically, keeping the visible list during synchronization. */
  async refresh() {
    if (this.state.loading) return;
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    const lastPage = Math.max(1, this.state.nextPage - 1);
    this.state = { ...this.state, loading: true, error: null };
    this.publish(this.state);
    const unique = new Map<string, T>();
    let page = 1;
    let hasMore = true;
    try {
      for (; page <= lastPage && hasMore; page += 1) {
        const result = await this.fetchPage(page, controller.signal);
        if (generation !== this.generation || controller.signal.aborted) return;
        for (const item of result.items) unique.set(item.id, item);
        hasMore = result.items.length > 0 && (typeof result.pages === "number" ? page < result.pages : result.items.length >= LIBRARY_BATCH_SIZE);
      }
      this.state = { items: [...unique.values()], nextPage: page, hasMore, loading: false, error: null };
      this.retryRefresh = false;
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted) return;
      this.retryRefresh = true;
      this.state = { ...this.state, loading: false, error };
    }
    this.publish(this.state);
  }

  async load() {
    if (this.retryRefresh) return this.refresh();
    if (this.state.loading || !this.state.hasMore) return;
    const generation = this.generation;
    const page = this.state.nextPage;
    const controller = new AbortController();
    this.controller = controller;
    this.state = { ...this.state, loading: true, error: null };
    this.publish(this.state);
    try {
      const result = await this.fetchPage(page, controller.signal);
      if (generation !== this.generation || controller.signal.aborted) return;
      const unique = new Map(this.state.items.map(item => [item.id, item]));
      for (const item of result.items) unique.set(item.id, item);
      this.state = { items: [...unique.values()], nextPage: page + 1, loading: false, error: null,
        hasMore: result.items.length > 0 && (typeof result.pages === "number" ? page < result.pages : result.items.length >= LIBRARY_BATCH_SIZE) };
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted) return;
      this.state = { ...this.state, loading: false, error };
    }
    this.publish(this.state);
  }
}
