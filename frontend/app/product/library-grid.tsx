"use client";

import { ChevronRight, ExternalLink, MessageSquare, File, FileSpreadsheet, FileText, Folder, Image as ImageIcon, LayoutGrid, List, MoreHorizontal, Presentation, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from "react";
import { FILE_KIND_LABEL, fileKind, withSpaceHeadings, type FileKind, type LibraryGridSize, type LibraryView } from "../library-view-logic";
import { SpaceBadges } from "./library-spaces";
import type { LibraryNode } from "./types-and-api";
import { LibraryIndexingBadge } from "./library-indexing-badge";
import { LibraryAccessBadge } from "./library-access-badge";
import { LoadingBlock, SkeletonLine, Spinner, staggerStyle } from "../ui";
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
      <button type="button" role="radio" aria-checked={view.mode === "list"} tabIndex={view.mode === "list" ? 0 : -1} aria-label="Lista" title="Lista" onClick={() => onChange({ ...view, mode: "list" })}><List size={16} aria-hidden="true" /><span>Lista</span></button>
      <button type="button" role="radio" aria-checked={view.mode === "grid"} tabIndex={view.mode === "grid" ? 0 : -1} aria-label="Grade" title="Grade" onClick={() => onChange({ ...view, mode: "grid" })}><LayoutGrid size={16} aria-hidden="true" /><span>Grade</span></button>
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
    {open && <div ref={menu} role="menu" aria-label={`Ações para ${name}`} className="library-card-menu" data-ready={pos ? "" : undefined} style={pos ? { top: pos.top, left: pos.left } : { top: 0, left: 0, visibility: "hidden" }} onKeyDown={keys}>
      {actions.map((action) => <button key={action.key} type="button" role="menuitem" disabled={action.disabled} data-danger={action.danger || undefined} onClick={() => { close(true); action.run(); }}>{action.icon}<span>{action.label}</span></button>)}
    </div>}
  </>;
}

export type LibraryGridProps = {
  items: LibraryNode[]; groupBySpace?: boolean; size: LibraryGridSize; loading: boolean; canManage: boolean;
  busyNodeId: string | null; busyFileId: string | null;
  onOpen: (item: LibraryNode) => void;
  onReprocessFile: (item: LibraryNode) => void; onRemoveFile: (item: LibraryNode) => void;
  onSyncFolder: (item: LibraryNode) => void; onRemoveFolder: (item: LibraryNode) => void;
  /** Biblioteca → Conversa: abre o chat com o item já mencionado. */
  onAsk?: (item: LibraryNode) => void;
  /** Item destacado pela ponte Conversa → Biblioteca. */
  focusId?: string | null;
};

/** Placeholder com a forma real dos cards/linhas enquanto a biblioteca carrega (skeleton, não texto cru). */
export function LibraryLoadingSkeleton({ view, label = "Carregando arquivos…" }: { view: LibraryView; label?: string }) {
  if (view.mode === "list") return <LoadingBlock label={label}><ul aria-hidden="true" className="library-skeleton-list">{Array.from({ length: 8 }, (_, i) => <li key={i} className="library-skeleton-row"><span className="mo-skeleton" data-shape="circle" style={{ width: 32, height: 32 }} /><SkeletonLine width={`${[52, 38, 64, 45, 58, 34, 49, 61][i]}%`} /><SkeletonLine width="12%" /></li>)}</ul></LoadingBlock>;
  return <LoadingBlock label={label}><div aria-hidden="true" data-size={view.size} className="library-grid library-skeleton-grid">{Array.from({ length: view.size === "s" ? 12 : view.size === "m" ? 8 : 6 }, (_, i) => <div key={i} className="library-card library-skeleton-card"><span className="mo-skeleton library-skeleton-icon" /><SkeletonLine width={`${[78, 62, 70, 55][i % 4]}%`} /><SkeletonLine width="34%" /></div>)}</div></LoadingBlock>;
}

