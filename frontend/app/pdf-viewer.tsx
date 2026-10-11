"use client";

import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut } from "lucide-react";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";
import { locateInSpans, renderFailureCode } from "./file-viewer-logic";
// `?url` makes the bundler emit the worker as an asset and hand back its real served URL. resolving a package file relative to the
// module URL is NOT safe here: the production build rewrote it to `file:///ROOT/...`, which browsers refuse to load, so every PDF failed.
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "pdfjs-dist/web/pdf_viewer.css";
import "./pdf-viewer.css";

const ZOOM_STEPS = [0.6, 0.8, 1, 1.25, 1.5, 2, 2.5];

/** pdf.js is loaded here, on demand, so the chat bundle never carries it. */
async function loadPdfjs() {
  const pdfjs = await import("pdfjs-dist");
  if (!pdfjs.GlobalWorkerOptions.workerSrc) pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
  return pdfjs;
}

/** Single-page PDF reader: opens on the cited page, marks the cited passage through the text layer, basic page and zoom controls. */
export function PdfViewer({ blob, page, excerpt, onFailed }: { blob: Blob; page: number | null; excerpt: string; onFailed: (code: string) => void }) {
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [current, setCurrent] = useState(page ?? 1);
  const [zoomIndex, setZoomIndex] = useState(2);
  const [width, setWidth] = useState(0);
  const [status, setStatus] = useState<"loading" | "ready" | "marked-missing">("loading");
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const textLayer = useRef<HTMLDivElement>(null);
  const failed = useRef(onFailed);
  useEffect(() => { failed.current = onFailed; }, [onFailed]);

  useEffect(() => {
    let cancelled = false;
    let document: PDFDocumentProxy | null = null;
    (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const task = pdfjs.getDocument({ data: new Uint8Array(await blob.arrayBuffer()), isEvalSupported: false, enableXfa: false });
        document = await task.promise;
        if (cancelled) { void document.destroy(); return; }
        setPdf(document);
        setCurrent(Math.min(Math.max(page ?? 1, 1), document.numPages));
      } catch (caught) { if (!cancelled) failed.current(renderFailureCode(caught)); }
    })();
    return () => { cancelled = true; if (document) void document.destroy(); };
  }, [blob, page]);

  useEffect(() => {
    const element = stage.current;
    if (!element) return;
    let timer = 0;
    const observer = new ResizeObserver(() => { window.clearTimeout(timer); timer = window.setTimeout(() => setWidth(element.clientWidth), 120); });
    observer.observe(element);
    setWidth(element.clientWidth);
    return () => { window.clearTimeout(timer); observer.disconnect(); };
  }, []);

  useEffect(() => {
    if (!pdf || width < 80 || !canvas.current || !textLayer.current) return;
    let cancelled = false;
    let renderTask: RenderTask | null = null;
    (async () => {
      try {
        const pdfjs = await loadPdfjs();
        const pdfPage = await pdf.getPage(current);
        const base = pdfPage.getViewport({ scale: 1 });
        const viewport = pdfPage.getViewport({ scale: ((width - 24) / base.width) * ZOOM_STEPS[zoomIndex] });
        const target = canvas.current;
        const layer = textLayer.current;
        if (cancelled || !target || !layer) return;
        const ratio = window.devicePixelRatio || 1;
        target.width = Math.floor(viewport.width * ratio);
        target.height = Math.floor(viewport.height * ratio);
        target.style.width = `${Math.floor(viewport.width)}px`;
        target.style.height = `${Math.floor(viewport.height)}px`;
        layer.replaceChildren();
        layer.style.width = target.style.width;
        layer.style.height = target.style.height;
        layer.style.setProperty("--scale-factor", String(viewport.scale));
        const context = target.getContext("2d");
        if (!context) throw new Error("canvas");
        renderTask = pdfPage.render({ canvasContext: context, viewport, transform: ratio === 1 ? undefined : [ratio, 0, 0, ratio, 0, 0] });
        const text = new pdfjs.TextLayer({ textContentSource: pdfPage.streamTextContent(), container: layer, viewport });
        await Promise.all([renderTask.promise, text.render()]);
        if (cancelled) return;
        let marked = false;
        if (page === current && excerpt) {
          const spans = text.textDivs;
          const range = locateInSpans(spans.map((span) => span.textContent ?? ""), excerpt);
          if (range) { for (let index = range.from; index <= range.to; index += 1) spans[index].classList.add("pdf-hit"); spans[range.from].scrollIntoView?.({ block: "center", behavior: "auto" }); marked = true; }
        }
        setStatus(page === current && excerpt && !marked ? "marked-missing" : "ready");
      } catch (caught) {
        const name = (caught as { name?: string } | null)?.name;
        if (!cancelled && name !== "RenderingCancelledException") failed.current(renderFailureCode(caught));
      }
    })();
    return () => { cancelled = true; renderTask?.cancel(); };
  }, [pdf, current, zoomIndex, width, page, excerpt]);

  const total = pdf?.numPages ?? 0;
  return <div className="pdf-viewer">
    <div className="pdf-toolbar" role="toolbar" aria-label="Navegação do PDF">
      <button type="button" onClick={() => setCurrent((value) => Math.max(1, value - 1))} disabled={!pdf || current <= 1} aria-label="Página anterior"><ChevronLeft size={16} aria-hidden="true" /></button>
      <span className="pdf-page-label" aria-live="polite">{pdf ? `Página ${current} de ${total}` : "Carregando…"}</span>
      <button type="button" onClick={() => setCurrent((value) => Math.min(total, value + 1))} disabled={!pdf || current >= total} aria-label="Próxima página"><ChevronRight size={16} aria-hidden="true" /></button>
      <span className="pdf-toolbar-gap" />
      <button type="button" onClick={() => setZoomIndex((value) => Math.max(0, value - 1))} disabled={zoomIndex === 0} aria-label="Diminuir zoom"><ZoomOut size={16} aria-hidden="true" /></button>
      <span className="pdf-zoom-label">{Math.round(ZOOM_STEPS[zoomIndex] * 100)}%</span>
      <button type="button" onClick={() => setZoomIndex((value) => Math.min(ZOOM_STEPS.length - 1, value + 1))} disabled={zoomIndex === ZOOM_STEPS.length - 1} aria-label="Aumentar zoom"><ZoomIn size={16} aria-hidden="true" /></button>
    </div>
    {status === "marked-missing" && <p className="pdf-note" role="status">Não encontramos o trecho exato nesta página; veja a aba Trecho.</p>}
    <div className="pdf-stage" ref={stage} tabIndex={0} aria-label="Conteúdo do PDF">
      <div className="pdf-page">
        <canvas ref={canvas} aria-hidden="true" />
        <div className="textLayer" ref={textLayer} />
      </div>
    </div>
  </div>;
}
