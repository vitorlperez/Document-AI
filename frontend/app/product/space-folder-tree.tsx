"use client";

import { useEffect, useRef, useState } from "react";
import { ChevronRight, Folder as FolderIcon, Search } from "lucide-react";
import { AutomationSourceIcon } from "./automation-folder-picker";
import type { NodeGrant, TreeFolder } from "./spaces-api";
import { filterGroups, groupState, type CheckState, type FolderGroup } from "./spaces-folder-tree";
import { nodeState, scopeState, selectedFoldersLabel, selectionSize, toggleScope, type Chains, type NodeContext, type Selection } from "./spaces-node-selection";
import { LoadingBlock, SkeletonText } from "../ui";

function TriCheckbox({ state, label, disabled, onChange }: { state: CheckState; label: string; disabled?: boolean; onChange: () => void }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (ref.current) ref.current.indeterminate = state === "indeterminate"; }, [state]);
  return <input ref={ref} type="checkbox" aria-label={label} checked={state === "checked"} disabled={disabled} onChange={onChange} className="size-4 shrink-0 accent-[var(--primary)]" aria-checked={state === "indeterminate" ? "mixed" : state === "checked"} />;
}

/** Tudo o que a árvore precisa para entrar nas pastas: raízes por sincronização, subpastas sob demanda e o clique em uma pasta. */
export type FolderTreeNodes = {
  roots: Record<string, TreeFolder[]>;
  children: Record<string, TreeFolder[] | "error">;
  chains: Chains;
  load: (nodeId: string) => void;
  toggle: (ctx: NodeContext) => void;
};

function FolderNode({ folder, ctx, depth, selection, nodes, spaceName }: { folder: TreeFolder; ctx: NodeContext; depth: number; selection: Selection; nodes: FolderTreeNodes; spaceName: string }) {
  const [open, setOpen] = useState(false);
  const state = nodeState(ctx, selection, nodes.chains);
  const kids = nodes.children[folder.id];
  const { load } = nodes;
  useEffect(() => { if (open && kids === undefined) load(folder.id); }, [open, kids, load, folder.id]);
  const pad = { paddingLeft: `${depth * 20 + 12}px` };
  return <li role="treeitem" aria-expanded={folder.has_children ? open : undefined} aria-selected={state === "checked"}>
    <div className="flex min-h-11 items-center gap-1 pr-3" style={pad}>
      {folder.has_children
        ? <button type="button" aria-label={`${open ? "Recolher" : "Abrir"} ${folder.name}`} className="grid size-11 shrink-0 place-items-center rounded-lg focus-visible:outline-2 focus-visible:outline-primary" onClick={() => setOpen((value) => !value)}>
          <ChevronRight aria-hidden="true" size={16} className={`transition-transform duration-[var(--motion-base)] ease-[var(--ease-out)] ${open ? "rotate-90" : ""}`} /></button>
        : <span className="size-11 shrink-0" aria-hidden="true" />}
      <label className="flex min-h-11 min-w-0 flex-1 items-center gap-3">
        <TriCheckbox state={state} label={`${folder.name} — ${spaceName}`} onChange={() => nodes.toggle(ctx)} />
        <FolderIcon aria-hidden="true" size={16} className="shrink-0 text-muted-foreground" /><span className="min-w-0 break-words text-sm">{folder.name}</span>
      </label>
    </div>
    {open && folder.has_children && (kids === "error"
      ? <p role="alert" className="text-sm text-rose-700" style={{ paddingLeft: `${(depth + 1) * 20 + 44}px` }}>Não foi possível abrir esta pasta. <button type="button" className="underline" onClick={() => nodes.load(folder.id)}>Tentar novamente</button></p>
      : kids === undefined
        ? <LoadingBlock label="Carregando…" className="py-1"><div style={{ paddingLeft: `${(depth + 1) * 20 + 44}px` }}><SkeletonText lines={2} /></div></LoadingBlock>
        : kids.length === 0 ? <p className="text-sm text-muted-foreground" style={{ paddingLeft: `${(depth + 1) * 20 + 44}px` }}>Sem subpastas.</p>
          : <ul role="group">{kids.map((child) => <FolderNode key={child.id} folder={child} ctx={{ scopeId: ctx.scopeId, path: [...ctx.path, child.id] }} depth={depth + 1} selection={selection} nodes={nodes} spaceName={spaceName} />)}</ul>)}
  </li>;
}

