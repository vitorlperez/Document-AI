"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronRight, Folder as FolderIcon, Search } from "lucide-react";
import { AutomationSourceIcon } from "./automation-folder-picker";
import { filterGroups, groupState, selectedCountLabel, toggleFolder, toggleGroup, type FolderGroup } from "./spaces-folder-tree";

function TriCheckbox({ state, label, disabled, onChange }: { state: "checked" | "unchecked" | "indeterminate"; label: string; disabled?: boolean; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = state === "indeterminate"; }, [state]);
  return <input ref={ref} type="checkbox" aria-label={label} checked={state === "checked"} disabled={disabled} onChange={onChange} className="size-4 shrink-0 accent-[var(--primary)]" aria-checked={state === "indeterminate" ? "mixed" : state === "checked"} />;
}

/**
 * Árvore de pastas agrupada por ferramenta/conexão (mesmo padrão do passo de pastas da automação): marcar a ferramenta marca
 * todas as pastas dela (indeterminado quando parcial). Sem `onChange` é somente leitura: só lista as pastas recebidas.
 */
export function SpaceFolderTree({ groups, selected, onChange, spaceId, spaceName }: { groups: FolderGroup[]; selected: ReadonlySet<string>; onChange?: (next: Set<string>) => void; spaceId: string; spaceName: string }) {
  const [term, setTerm] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const visible = filterGroups(groups, term);
  const editable = Boolean(onChange);
  const total = groups.reduce((sum, group) => sum + group.folders.length, 0);
  return <div>
    <div className="flex flex-wrap items-center gap-3">
      <label className="relative min-w-0 flex-1 basis-56">
        <span className="sr-only">Buscar pasta ou ferramenta</span>
        <Search aria-hidden="true" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input type="search" autoComplete="off" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Buscar pasta, ferramenta ou conta" className="min-h-11 w-full rounded-lg border border-line bg-paper py-2 pl-9 pr-3 text-sm focus-visible:outline-2 focus-visible:outline-primary" />
      </label>
      <p role="status" aria-live="polite" className="text-sm font-semibold">{editable ? <>{selectedCountLabel(selected.size)}<span className="font-normal text-muted-foreground"> de {total}</span></> : `${total} ${total === 1 ? "pasta" : "pastas"}`}</p>
    </div>
    {visible.length === 0
      ? <p className="mt-4 text-sm text-muted-foreground">{term.trim() ? `Nenhuma pasta encontrada para “${term.trim()}”.` : "Nenhuma pasta neste Espaço."}</p>
      : <ul role="tree" aria-label="Pastas por ferramenta" className="mt-3 space-y-3">{visible.map((group) => {
        const state = groupState(group, selected);
        const open = !collapsed.has(group.key) || Boolean(term.trim());
        const chosen = group.folders.filter((folder) => selected.has(folder.id)).length;
        return <li key={group.key} role="treeitem" aria-expanded={open} aria-selected={state === "checked"} className="overflow-hidden rounded-lg border border-line-soft">
          <div className="flex min-h-12 items-center gap-1 bg-sage/60 pr-3">
            <button type="button" aria-label={`${open ? "Recolher" : "Expandir"} ${group.label}${group.account ? ` ${group.account}` : ""}`} className="grid size-11 shrink-0 place-items-center rounded-lg focus-visible:outline-2 focus-visible:outline-primary" onClick={() => setCollapsed((current) => { const next = new Set(current); if (!next.delete(group.key)) next.add(group.key); return next; })}>
              <ChevronRight aria-hidden="true" size={16} className={`transition-transform duration-[var(--motion-base)] ease-[var(--ease-out)] ${open ? "rotate-90" : ""}`} />
            </button>
            <label className="flex min-h-11 min-w-0 flex-1 items-center gap-3">
              {editable && <TriCheckbox state={state} label={`Selecionar todas as pastas de ${group.label}${group.account ? ` (${group.account})` : ""}`} onChange={() => onChange?.(toggleGroup(group, selected))} />}
              <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-panel" aria-hidden="true"><AutomationSourceIcon node={{ name: group.label, source_provider: group.provider === "other" ? null : group.provider }} /></span>
              <span className="min-w-0"><b className="block truncate text-sm">{group.label}</b>{group.account && <span className="block truncate text-xs text-muted-foreground">{group.account}</span>}</span>
            </label>
            <span className="shrink-0 text-xs text-muted-foreground">{editable ? `${chosen} de ${group.folders.length}` : group.folders.length}</span>
          </div>
          {open && <ul role="group" className="divide-y divide-line-soft bg-panel">{group.folders.map((folder) => {
            const others = folder.spaces.filter((item) => item.id !== spaceId);
            const checked = selected.has(folder.id);
            const body = <><FolderIcon aria-hidden="true" size={16} className="shrink-0 text-muted-foreground" /><span className="min-w-0 break-words text-sm">{folder.name}</span></>;
            return <li key={folder.id} role="treeitem" aria-selected={checked} className="flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 py-1 pl-12 pr-3">
              {editable
                ? <label className="flex min-h-11 min-w-0 flex-1 basis-48 items-center gap-3"><TriCheckbox state={checked ? "checked" : "unchecked"} label={`${folder.name} — ${spaceName}`} onChange={() => onChange?.(toggleFolder(folder.id, selected))} />{body}</label>
                : <span className="flex min-h-11 min-w-0 flex-1 basis-48 items-center gap-3">{body}</span>}
              {others.length > 0
                ? <span title={`Também em: ${others.map((item) => item.name).join(", ")}`} className="max-w-full truncate rounded-full bg-sage px-2 py-0.5 text-xs text-muted-foreground">Também em {others.length === 1 ? others[0].name : `${others.length} Espaços`}</span>
                : editable && folder.spaces.length === 0 ? <span title="Nenhum Espaço concede esta pasta: ninguém a lê" className="rounded-full bg-sage px-2 py-0.5 text-xs text-muted-foreground">Sem Espaço</span> : null}
            </li>;
          })}</ul>}
        </li>;
      })}</ul>}
  </div>;
}
