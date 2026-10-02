"use client";

import { ChevronRight, ExternalLink, File, FileSpreadsheet, FileText, Folder, Image as ImageIcon, LayoutGrid, List, MoreHorizontal, Presentation, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { FILE_KIND_LABEL, fileKind, type FileKind, type LibraryGridSize, type LibraryView } from "../library-view-logic";
import type { LibraryNode } from "./types-and-api";
import "../library-view.css";

const SIZES: { value: LibraryGridSize; label: string; name: string }[] = [{ value: "s", label: "P", name: "Pequeno" }, { value: "m", label: "M", name: "Médio" }, { value: "l", label: "G", name: "Grande" }];
const KIND_ICON: Record<FileKind, typeof File> = { pdf: FileText, doc: FileText, sheet: FileSpreadsheet, slides: Presentation, image: ImageIcon, generic: File };

/** Segmented "Lista | Grade" control plus, in grid mode, the P/M/G size picker. */
export function LibraryViewControls({ view, onChange }: { view: LibraryView; onChange: (view: LibraryView) => void }) {
  const arrows = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp"].includes(event.key)) return;
    event.preventDefault();
    const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("button"));
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = buttons[(index + (event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : buttons.length - 1)) % buttons.length];
    next?.focus(); next?.click();
  };
  return <div className="library-view-controls">
    <div role="radiogroup" aria-label="Modo de visualização" className="library-seg" onKeyDown={arrows}>
      <button type="button" role="radio" aria-checked={view.mode === "list"} tabIndex={view.mode === "list" ? 0 : -1} aria-label="Lista" title="Lista" onClick={() => onChange({ ...view, mode: "list" })}><List size={15} aria-hidden="true" /><span>Lista</span></button>
      <button type="button" role="radio" aria-checked={view.mode === "grid"} tabIndex={view.mode === "grid" ? 0 : -1} aria-label="Grade" title="Grade" onClick={() => onChange({ ...view, mode: "grid" })}><LayoutGrid size={15} aria-hidden="true" /><span>Grade</span></button>
    </div>
    {view.mode === "grid" && <div role="radiogroup" aria-label="Tamanho dos itens da grade" className="library-seg library-seg-size" onKeyDown={arrows}>
      {SIZES.map((size) => <button key={size.value} type="button" role="radio" aria-checked={view.size === size.value} tabIndex={view.size === size.value ? 0 : -1} aria-label={`Tamanho ${size.name}`} title={`Tamanho ${size.name}`} onClick={() => onChange({ ...view, size: size.value })}>{size.label}</button>)}
    </div>}
  </div>;
}

type MenuAction = { key: string; label: string; icon: ReactNode; danger?: boolean; disabled?: boolean; run: () => void };

/** "⋯" button + keyboard-navigable menu (fixed positioning so the scrolling grid never clips it). Closes on Esc, outside click and scroll. */
function CardMenu({ name, actions }: { name: string; actions: MenuAction[] }) {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const close = useCallback((restore: boolean) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); }, []);
  useLayoutEffect(() => {
    if (!open || !trigger.current || !menu.current) return;
    const anchor = trigger.current.getBoundingClientRect(); const box = menu.current.getBoundingClientRect();
    const left = Math.max(8, Math.min(anchor.right - box.width, window.innerWidth - box.width - 8));
    const top = anchor.bottom + 4 + box.height > window.innerHeight - 8 ? Math.max(8, anchor.top - box.height - 4) : anchor.bottom + 4;
    setPos({ top, left });
  }, [open]);
  // Focus moves into the menu once it is positioned (a visibility:hidden element cannot take focus).
  useEffect(() => { if (open && pos) menu.current?.querySelector<HTMLElement>('[role="menuitem"]:not([disabled])')?.focus({ preventScroll: true }); }, [open, pos]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: globalThis.MouseEvent) => { const target = event.target as Node; if (!menu.current?.contains(target) && !trigger.current?.contains(target)) setOpen(false); };
    const dismiss = () => setOpen(false);
    document.addEventListener("mousedown", outside);
    window.addEventListener("scroll", dismiss, true); window.addEventListener("resize", dismiss);
    return () => { document.removeEventListener("mousedown", outside); window.removeEventListener("scroll", dismiss, true); window.removeEventListener("resize", dismiss); };
  }, [open]);
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]:not([disabled])') ?? []);
    const index = items.indexOf(document.activeElement as HTMLElement);
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
    else if (event.key === "Tab") close(false);
    else if (event.key === "ArrowDown") { event.preventDefault(); items[(index + 1) % items.length]?.focus(); }
    else if (event.key === "ArrowUp") { event.preventDefault(); items[(index - 1 + items.length) % items.length]?.focus(); }
    else if (event.key === "Home") { event.preventDefault(); items[0]?.focus(); }
    else if (event.key === "End") { event.preventDefault(); items.at(-1)?.focus(); }
  };
  if (actions.length === 0) return null;
  return <>
    <button ref={trigger} type="button" className="library-card-more" aria-haspopup="menu" aria-expanded={open} aria-label={`Ações para ${name}`} title="Mais ações" onClick={() => { setPos(null); setOpen((value) => !value); }} onKeyDown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); setPos(null); setOpen(true); } }}><MoreHorizontal size={16} aria-hidden="true" /></button>
    {open && <div ref={menu} role="menu" aria-label={`Ações para ${name}`} className="library-card-menu" style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0, visibility: "hidden" }} onKeyDown={keys}>
      {actions.map((action) => <button key={action.key} type="button" role="menuitem" disabled={action.disabled} data-danger={action.danger || undefined} onClick={() => { close(true); action.run(); }}>{action.icon}<span>{action.label}</span></button>)}
    </div>}
  </>;
}

