"use client";

import { ArrowRight, File as FileIcon, Folder, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { filterDestinations, paletteDestinations } from "./account-helpers";
import { OPEN_PALETTE_EVENT, OPEN_SHORTCUTS_EVENT, isMac } from "./nav-events";
import { type Company, api, companyPath, libraryPath } from "./types-and-api";
import type { MentionCandidate } from "../mention-composer";
import "./command-palette.css";

type Entry = { id: string; label: string; detail?: string; kind: "page" | "file" | "folder"; path: string };

const isEditable = (target: EventTarget | null) => target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName));

/** ⌘K palette (destinations allowed for the role + file/folder search) and the global shortcuts. Mounted once by the shell. */
export function ShellShortcuts({ company, onNavigate }: { company: Company; onNavigate: (path: string) => void }) {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const navigate = useRef(onNavigate);
  useEffect(() => { navigate.current = onNavigate; }, [onNavigate]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const mod = event.metaKey || event.ctrlKey;
      const key = event.key.toLowerCase();
      if (mod && !event.shiftKey && !event.altKey && key === "k") { event.preventDefault(); setPaletteOpen((open) => !open); return; }
      if (mod && !event.shiftKey && !event.altKey && (key === "1" || key === "2")) { event.preventDefault(); navigate.current(key === "1" ? companyPath(company.id) : companyPath(company.id, "/library")); return; }
      if (mod && event.shiftKey && key === "o") {
        event.preventDefault();
        const button = document.querySelector<HTMLButtonElement>('[data-tour="new-conversation"]');
        if (button) button.click(); else navigate.current(companyPath(company.id));
        return;
      }
      if (event.key === "?" && !mod && !isEditable(event.target)) { event.preventDefault(); setHelpOpen(true); }
    };
    const openPalette = () => setPaletteOpen(true);
    const openHelp = () => setHelpOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_PALETTE_EVENT, openPalette);
    window.addEventListener(OPEN_SHORTCUTS_EVENT, openHelp);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener(OPEN_PALETTE_EVENT, openPalette); window.removeEventListener(OPEN_SHORTCUTS_EVENT, openHelp); };
  }, [company.id]);
  return <>
    {paletteOpen && <CommandPalette company={company} onClose={() => setPaletteOpen(false)} onNavigate={(path) => { setPaletteOpen(false); navigate.current(path); }} />}
    {helpOpen && <ShortcutsDialog onClose={() => setHelpOpen(false)} />}
  </>;
}

function useModalDialog(onClose: () => void) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const modal = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    modal?.showModal();
    return () => { modal?.close(); if (previous?.isConnected) previous.focus({ preventScroll: true }); };
  }, []);
  return { ref: dialog, onCancel: (event: React.SyntheticEvent) => { event.preventDefault(); onClose(); }, onClick: (event: React.MouseEvent) => { if (event.target === dialog.current) onClose(); } };
}

function CommandPalette({ company, onClose, onNavigate }: { company: Company; onClose: () => void; onNavigate: (path: string) => void }) {
  const modal = useModalDialog(onClose);
  const listId = useId();
  const [query, setQuery] = useState("");
  const [files, setFiles] = useState<MentionCandidate[]>([]);
  const [active, setActive] = useState(0);
  const destinations = useMemo(() => filterDestinations(paletteDestinations(company.role), query), [company.role, query]);
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) { queueMicrotask(() => setFiles([])); return; }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api<{ items: MentionCandidate[] }>(`/library/mention-candidates?organization_id=${company.id}&q=${encodeURIComponent(text)}&limit=8`, { signal: controller.signal })
        .then((result) => setFiles(result.items ?? []))
        .catch(() => { if (!controller.signal.aborted) setFiles([]); });
    }, 180);
    return () => { window.clearTimeout(timer); controller.abort(); };
  }, [company.id, query]);
  const entries: Entry[] = [
    ...destinations.map((item) => ({ id: `go-${item.key}`, label: item.label, detail: "Ir para", kind: "page" as const, path: companyPath(company.id, item.suffix) })),
    ...files.map((item) => ({ id: `node-${item.node_id}`, label: item.name, detail: item.path, kind: item.kind as "file" | "folder", path: libraryPath(company.id, item.node_id) })),
  ];
  const current = Math.min(active, Math.max(entries.length - 1, 0));
  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); if (entries.length) setActive((current + (event.key === "ArrowDown" ? 1 : -1) + entries.length) % entries.length); }
    else if (event.key === "Enter") { event.preventDefault(); const entry = entries[current]; if (entry) onNavigate(entry.path); }
  }
  return <dialog {...modal} aria-label="Paleta de comandos" className="command-palette" onKeyDown={onKeyDown}>
    <div className="command-palette-input"><Search size={16} aria-hidden="true" /><input autoFocus className="bg-transparent" role="combobox" aria-expanded="true" aria-controls={listId} aria-activedescendant={entries[current] ? `${listId}-${entries[current].id}` : undefined} aria-autocomplete="list" aria-label="Buscar arquivos, pastas ou páginas" placeholder="Ir para ou buscar arquivos…" value={query} onChange={(event) => { setQuery(event.target.value); setActive(0); }} /><kbd>Esc</kbd></div>
    <ul id={listId} role="listbox" aria-label="Resultados" className="command-palette-list">
      {entries.length === 0 && <li role="presentation" className="command-palette-empty">Nada encontrado.</li>}
      {entries.map((entry, index) => <li key={entry.id} id={`${listId}-${entry.id}`} role="option" aria-selected={index === current} onMouseMove={() => setActive(index)} onClick={() => onNavigate(entry.path)} className="command-palette-option">
        {entry.kind === "folder" ? <Folder size={16} aria-hidden="true" /> : entry.kind === "file" ? <FileIcon size={16} aria-hidden="true" /> : <ArrowRight size={16} aria-hidden="true" />}
        <span className="truncate">{entry.label}</span>{entry.detail && <small className="truncate">{entry.detail}</small>}
      </li>)}
    </ul>
  </dialog>;
}

function ShortcutsDialog({ onClose }: { onClose: () => void }) {
  const modal = useModalDialog(onClose);
  const mod = isMac() ? "⌘" : "Ctrl";
  const rows: [string, string][] = [[`${mod} K`, "Buscar arquivos ou ir para…"], [`${mod} 1`, "Conversa"], [`${mod} 2`, "Biblioteca"], [`${mod} ⇧ O`, "Nova conversa"], [`${mod} \\`, "Recolher ou mostrar o histórico"], ["?", "Mostrar esta lista"]];
  return <dialog {...modal} aria-label="Atalhos de teclado" className="command-palette shortcuts-dialog">
    <div className="shortcuts-head"><h2>Atalhos de teclado</h2><button type="button" autoFocus onClick={onClose} className="mo-interactive">Fechar</button></div>
    <dl>{rows.map(([keys, label]) => <div key={keys}><dt><kbd>{keys}</kbd></dt><dd>{label}</dd></div>)}</dl>
  </dialog>;
}
