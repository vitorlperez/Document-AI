"use client";

import { useEffect, useState } from "react";
import { ChevronRight, Folder as FolderIcon, X } from "lucide-react";
import type { ScopeFolder } from "./automations-model";
import { Enter, LoadingBlock, SkeletonList, SkeletonText, StaggerItem } from "../ui";

export const MAX_SCOPE_FOLDERS = 20;
type LibraryNode = { id: string; kind: "source" | "folder" | "file"; name: string };
type Candidate = { node_id: string; kind: "folder" | "file"; path: string };
const small = "min-h-11 rounded-lg border border-line px-3 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50";
const folderName = (path: string) => path.split("/").pop() || path;

export type LibraryFetch = <T>(path: string, signal: AbortSignal) => Promise<T>;
type Choose = { selected: ScopeFolder[]; onToggle: (folder: ScopeFolder) => void };

function TreeNode({ fetchJson, organizationId, node, path, depth, selected, onToggle }: Choose & { fetchJson: LibraryFetch; organizationId: string; node: LibraryNode; path: string; depth: number }) {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<LibraryNode[] | null>(null);
  const [error, setError] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    void Promise.resolve().then(async () => {
      try {
        const data = await fetchJson<{ items: LibraryNode[] }>(`/library/nodes/${node.id}/children?organization_id=${organizationId}&page_size=100`, controller.signal);
        if (!controller.signal.aborted) { setChildren(data.items.filter((item) => item.kind === "folder")); setError(false); }
      } catch { if (!controller.signal.aborted) setError(true); }
    });
    return () => controller.abort();
  }, [open, node.id, organizationId, revision, fetchJson]);
  const chosen = selected.some((item) => item.id === node.id);
  return <li role="treeitem" aria-expanded={open} aria-selected={chosen}>
    <div className="flex min-h-11 items-center gap-1" style={{ paddingLeft: depth * 16 }}>
      <button type="button" aria-label={`${open ? "Recolher" : "Expandir"} ${node.name}`} className="grid size-11 shrink-0 place-items-center rounded-lg focus-visible:outline-2 focus-visible:outline-primary" onClick={() => setOpen(!open)}><ChevronRight aria-hidden="true" size={16} className={`transition-transform duration-[var(--motion-base)] ease-[var(--ease-out)] ${open ? "rotate-90" : ""}`} /></button>
      {node.kind === "folder" ? <label className="flex min-h-11 min-w-0 flex-1 items-center gap-2"><input type="checkbox" checked={chosen} disabled={!chosen && selected.length >= MAX_SCOPE_FOLDERS} onChange={() => onToggle({ id: node.id, name: node.name, path })} /><FolderIcon aria-hidden="true" size={16} className="shrink-0" /><span className="min-w-0 break-words">{node.name}</span></label> : <span className="min-w-0 break-words font-semibold">{node.name}</span>}
    </div>
    {open && (error ? <p role="alert" className="text-sm text-rose-700" style={{ paddingLeft: depth * 16 + 44 }}>Não foi possível abrir esta pasta. <button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Tentar novamente</button></p> : children === null ? <LoadingBlock label="Carregando…" className="py-1"><div style={{ paddingLeft: depth * 16 + 44 }}><SkeletonText lines={2} /></div></LoadingBlock> : !children.length ? <p className="text-sm text-muted-foreground" style={{ paddingLeft: depth * 16 + 44 }}>Sem subpastas.</p> : <ul role="group" className="mo-enter" data-variant="slide">{children.map((child) => <TreeNode key={child.id} fetchJson={fetchJson} organizationId={organizationId} node={child} path={`${path}/${child.name}`} depth={depth + 1} selected={selected} onToggle={onToggle} />)}</ul>)}
  </li>;
}

