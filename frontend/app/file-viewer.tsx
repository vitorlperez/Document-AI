"use client";

import { ArrowLeft, ExternalLink, FileText, X } from "lucide-react";
import { type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type RefObject, Suspense, lazy, useCallback, useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { REDUCED_MOTION_QUERY } from "./interface-motion";
import {
  CHAT_MIN_WIDTH, type DocumentView, VIEWER_MIN_WIDTH, clampViewerWidth, defaultViewerWidth, fallsBackToText, fileErrorMessage, groupByPage, httpFileErrorCode, parseRowTable,
  readStoredWidth, splitHighlight, storeWidth, viewerFor, widthAfterDrag, type ViewerChunk,
} from "./file-viewer-logic";
import { type EvidenceCitation } from "./source-reading";
import { API_BASE, ProviderMark, api, messageFor } from "./product/types-and-api";
import "./file-viewer.css";

// The renderers are fetched only when a file of that kind is actually opened.
const PdfViewer = lazy(() => import("./pdf-viewer").then((module) => ({ default: module.PdfViewer })));
const DocxViewer = lazy(() => import("./docx-viewer").then((module) => ({ default: module.DocxViewer })));
const viewerLoading = <p className="fv-status" role="status">Carregando visualizador…</p>;

export type ViewerCitation = EvidenceCitation & { source_provider?: string | null };
export type ViewerTarget = { citation: ViewerCitation; number: number };

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const list = window.matchMedia(query);
    const sync = () => setMatches(list.matches);
    sync();
    list.addEventListener("change", sync);
    return () => list.removeEventListener("change", sync);
  }, [query]);
  return matches;
}

class FileLoadError extends Error { constructor(public readonly code: string) { super(code); } }

async function fetchFileBlob(organizationId: string, documentId: string, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`${API_BASE}/organizations/${organizationId}/documents/${documentId}/file`, { credentials: "include", signal });
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    throw new FileLoadError(typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string" ? body.detail : httpFileErrorCode(response.status));
  }
  return response.blob();
}

type ViewState =
  | { phase: "loading" }
  | { phase: "pdf"; blob: Blob }
  | { phase: "docx"; blob: Blob }
  | { phase: "office"; url: string }
  | { phase: "text"; notice: string | null }
  | { phase: "error"; code: string };

