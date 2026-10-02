"use client";

import { HardDrive, PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { useRouter } from "next/navigation";
import { isActive, progressView } from "./sync-status-logic";
import { useCallback, useEffect, useState } from "react";
import { toolLabel } from "./question-scope";
import { ToolLogoSpinner, ToolProgressMini, type ToolSyncState } from "./sync-status";
import { ProviderMark, type LibraryNode } from "./product/types-and-api";
import "./tools-sidebar.css";

const STORAGE_KEY = "arquivio:tools-sidebar-collapsed";
const OPEN_BY_DEFAULT_MIN_WIDTH = 1280;

export type ToolSelection = { libraryNodeId: string; provider: string; name: string };

type ToolEntry = { key: string; libraryNodeId: string | null; provider: string; name: string; tool?: ToolSyncState };

/** Collapsed state: persisted choice wins; otherwise open ≥1280px and collapsed on 768–1279px. */
export function useToolsSidebarCollapsed() {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    let stored: string | null = null;
    try { stored = window.localStorage.getItem(STORAGE_KEY); } catch { /* storage unavailable */ }
    const next = stored === "1" ? true : stored === "0" ? false : window.innerWidth < OPEN_BY_DEFAULT_MIN_WIDTH;
    queueMicrotask(() => setCollapsed(next));
  }, []);
  const toggle = useCallback(() => {
    setCollapsed((current) => {
      const next = !current;
      try { window.localStorage.setItem(STORAGE_KEY, next ? "1" : "0"); } catch { /* storage unavailable */ }
      return next;
    });
  }, []);
  return { collapsed, toggle };
}

/** Tools with data: library roots ∪ tools currently syncing (so a freshly connected tool does not vanish). */
function buildEntries(roots: LibraryNode[], tools: ToolSyncState[]): ToolEntry[] {
  const entries: ToolEntry[] = roots.filter((root) => root.kind === "source").map((root) => {
    const tool = tools.find((item) => item.libraryNodeId === root.id || item.sourceId === root.source_id);
    return { key: root.id, libraryNodeId: root.id, provider: root.source_provider ?? tool?.provider ?? "", name: root.name, tool };
  });
  const covered = new Set(entries.map((entry) => entry.tool?.sourceId).filter(Boolean));
  for (const tool of tools) {
    if (covered.has(tool.sourceId)) continue;
    if (tool.state === "idle") continue;
    entries.push({ key: `source:${tool.sourceId}`, libraryNodeId: tool.libraryNodeId, provider: tool.provider, name: toolLabel(tool.provider), tool });
  }
  return entries;
}

/** Tool logo; while the tool syncs, a spinner turns around it (rail, list and drawer alike). */
function Logo({ entry }: { entry: ToolEntry }) {
  const syncing = Boolean(entry.tool) && isActive(entry.tool!);
  return <span className="ts-logo" data-syncing={syncing || undefined}><ProviderMark provider={entry.provider} size="sm" />{syncing && <ToolLogoSpinner />}</span>;
}

/** Chat sidebar stays quiet: logo + name, plus a thin progress bar + short % only while syncing. Rich status lives in the Library. */
function RowText({ entry }: { entry: ToolEntry }) {
  const tool = entry.tool;
  return <span className="ts-text">
    <span className="ts-name">{entry.name}</span>
    {tool && isActive(tool) && <ToolProgressMini tool={tool} />}
  </span>;
}