export function AutomationFolderPicker({ fetchJson, organizationId, selected, onChange, legacyNames }: { fetchJson: LibraryFetch; organizationId: string; selected: ScopeFolder[]; onChange: (folders: ScopeFolder[]) => void; legacyNames: string[] }) {
  const [query, setQuery] = useState("");
  const [roots, setRoots] = useState<LibraryNode[] | null>(null);
  const [rootsError, setRootsError] = useState(false);
  const [results, setResults] = useState<Candidate[] | null>(null);
  const [searchError, setSearchError] = useState(false);
  const [revision, setRevision] = useState(0);
  const term = query.trim();
  const toggle = (folder: ScopeFolder) => onChange(selected.some((item) => item.id === folder.id) ? selected.filter((item) => item.id !== folder.id) : [...selected, folder]);
  useEffect(() => {
    const controller = new AbortController();
    void Promise.resolve().then(async () => {
      try { const data = await fetchJson<{ items: LibraryNode[] }>(`/library?organization_id=${organizationId}`, controller.signal); if (!controller.signal.aborted) { setRoots(data.items); setRootsError(false); } }
      catch { if (!controller.signal.aborted) setRootsError(true); }
    });
    return () => controller.abort();
  }, [organizationId, revision, fetchJson]);
  useEffect(() => {
    if (!term) return;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      void fetchJson<{ items: Candidate[] }>(`/library/mention-candidates?organization_id=${organizationId}&q=${encodeURIComponent(term)}&limit=50`, controller.signal)
        .then((data) => { if (!controller.signal.aborted) { setResults(data.items.filter((item) => item.kind === "folder")); setSearchError(false); } })
        .catch(() => { if (!controller.signal.aborted) setSearchError(true); });
    }, 250);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [term, organizationId, fetchJson]);
  return <div className="mt-4">
    <p className="text-sm text-muted-foreground">Escolha qualquer pasta indexada, em qualquer nível. A automação considera os arquivos dessa pasta e das subpastas.</p>
    {legacyNames.length > 0 && !selected.length && <p role="status" className="mt-3 rounded-lg bg-sage p-3 text-sm">Esta automação usa o escopo anterior (espaço inteiro: {legacyNames.join(", ")}). Escolha pastas abaixo para trocar; sem escolher, ela continua como está.</p>}
    <div aria-label="Pastas escolhidas" className="mt-3 flex flex-wrap gap-2">{selected.map((folder) => <Enter as="span" variant="pop" key={folder.id} className="flex min-h-11 max-w-full items-center gap-2 rounded-lg border border-line px-3 py-1 text-sm"><span className="min-w-0 break-words" title={folder.path}>{folder.path}</span><button type="button" aria-label={`Remover ${folder.name}`} className="grid size-8 shrink-0 place-items-center rounded-lg focus-visible:outline-2 focus-visible:outline-primary" onClick={() => toggle(folder)}><X aria-hidden="true" size={14} /></button></Enter>)}</div>
    {selected.length >= MAX_SCOPE_FOLDERS && <p className="mt-2 text-sm text-muted-foreground">Limite de {MAX_SCOPE_FOLDERS} pastas atingido.</p>}
    <label className="mt-4 block">Buscar pasta<input type="search" autoComplete="off" className="mt-2 min-h-11 w-full rounded-lg border border-line bg-panel px-3 py-2 focus-visible:outline-2 focus-visible:outline-primary" value={query} onChange={(event) => { setQuery(event.target.value); setResults(null); setSearchError(false); }} placeholder="Digite parte do nome ou do caminho" /></label>
    {term ? <div className="mt-3" aria-live="polite">{searchError ? <p role="alert" className="text-sm text-rose-700">Não foi possível buscar agora. Tente novamente.</p> : results === null ? <LoadingBlock label="Buscando…"><SkeletonList rows={3} avatar={false} /></LoadingBlock> : !results.length ? <p className="text-sm text-muted-foreground">Nenhuma pasta indexada encontrada para “{term}”.</p> : <ul className="space-y-2">{results.map((item, index) => <StaggerItem as="li" key={item.node_id} index={index}><label className="flex min-h-11 items-center gap-3 rounded-lg border border-line p-3"><input type="checkbox" checked={selected.some((folder) => folder.id === item.node_id)} disabled={!selected.some((folder) => folder.id === item.node_id) && selected.length >= MAX_SCOPE_FOLDERS} onChange={() => toggle({ id: item.node_id, name: folderName(item.path), path: item.path })} /><span className="min-w-0 break-words">{item.path}</span></label></StaggerItem>)}</ul>}</div>
      : <div className="mt-3">{rootsError ? <p role="alert" className="text-sm text-rose-700">Não foi possível carregar as pastas. <button type="button" className={small} onClick={() => setRevision((value) => value + 1)}>Tentar novamente</button></p> : roots === null ? <LoadingBlock label="Carregando pastas…"><SkeletonList rows={4} avatar={false} /></LoadingBlock> : !roots.length ? <p className="text-sm">Nenhuma pasta indexada disponível. Conecte e sincronize uma pasta em Integrações antes de criar a automação.</p> : <ul role="tree" aria-label="Pastas indexadas">{roots.map((root) => <TreeNode key={root.id} fetchJson={fetchJson} organizationId={organizationId} node={root} path={root.name} depth={0} selected={selected} onToggle={toggle} />)}</ul>}</div>}
  </div>;
}