/** "Visualizar": renders the original (PDF, Word) or the extracted text, falling back gracefully. Loads only when the viewer opens. */
function ViewTab({ organizationId, citation, onOpenTrecho }: { organizationId: string; citation: ViewerCitation; onOpenTrecho: () => void }) {
  const [state, setState] = useState<ViewState>({ phase: "loading" });
  const [view, setView] = useState<DocumentView | null>(null);
  const [simpleWord, setSimpleWord] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const meta = view ?? await api<DocumentView>(`/organizations/${organizationId}/documents/${citation.document_id}/view`, { signal: controller.signal });
        setView(meta);
        const kind = viewerFor(meta);
        if (kind === "text") { setState({ phase: "text", notice: null }); return; }
        if (kind === "docx" && meta.office_preview && !simpleWord) {
          const preview = await api<{ url: string | null }>(`/organizations/${organizationId}/documents/${citation.document_id}/preview`, { method: "POST", body: JSON.stringify({ page: citation.page_number }), signal: controller.signal }).catch(() => ({ url: null }));
          if (preview.url) { setState({ phase: "office", url: preview.url }); return; }
        }
        const blob = await fetchFileBlob(organizationId, citation.document_id, controller.signal);
        setState(kind === "pdf" ? { phase: "pdf", blob } : { phase: "docx", blob });
      } catch (caught) {
        if (controller.signal.aborted) return;
        const code = caught instanceof FileLoadError ? caught.code : caught instanceof Error && "status" in caught && typeof caught.status === "number" ? httpFileErrorCode(caught.status) : "network_error";
        console.warn("[file-viewer] could not load the file", { documentId: citation.document_id, code, caught });
        setState(fallsBackToText(code) ? { phase: "text", notice: fileErrorMessage(code) } : { phase: "error", code });
      }
    })();
    return () => controller.abort();
    // `view` is intentionally read once: the metadata is stable while this viewer instance lives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizationId, citation.document_id, citation.page_number, simpleWord]);
  const renderFailed = useCallback((code: string) => {
    console.warn("[file-viewer] could not render the original", { documentId: citation.document_id, code });
    setState({ phase: "text", notice: `${fileErrorMessage(code)} Mostrando o texto extraído.` });
  }, [citation.document_id]);
  if (state.phase === "loading") return <p className="fv-status" role="status">Carregando arquivo…</p>;
  if (state.phase === "error") return <div className="fv-status" role="alert"><p>{fileErrorMessage(state.code)}</p><div className="fv-actions"><button type="button" onClick={() => setState({ phase: "text", notice: null })}>Ver texto extraído</button><button type="button" onClick={onOpenTrecho}>Ver trecho citado</button></div></div>;
  if (state.phase === "pdf") return <Suspense fallback={viewerLoading}><PdfViewer blob={state.blob} page={citation.page_number} excerpt={citation.excerpt} onFailed={renderFailed} /></Suspense>;
  if (state.phase === "docx") return <Suspense fallback={viewerLoading}><DocxViewer blob={state.blob} onFailed={renderFailed} /></Suspense>;
  if (state.phase === "office") return <div className="fv-office">
    <iframe title={`Prévia de ${citation.document_name}`} src={state.url} sandbox="allow-scripts allow-same-origin allow-forms allow-popups" referrerPolicy="no-referrer" loading="lazy" />
    <p className="fv-office-note">Prévia do Office. Se não carregar, <button type="button" onClick={() => { setState({ phase: "loading" }); setSimpleWord(true); }}>ver versão simples</button>.</p>
  </div>;
  return <TextViewer organizationId={organizationId} citation={citation} notice={state.notice} slides={/presentation|powerpoint/i.test(view?.mime_type ?? "")} />;
}

type ChunkPage = { total: number; offset: number; has_more: boolean; chunks: ViewerChunk[] };

function ChunkBody({ text }: { text: string }) {
  const table = parseRowTable(text);
  if (table) return <div className="fv-table-wrap"><table><thead><tr>{table.headers.map((header) => <th key={header} scope="col">{header}</th>)}</tr></thead><tbody>{table.rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={column}>{cell}</td>)}</tr>)}</tbody></table></div>;
  return <>{text.split(/\n{2,}/).map((paragraph, index) => {
    const heading = /^(#{1,3})\s+(.*)$/.exec(paragraph.trim());
    return heading ? <h4 key={index} className="fv-heading">{heading[2]}</h4> : <p key={index}>{paragraph}</p>;
  })}</>;
}