export function ToolsSidebar({ orgId, canManage, collapsed, onToggle, onSelectTool, onAdd, variant = "rail", tools, libraryRoots, loading = false }: {
  orgId: string;
  canManage: boolean;
  collapsed: boolean;
  onToggle: () => void;
  onSelectTool: (tool: ToolSelection) => void;
  onAdd: () => void;
  /** "rail" = desktop sidebar (open/collapsed); "list" = plain list for the mobile drawer. */
  variant?: "rail" | "list";
  tools: ToolSyncState[];
  libraryRoots: LibraryNode[];
  /** First sync-status response not in yet: show a skeleton instead of the "no tools" empty state. */
  loading?: boolean;
}) {
  const router = useRouter();
  const entries = buildEntries(libraryRoots, tools);
  const pending = loading && entries.length === 0;
  const skeleton = (key: string) => <li key={key} className="ts-skeleton" aria-hidden="true"><span className="ts-skeleton-logo" /><span className="ts-skeleton-line" /></li>;
  const select = (entry: ToolEntry) => {
    if (entry.libraryNodeId) onSelectTool({ libraryNodeId: entry.libraryNodeId, provider: entry.provider, name: entry.name });
    else if (entry.tool) router.push(`/companies/${orgId}/library?syncing=${encodeURIComponent(entry.tool.sourceId)}`);
  };
  const description = (entry: ToolEntry) => entry.tool && isActive(entry.tool) ? `${entry.name}: ${progressView(entry.tool).text}` : undefined;
  const addButton = canManage && <button type="button" onClick={onAdd} className="ts-add" aria-label="Conectar ferramenta" title="Conectar ferramenta"><Plus size={18} aria-hidden="true" /></button>;

  if (variant === "list") {
    return <nav aria-label="Ferramentas" data-org={orgId} className="tools-list">
      <div className="ts-head"><p className="ts-title">Ferramentas</p>{addButton}</div>
      {pending ? <ul role="status" aria-label="Carregando ferramentas">{skeleton("a")}{skeleton("b")}</ul> : entries.length === 0 ? <p className="ts-empty"><HardDrive size={16} aria-hidden="true" />Nenhuma ferramenta com conteúdo ainda.</p> : <ul>{entries.map((entry) => <li key={entry.key}>
        <button type="button" className="ts-row" onClick={() => select(entry)} title={description(entry)} aria-describedby={description(entry) ? `ts-issue-${variant}-${entry.key}` : undefined}>
          <Logo entry={entry} />
          <RowText entry={entry} />
        </button>
        {description(entry) && <span id={`ts-issue-${variant}-${entry.key}`} className="sr-only">{description(entry)}</span>}
      </li>)}</ul>}
    </nav>;
  }

  const toggleLabel = collapsed ? "Expandir barra de ferramentas" : "Recolher barra de ferramentas";
  return <aside id="library-sources" data-tour="tool-sidebar" aria-label="Ferramentas" data-org={orgId} data-collapsed={collapsed ? "true" : "false"} className="tools-sidebar sources-panel">
    <div className="ts-head">
      {!collapsed && <p className="ts-title">Ferramentas</p>}
      {!collapsed && addButton}
      <button type="button" onClick={onToggle} className="ts-toggle" aria-expanded={!collapsed} aria-controls="tools-sidebar-list" aria-label={toggleLabel} title={toggleLabel}>{collapsed ? <PanelLeftOpen size={18} aria-hidden="true" /> : <PanelLeftClose size={18} aria-hidden="true" />}</button>
    </div>
    <ul id="tools-sidebar-list" className="ts-items">
      {pending && <li className="sr-only" role="status">Carregando ferramentas…</li>}
      {pending && (collapsed ? [<li key="a" className="ts-skeleton ts-skeleton-rail" aria-hidden="true"><span className="ts-skeleton-logo" /></li>] : [skeleton("a"), skeleton("b")])}
      {!pending && entries.length === 0 && !collapsed && <li className="ts-empty"><HardDrive size={16} aria-hidden="true" />Nenhuma ferramenta com conteúdo ainda.</li>}
      {entries.map((entry) => {
        const syncing = entry.tool?.state === "queued" || entry.tool?.state === "syncing";
        return <li key={entry.key}>
          <button type="button" className={collapsed ? "ts-icon" : "ts-row"} onClick={() => select(entry)} aria-describedby={description(entry) ? `ts-issue-${variant}-${entry.key}` : undefined} aria-label={collapsed ? `${entry.name}${syncing ? ", sincronizando" : ""}` : undefined} title={description(entry) ?? (collapsed ? entry.name : undefined)}>
            <Logo entry={entry} />
            {!collapsed && <RowText entry={entry} />}
          </button>
          {description(entry) && <span id={`ts-issue-${variant}-${entry.key}`} className="sr-only">{description(entry)}</span>}
        </li>;
      })}
    </ul>
    {collapsed && addButton && <div className="ts-foot">{addButton}</div>}
  </aside>;
}