export function LibraryGrid({ items, groupBySpace = false, size, loading, canManage, busyNodeId, busyFileId, onOpen, onReprocessFile, onRemoveFile, onSyncFolder, onRemoveFolder, onAsk, focusId }: LibraryGridProps) {
  return <ul key={size} aria-busy={loading} aria-label="Arquivos e pastas" data-size={size} className={`library-grid${loading ? " is-loading" : ""}`}>
    {withSpaceHeadings(items, groupBySpace).map((entry, index) => {
      if (entry.type === "heading") return <li key={entry.key} className="library-group-heading">{entry.label}<span>{entry.count} {entry.count === 1 ? "item" : "itens"}</span></li>;
      const item = entry.item;
      const isFolder = item.kind !== "file";
      const indexed = !isFolder && (item.workspace_documents?.length ?? 0) > 0;
      const kind = fileKind(item.name, item.mime_type); const Icon = KIND_ICON[kind];
      const canAsk = !!onAsk && item.kind !== "source" && (isFolder || indexed);
      const askLabel = isFolder ? "Perguntar sobre esta pasta" : "Perguntar sobre este arquivo";
      const actions: MenuAction[] = [];
      if (canAsk) actions.push({ key: "ask", label: askLabel, icon: <MessageSquare size={16} aria-hidden="true" />, run: () => onAsk(item) });
      if (!isFolder && item.source_url) actions.push({ key: "open", label: "Abrir no provedor", icon: <ExternalLink size={16} aria-hidden="true" />, run: () => onOpen(item) });
      if (canManage && !isFolder && indexed) {
        actions.push({ key: "reprocess", label: "Reprocessar arquivo", icon: <RefreshCw size={16} aria-hidden="true" />, disabled: busyFileId !== null, run: () => onReprocessFile(item) });
        actions.push({ key: "remove", label: "Remover do índice", icon: <Trash2 size={16} aria-hidden="true" />, danger: true, disabled: busyFileId !== null, run: () => onRemoveFile(item) });
      }
      if (item.kind === "folder") actions.push({ key: "sync", label: "Sincronizar alterações", icon: <RefreshCw size={16} aria-hidden="true" />, disabled: busyNodeId !== null, run: () => onSyncFolder(item) });
      if (item.kind === "folder" && canManage) actions.push({ key: "remove-folder", label: "Remover pasta", icon: <Trash2 size={16} aria-hidden="true" />, danger: true, disabled: busyNodeId !== null, run: () => onRemoveFolder(item) });
      const label = isFolder ? (item.kind === "source" ? "Integração" : "Pasta") : FILE_KIND_LABEL[kind];
      const working = busyNodeId === item.id || busyFileId === item.id;
      return <li key={entry.key} className="library-card mo-stagger-item" data-step={size === "s" ? undefined : "md"} style={staggerStyle(index) as CSSProperties} data-kind={isFolder ? "folder" : kind} data-busy={working || undefined} data-node-id={item.id} data-focus={focusId === item.id ? "true" : undefined}>
        <button type="button" className="library-card-main" onClick={() => onOpen(item)} title={item.name} aria-label={isFolder ? `Abrir pasta ${item.name}` : item.source_url ? `${item.name} — abrir no provedor` : item.name}>
          <span className="library-card-icon" aria-hidden="true">{isFolder ? <Folder size={size === "s" ? 24 : size === "m" ? 30 : 38} /> : <Icon size={size === "s" ? 24 : size === "m" ? 30 : 38} />}{working && <span className="library-card-spin"><Spinner size={12} /></span>}</span>
          <span className="library-card-name">{item.name}</span>
          <span className="library-card-meta"><span>{label}</span>{isFolder && <ChevronRight size={12} aria-hidden="true" />}</span>
          <SpaceBadges spaces={item.spaces} max={1} />
        </button>
        {!isFolder && <div className="library-card-indexing"><LibraryIndexingBadge item={item} /></div>}
        {item.access_state && <div className="library-card-indexing"><LibraryAccessBadge item={item} /></div>}
        {canAsk && <button type="button" className="library-card-ask" onClick={() => onAsk(item)} title={askLabel} aria-label={`${askLabel}: ${item.name}`}><MessageSquare size={16} aria-hidden="true" /></button>}
        <CardMenu name={item.name} actions={actions} />
      </li>;
    })}
  </ul>;
}