export type LibraryGridProps = {
  items: LibraryNode[]; size: LibraryGridSize; loading: boolean; canManage: boolean;
  busyNodeId: string | null; busyFileId: string | null;
  onOpen: (item: LibraryNode) => void;
  onReprocessFile: (item: LibraryNode) => void; onRemoveFile: (item: LibraryNode) => void;
  onSyncFolder: (item: LibraryNode) => void; onRemoveFolder: (item: LibraryNode) => void;
};

export function LibraryGrid({ items, size, loading, canManage, busyNodeId, busyFileId, onOpen, onReprocessFile, onRemoveFile, onSyncFolder, onRemoveFolder }: LibraryGridProps) {
  return <ul aria-busy={loading} aria-label="Arquivos e pastas" data-size={size} className={`library-grid${loading ? " is-loading" : ""}`}>
    {items.map((item) => {
      const isFolder = item.kind !== "file";
      const indexed = !isFolder && (item.workspace_documents?.length ?? 0) > 0;
      const kind = fileKind(item.name, item.mime_type); const Icon = KIND_ICON[kind];
      const actions: MenuAction[] = [];
      if (!isFolder && item.source_url) actions.push({ key: "open", label: "Abrir no provedor", icon: <ExternalLink size={15} aria-hidden="true" />, run: () => onOpen(item) });
      if (canManage && !isFolder && indexed) {
        actions.push({ key: "reprocess", label: "Reprocessar arquivo", icon: <RefreshCw size={15} aria-hidden="true" />, disabled: busyFileId !== null, run: () => onReprocessFile(item) });
        actions.push({ key: "remove", label: "Remover do índice", icon: <Trash2 size={15} aria-hidden="true" />, danger: true, disabled: busyFileId !== null, run: () => onRemoveFile(item) });
      }
      if (item.kind === "folder") actions.push({ key: "sync", label: "Sincronizar alterações", icon: <RefreshCw size={15} aria-hidden="true" />, disabled: busyNodeId !== null, run: () => onSyncFolder(item) });
      if (item.kind === "folder" && canManage) actions.push({ key: "remove-folder", label: "Remover pasta", icon: <Trash2 size={15} aria-hidden="true" />, danger: true, disabled: busyNodeId !== null, run: () => onRemoveFolder(item) });
      const label = isFolder ? (item.kind === "source" ? "Integração" : "Pasta") : FILE_KIND_LABEL[kind];
      const working = busyNodeId === item.id || busyFileId === item.id;
      return <li key={item.id} className="library-card" data-kind={isFolder ? "folder" : kind} data-busy={working || undefined}>
        <button type="button" className="library-card-main" onClick={() => onOpen(item)} title={item.name} aria-label={isFolder ? `Abrir pasta ${item.name}` : item.source_url ? `${item.name} — abrir no provedor` : item.name}>
          <span className="library-card-icon" aria-hidden="true">{isFolder ? <Folder size={size === "s" ? 24 : size === "m" ? 30 : 38} /> : <Icon size={size === "s" ? 24 : size === "m" ? 30 : 38} />}{working && <RefreshCw size={12} className="library-card-spin" />}</span>
          <span className="library-card-name">{item.name}</span>
          <span className="library-card-meta"><span>{label}</span>{!isFolder && <span className="library-card-badge" data-indexed={indexed || undefined}>{indexed ? "Indexado" : "Não indexado"}</span>}{isFolder && <ChevronRight size={12} aria-hidden="true" />}</span>
        </button>
        <CardMenu name={item.name} actions={actions} />
      </li>;
    })}
  </ul>;
}


