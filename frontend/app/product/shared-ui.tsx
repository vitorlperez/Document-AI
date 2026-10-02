"use client";

import { ChevronRight, PanelLeftClose, PanelLeftOpen, Plus, RefreshCw } from "lucide-react";
import { type LibraryNode } from "./types-and-api";

/** "Nova conversa" lives only in the chat top bar (the mobile shell has its own in the header). */
export function NewConversationButton({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return <button data-tour="new-conversation" type="button" onClick={onClick} disabled={disabled} className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-line bg-white px-3 text-xs font-medium text-ink hover:bg-sage focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:opacity-50"><Plus size={15} aria-hidden="true" />Nova conversa</button>;
}

export function LoadingIndicator({ label, className = "" }: { label: string; className?: string }) {
  return <span role="status" aria-live="polite" className={`inline-flex items-center gap-2 ${className}`}><RefreshCw size={16} className="shrink-0 motion-safe:animate-spin" aria-hidden="true" /><span>{label}</span></span>;
}

export function Pagination({ value, loading, onChange }: { value: { page: number; pages: number; total: number }; loading: boolean; onChange: (page: number) => void }) {
  return <nav aria-label="Paginação da biblioteca" className="mt-4 flex items-center justify-between gap-3 border-t border-line px-2 py-3 text-xs text-muted-foreground"><span>Página {value.page} de {value.pages} · {value.total} itens</span><div className="flex gap-1"><button disabled={loading || value.page <= 1} onClick={() => onChange(value.page - 1)} aria-label="Página anterior" className="rounded-lg border border-line bg-white px-2.5 py-2 disabled:opacity-40">←</button><button disabled={loading || value.page >= value.pages} onClick={() => onChange(value.page + 1)} aria-label="Próxima página" className="rounded-lg border border-line bg-white px-2.5 py-2 disabled:opacity-40">→</button></div></nav>;
}

export function LibrarySidebarHeader({ canManage, onConnect, onRefresh, collapsed = false, onToggle }: { canManage: boolean; onConnect: () => void; onRefresh: () => void; collapsed?: boolean; onToggle?: () => void }) {
  const toggleLabel = collapsed ? "Expandir barra de ferramentas" : "Recolher barra de ferramentas";
  return <div className="library-sidebar-head flex items-center justify-between px-4 pb-3 pt-4"><div className="library-sidebar-title"><p className="text-sm font-semibold text-ink">Biblioteca</p><p className="mt-0.5 text-xs text-muted-foreground">Arquivos e pastas sincronizados</p></div><div className="library-sidebar-actions flex items-center gap-1">{canManage && <button onClick={onConnect} className="library-sidebar-btn rounded-lg p-2 text-primary hover:bg-sage-selected" aria-label="Adicionar fonte" title="Adicionar fonte"><Plus size={17} /></button>}<button onClick={onRefresh} className="library-sidebar-btn rounded-lg p-2 text-muted-foreground hover:bg-sage-selected" aria-label="Atualizar biblioteca" title="Atualizar biblioteca"><RefreshCw size={15} /></button>{onToggle && <button type="button" onClick={onToggle} className="ts-toggle library-sidebar-toggle" aria-expanded={!collapsed} aria-controls="library-tool-list" aria-label={toggleLabel} title={toggleLabel}>{collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}</button>}</div></div>;
}

export function LibraryBreadcrumbs({ path, onOpenPath }: { path: LibraryNode[]; onOpenPath: (nodes: LibraryNode[]) => void }) {
  return <nav className="flex flex-wrap items-center gap-1 px-3 pb-3 text-xs" aria-label="Caminho das fontes"><button onClick={() => onOpenPath([])} className={`rounded-md px-2 py-1.5 ${path.length === 0 ? "bg-white font-semibold text-ink shadow-sm" : "text-primary hover:bg-sage"}`}>Biblioteca</button>{path.map((node, index) => <span key={node.id} className="flex items-center"><ChevronRight size={13} className="text-muted-foreground" /><button onClick={() => onOpenPath(path.slice(0, index + 1))} className={`max-w-24 truncate rounded-md px-1.5 py-1.5 ${index === path.length - 1 ? "bg-white font-semibold text-ink shadow-sm" : "text-primary hover:bg-sage"}`}>{node.name}</button></span>)}</nav>;
}
