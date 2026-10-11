"use client";

import { useEffect, useRef } from "react";

/** Safe links only: the document is third-party content, so anything but http(s)/mailto is neutralised. */
function hardenLinks(root: HTMLElement) {
  root.querySelectorAll<HTMLAnchorElement>("a[href]").forEach((link) => {
    if (/^(https?:|mailto:|#)/i.test(link.getAttribute("href") ?? "")) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
    else link.removeAttribute("href");
  });
}

/** Word document rendered in the page by docx-preview (loaded on demand). Pages flow continuously: there is no jump to a page. */
export function DocxViewer({ blob, onFailed }: { blob: Blob; onFailed: () => void }) {
  const host = useRef<HTMLDivElement>(null);
  const failed = useRef(onFailed);
  useEffect(() => { failed.current = onFailed; }, [onFailed]);
  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let cancelled = false;
    (async () => {
      try {
        const { renderAsync } = await import("docx-preview");
        element.replaceChildren();
        await renderAsync(blob, element, undefined, { className: "docx", inWrapper: true, breakPages: false, ignoreLastRenderedPageBreak: true, renderHeaders: false, renderFooters: false, useBase64URL: true });
        if (cancelled) return;
        hardenLinks(element);
        const wrapper = element.querySelector<HTMLElement>(".docx-wrapper");
        const page = element.querySelector<HTMLElement>("section.docx");
        if (wrapper && page && page.offsetWidth > element.clientWidth) wrapper.style.zoom = String(Math.max(0.3, (element.clientWidth - 8) / page.offsetWidth));
      } catch { if (!cancelled) failed.current(); }
    })();
    return () => { cancelled = true; element.replaceChildren(); };
  }, [blob]);
  return <div className="docx-viewer" ref={host} tabIndex={0} aria-label="Conteúdo do documento" />;
}