/** Extracted text in reading order (spreadsheets as tables, slides by number), paginated; the cited passage is marked. No file is downloaded. */
function TextViewer({ organizationId, citation, notice, slides }: { organizationId: string; citation: ViewerCitation; notice: string | null; slides: boolean }) {
  const [pages, setPages] = useState<ChunkPage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const cited = useRef<HTMLElement | null>(null);
  const base = `/organizations/${organizationId}/documents/${citation.document_id}/chunks`;
  useEffect(() => {
    const controller = new AbortController();
    const around = citation.chunk_id ? `&around_chunk_id=${citation.chunk_id}` : "";
    api<ChunkPage>(`${base}?limit=40${around}`, { signal: controller.signal }).then((page) => setPages([page])).catch((caught) => { if (!controller.signal.aborted) setError(messageFor(caught)); });
    return () => controller.abort();
  }, [base, citation.chunk_id]);
  const landed = pages.length > 0;
  useEffect(() => {
    if (!landed) return;
    const reduced = window.matchMedia(REDUCED_MOTION_QUERY).matches;
    cited.current?.scrollIntoView?.({ block: "center", behavior: reduced ? "auto" : "smooth" });
  }, [landed]);
  async function more(direction: "next" | "previous") {
    const edge = direction === "next" ? pages[pages.length - 1] : pages[0];
    if (!edge) return;
    setLoadingMore(true);
    try {
      const offset = direction === "next" ? edge.offset + edge.chunks.length : Math.max(0, edge.offset - 40);
      const page = await api<ChunkPage>(`${base}?limit=40&offset=${offset}`);
      setPages((current) => direction === "next" ? [...current, page] : [page, ...current]);
    } catch (caught) { setError(messageFor(caught)); } finally { setLoadingMore(false); }
  }
  if (error && pages.length === 0) return <p className="fv-status" role="alert">{error}</p>;
  if (pages.length === 0) return <p className="fv-status" role="status">Carregando texto…</p>;
  const chunks = pages.flatMap((page) => page.chunks);
  const first = pages[0]; const last = pages[pages.length - 1];
  return <div className="fv-text">
    {notice && <p className="fv-notice" role="status">{notice}</p>}
    {first.offset > 0 && <button type="button" className="fv-more" disabled={loadingMore} onClick={() => { void more("previous"); }}>Mostrar trechos anteriores</button>}
    {groupByPage(chunks).map((group) => <section key={`${group.page}-${group.chunks[0].id}`} className="fv-group" aria-label={group.page != null ? `${slides ? "Slide" : "Página"} ${group.page}` : undefined}>
      {group.page != null && <h3 className="fv-page">{slides ? "Slide" : "Página"} {group.page}</h3>}
      {group.chunks.map((chunk) => {
        const isCited = chunk.id === citation.chunk_id;
        const parts = isCited ? splitHighlight(chunk.text, citation.excerpt) : null;
        return <div key={chunk.id} ref={isCited ? (element) => { cited.current = element; } : undefined} className={`fv-chunk${isCited ? " is-cited" : ""}`} aria-current={isCited ? "true" : undefined}>
          {parts ? <p>{parts[0]}<mark>{parts[1]}</mark>{parts[2]}</p> : <ChunkBody text={chunk.text} />}
        </div>;
      })}
    </section>)}
    {last.has_more && <button type="button" className="fv-more" disabled={loadingMore} onClick={() => { void more("next"); }}>Carregar mais</button>}
    {error && <p role="alert" className="fv-notice">{error}</p>}
  </div>;
}

type EvidencePassage = { text: string; page_number: number | null; source_url: string | null };

/** "Trecho": the cited passage highlighted, with its page. Fetched only when the tab is opened. */
function EvidenceTab({ organizationId, citation }: { organizationId: string; citation: ViewerCitation }) {
  const [passage, setPassage] = useState<EvidencePassage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!citation.chunk_id) return;
    let cancelled = false;
    void api<EvidencePassage>(`/organizations/${organizationId}/documents/${citation.document_id}/evidence?chunk_id=${citation.chunk_id}`)
      .then((result) => { if (!cancelled) setPassage(result); })
      .catch((caught) => { if (!cancelled) setError(messageFor(caught)); });
    return () => { cancelled = true; };
  }, [organizationId, citation.document_id, citation.chunk_id]);
  const text = passage?.text ?? citation.excerpt;
  const parts = splitHighlight(text, citation.excerpt);
  const page = passage?.page_number ?? citation.page_number;
  const loading = Boolean(citation.chunk_id) && !passage && !error;
  return <div className="fv-evidence">
    {page != null && <p className="fv-meta">Página {page}</p>}
    {loading ? <p role="status" className="fv-status">Carregando trecho…</p> : <p className="fv-passage">{parts ? <>{parts[0]}<mark>{parts[1]}</mark>{parts[2]}</> : text}</p>}
    {error && <p role="alert" className="fv-notice">Não foi possível carregar o trecho completo; mostrando o resumo da citação.</p>}
  </div>;
}

const TABS = [{ id: "view", label: "Visualizar" }, { id: "snippet", label: "Trecho" }] as const;
type TabId = typeof TABS[number]["id"];

