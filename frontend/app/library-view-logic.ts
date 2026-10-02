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