/**
 * Árvore de pastas por ferramenta/conexão → sincronização → pastas da biblioteca (qualquer profundidade). Marcar a sincronização
 * concede ela inteira; entrar nela e marcar uma subpasta concede só aquela pasta com tudo abaixo (indeterminado nos ancestrais).
 * Sem `onChange` é somente leitura: lista as sincronizações recebidas e as pastas já concedidas.
 */
export function SpaceFolderTree({ groups, selection, onChange, nodes, grants = [], spaceId, spaceName }: { groups: FolderGroup[]; selection: Selection; onChange?: (next: Selection) => void; nodes?: FolderTreeNodes; grants?: NodeGrant[]; spaceId: string; spaceName: string }) {
  const [term, setTerm] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [openScopes, setOpenScopes] = useState<Set<string>>(new Set());
  const visible = filterGroups(groups, term);
  const editable = Boolean(onChange);
  const total = groups.reduce((sum, group) => sum + group.folders.length, 0) + grants.length;
  const rootIds = (scopeId: string) => (nodes?.roots[scopeId] ?? []).map((root) => root.id);
  const groupChecked = (group: FolderGroup): CheckState => {
    const states = group.folders.map((folder) => scopeState(folder.id, rootIds(folder.id), selection, nodes?.chains ?? new Map()));
    return states.every((value) => value === "checked") ? "checked" : states.every((value) => value === "unchecked") ? "unchecked" : "indeterminate";
  };
  const toggleWholeGroup = (group: FolderGroup) => {
    const all = group.folders.every((folder) => selection.scopes.has(folder.id));
    const scopes = new Set(selection.scopes);
    for (const folder of group.folders) { if (all) scopes.delete(folder.id); else scopes.add(folder.id); }
    onChange?.({ scopes, nodes: selection.nodes });
  };
  return <div>
    <div className="flex flex-wrap items-center gap-3">
      <label className="relative min-w-0 flex-1 basis-56">
        <span className="sr-only">Buscar pasta ou ferramenta</span>
        <Search aria-hidden="true" size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
        <input type="search" autoComplete="off" value={term} onChange={(event) => setTerm(event.target.value)} placeholder="Buscar pasta, ferramenta ou conta" className="min-h-11 w-full rounded-lg border border-line bg-paper py-2 pl-9 pr-3 text-sm focus-visible:outline-2 focus-visible:outline-primary" />
      </label>
      <p role="status" aria-live="polite" className="text-sm font-semibold">{editable ? selectedFoldersLabel(selectionSize(selection)) : `${total} ${total === 1 ? "pasta" : "pastas"}`}</p>
    </div>
    {visible.length === 0
      ? (!editable && grants.length > 0 && !term.trim() ? null : <p className="mt-4 text-sm text-muted-foreground">{term.trim() ? `Nenhuma pasta encontrada para “${term.trim()}”.` : "Nenhuma pasta neste Espaço."}</p>)
      : <ul role="tree" aria-label="Pastas por ferramenta" className="mt-3 space-y-3">{visible.map((group) => {
        const state = editable && nodes ? groupChecked(group) : groupState(group, selection.scopes);
        const open = !collapsed.has(group.key) || Boolean(term.trim());
        const chosen = group.folders.filter((folder) => selection.scopes.has(folder.id)).length;
        return <li key={group.key} role="treeitem" aria-expanded={open} aria-selected={state === "checked"} className="overflow-hidden rounded-lg border border-line-soft">
          <div className="flex min-h-12 items-center gap-1 bg-sage/60 pr-3">
            <button type="button" aria-label={`${open ? "Recolher" : "Expandir"} ${group.label}${group.account ? ` ${group.account}` : ""}`} className="grid size-11 shrink-0 place-items-center rounded-lg focus-visible:outline-2 focus-visible:outline-primary" onClick={() => setCollapsed((current) => { const next = new Set(current); if (!next.delete(group.key)) next.add(group.key); return next; })}>
              <ChevronRight aria-hidden="true" size={16} className={`transition-transform duration-[var(--motion-base)] ease-[var(--ease-out)] ${open ? "rotate-90" : ""}`} />
            </button>
            <label className="flex min-h-11 min-w-0 flex-1 items-center gap-3">
              {editable && <TriCheckbox state={state} label={`Selecionar todas as pastas de ${group.label}${group.account ? ` (${group.account})` : ""}`} onChange={() => toggleWholeGroup(group)} />}
              <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-panel" aria-hidden="true"><AutomationSourceIcon node={{ name: group.label, source_provider: group.provider === "other" ? null : group.provider }} /></span>
              <span className="min-w-0"><b className="block truncate text-sm">{group.label}</b>{group.account && <span className="block truncate text-xs text-muted-foreground">{group.account}</span>}</span>
            </label>
            <span className="shrink-0 text-xs text-muted-foreground">{editable ? `${chosen} de ${group.folders.length}` : group.folders.length}</span>
          </div>
          {open && <ul role="group" className="divide-y divide-line-soft bg-panel">{group.folders.map((folder) => {
            const others = folder.spaces.filter((item) => item.id !== spaceId);
            const roots = nodes?.roots[folder.id] ?? [];
            const scopeOpen = openScopes.has(folder.id);
            const folderState: CheckState = editable && nodes ? scopeState(folder.id, rootIds(folder.id), selection, nodes.chains) : selection.scopes.has(folder.id) ? "checked" : "unchecked";
            const body = <><FolderIcon aria-hidden="true" size={16} className="shrink-0 text-muted-foreground" /><span className="min-w-0 break-words text-sm">{folder.name}</span></>;
            return <li key={folder.id} role="treeitem" aria-expanded={editable && roots.length ? scopeOpen : undefined} aria-selected={folderState === "checked"}>
              <div className="flex min-h-11 flex-wrap items-center gap-x-1 gap-y-1 py-1 pl-1 pr-3">
                {editable && roots.length > 0
                  ? <button type="button" aria-label={`${scopeOpen ? "Recolher" : "Abrir"} ${folder.name}`} className="grid size-11 shrink-0 place-items-center rounded-lg focus-visible:outline-2 focus-visible:outline-primary" onClick={() => setOpenScopes((current) => { const next = new Set(current); if (!next.delete(folder.id)) next.add(folder.id); return next; })}>
                    <ChevronRight aria-hidden="true" size={16} className={`transition-transform duration-[var(--motion-base)] ease-[var(--ease-out)] ${scopeOpen ? "rotate-90" : ""}`} /></button>
                  : <span className="size-11 shrink-0" aria-hidden="true" />}
                {editable
                  ? <label className="flex min-h-11 min-w-0 flex-1 basis-48 items-center gap-3"><TriCheckbox state={folderState} label={`${folder.name} — ${spaceName}`} onChange={() => onChange?.(toggleScope(folder.id, selection))} />{body}</label>
                  : <span className="flex min-h-11 min-w-0 flex-1 basis-48 items-center gap-3">{body}</span>}
                {others.length > 0
                  ? <span title={`Também em: ${others.map((item) => item.name).join(", ")}`} className="max-w-full truncate rounded-full bg-sage px-2 py-0.5 text-xs text-muted-foreground">Também em {others.length === 1 ? others[0].name : `${others.length} Espaços`}</span>
                  : editable && folder.spaces.length === 0 ? <span title="Nenhum Espaço concede esta pasta: ninguém a lê" className="rounded-full bg-sage px-2 py-0.5 text-xs text-muted-foreground">Sem Espaço</span> : null}
              </div>
              {editable && nodes && scopeOpen && roots.length > 0 && <ul role="group" className="border-t border-line-soft">{roots.map((root) => <FolderNode key={root.id} folder={root} ctx={{ scopeId: folder.id, path: [root.id] }} depth={1} selection={selection} nodes={nodes} spaceName={spaceName} />)}</ul>}
            </li>;
          })}</ul>}
        </li>;
      })}</ul>}
    {!editable && grants.length > 0 && <div className="mt-4">
      <p className="text-sm font-semibold">Subpastas compartilhadas</p>
      <ul aria-label="Subpastas compartilhadas" className="mt-2 divide-y divide-line-soft rounded-lg border border-line-soft bg-panel">{grants.map((grant) => <li key={`${grant.source_id}:${grant.node_id ?? grant.name}`} className="flex min-h-11 items-center gap-3 px-3 py-1">
        <FolderIcon aria-hidden="true" size={16} className="shrink-0 text-muted-foreground" /><span className="min-w-0 break-words text-sm">{grant.path ?? grant.name}</span></li>)}</ul>
    </div>}
  </div>;
}