export function FileViewerPanel({ organizationId, target, narrow, width, available, onResize, onResizeEnd, onClose }: {
  organizationId: string; target: ViewerTarget; narrow: boolean; width: number; available: () => number;
  onResize: (width: number) => void; onResizeEnd: (width: number) => void; onClose: () => void;
}) {
  const { citation, number } = target;
  const [tab, setTab] = useState<TabId>("view");
  const [visited, setVisited] = useState<Record<TabId, boolean>>({ view: true, snippet: false });
  const root = useRef<HTMLElement>(null);
  const ids = useId();
  const url = citation.source_url;
  const select = useCallback((next: TabId) => { setTab(next); setVisited((current) => ({ ...current, [next]: true })); }, []);
  useEffect(() => { root.current?.focus({ preventScroll: true }); }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      const active = document.activeElement;
      const typingElsewhere = active instanceof HTMLElement && !root.current?.contains(active) && (active.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(active.tagName));
      if (!typingElsewhere) onClose();
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  const tabKeys = (event: ReactKeyboardEvent) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next = TABS[(TABS.findIndex((item) => item.id === tab) + 1) % TABS.length].id;
    select(next);
    document.getElementById(`${ids}-tab-${next}`)?.focus();
  };
  const drag = useRef<{ x: number; width: number } | null>(null);
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => { event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, width }; document.body.classList.add("fv-resizing"); };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => { if (drag.current) onResize(widthAfterDrag(drag.current.width, drag.current.x, event.clientX, available())); };
  const finishDrag = (event: ReactPointerEvent<HTMLDivElement>) => { if (!drag.current) return; const final = widthAfterDrag(drag.current.width, drag.current.x, event.clientX, available()); drag.current = null; document.body.classList.remove("fv-resizing"); onResizeEnd(final); };
  const onSeparatorKey = (event: ReactKeyboardEvent) => {
    const step = event.shiftKey ? 80 : 24;
    const next = event.key === "ArrowLeft" ? width + step : event.key === "ArrowRight" ? width - step : event.key === "Home" ? VIEWER_MIN_WIDTH : event.key === "End" ? available() - CHAT_MIN_WIDTH : null;
    if (next === null) return;
    event.preventDefault();
    onResizeEnd(clampViewerWidth(next, available()));
  };
  const provider = citation.source_provider;
  return <aside ref={root} tabIndex={-1} role={narrow ? "dialog" : "complementary"} aria-modal={narrow ? true : undefined} aria-label={`Visualização do arquivo ${number}: ${citation.document_name}`} className="file-viewer" style={narrow ? undefined : { width }}>
    {!narrow && <div role="separator" tabIndex={0} aria-orientation="vertical" aria-label="Redimensionar visualização" aria-valuemin={VIEWER_MIN_WIDTH} aria-valuemax={Math.max(VIEWER_MIN_WIDTH, available() - CHAT_MIN_WIDTH)} aria-valuenow={width} className="fv-resizer" onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={finishDrag} onPointerCancel={finishDrag} onKeyDown={onSeparatorKey} />}
    <header className="fv-header">
      {narrow && <button type="button" className="fv-icon-button" onClick={onClose} aria-label="Voltar ao chat"><ArrowLeft size={18} aria-hidden="true" /></button>}
      <span className="fv-provider" aria-hidden="true">{provider ? <ProviderMark provider={provider} size="sm" /> : <FileText size={16} />}</span>
      <div className="fv-title"><p className="fv-kicker">Fonte {number}</p><h2 title={citation.document_name}>{citation.document_name}</h2></div>
      {url && <a href={url} target="_blank" rel="noopener noreferrer" className="fv-open"><ExternalLink size={14} aria-hidden="true" /><span>Abrir original</span></a>}
      {!narrow && <button type="button" className="fv-icon-button" onClick={onClose} aria-label="Fechar visualização"><X size={18} aria-hidden="true" /></button>}
    </header>
    <div className="fv-tabs" role="tablist" aria-label="Modo de leitura" onKeyDown={tabKeys}>
      {TABS.map((item) => <button key={item.id} id={`${ids}-tab-${item.id}`} type="button" role="tab" aria-selected={tab === item.id} aria-controls={`${ids}-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} onClick={() => select(item.id)}>{item.label}</button>)}
    </div>
    <div className="fv-body">
      {visited.view && <div id={`${ids}-panel-view`} role="tabpanel" aria-labelledby={`${ids}-tab-view`} hidden={tab !== "view"} className="fv-panel"><ViewTab organizationId={organizationId} citation={citation} onOpenTrecho={() => select("snippet")} /></div>}
      {visited.snippet && <div id={`${ids}-panel-snippet`} role="tabpanel" aria-labelledby={`${ids}-tab-snippet`} hidden={tab !== "snippet"} className="fv-panel"><EvidenceTab organizationId={organizationId} citation={citation} /></div>}
    </div>
  </aside>;
}

/**
 * Third column of the chat workspace (split view) on desktop, a full-screen sheet on narrow screens.
 * It owns width (remembered), the exit animation and the CSS variable the grid uses; the chat stays interactive beside it.
 */
export function FileViewerHost({ organizationId, target, panelsRef, onClose }: { organizationId: string; target: ViewerTarget | null; panelsRef: RefObject<HTMLElement | null>; onClose: () => void }) {
  const narrow = useMediaQuery("(max-width: 767px)");
  const [shown, setShown] = useState<ViewerTarget | null>(target);
  const [width, setWidth] = useState(0);
  const open = target !== null;
  const available = useCallback(() => {
    const panels = panelsRef.current;
    if (!panels) return 1000;
    const tools = panels.firstElementChild instanceof HTMLElement ? panels.firstElementChild.offsetWidth : 0;
    return panels.clientWidth - tools;
  }, [panelsRef]);
  // Keep the last target on screen while the exit animation runs (adjusting state during render, not in an effect).
  if (target && target !== shown) setShown(target);
  useEffect(() => {
    if (target) return;
    const reduced = window.matchMedia(REDUCED_MOTION_QUERY).matches;
    const timer = window.setTimeout(() => setShown(null), reduced ? 0 : 240);
    return () => window.clearTimeout(timer);
  }, [target]);
  useEffect(() => {
    if (!open) return;
    // Measured from the DOM (the grid's real width), which is exactly what effects are for.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setWidth((current) => clampViewerWidth(current || readStoredWidth() || defaultViewerWidth(available()), available()));
  }, [open, available]);
  useEffect(() => {
    const refit = () => setWidth((current) => (current ? clampViewerWidth(current, available()) : current));
    window.addEventListener("resize", refit);
    return () => window.removeEventListener("resize", refit);
  }, [available]);
  useEffect(() => {
    const panels = panelsRef.current;
    if (!panels) return;
    panels.style.setProperty("--file-viewer-col", open && !narrow && width ? `${width}px` : "0px");
    panels.classList.toggle("file-viewer-open", open && !narrow);
    return () => { panels.style.removeProperty("--file-viewer-col"); panels.classList.remove("file-viewer-open"); };
  }, [open, narrow, width, panelsRef]);
  useEffect(() => {
    if (!(open && narrow)) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [open, narrow]);
  const resizeEnd = useCallback((next: number) => { setWidth(next); storeWidth(next); }, []);
  if (!shown) return null;
  const slot = <div className="file-viewer-slot" data-state={open ? "open" : "closing"} data-narrow={narrow ? "true" : undefined}>
    <FileViewerPanel key={shown.citation.document_id + (shown.citation.chunk_id ?? "")} organizationId={organizationId} target={shown} narrow={narrow} width={width || VIEWER_MIN_WIDTH} available={available} onResize={setWidth} onResizeEnd={resizeEnd} onClose={onClose} />
  </div>;
  return narrow ? createPortal(slot, document.body) : slot;
}
