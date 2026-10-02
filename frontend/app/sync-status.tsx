"use client";

import { AlertTriangle, Check, LoaderCircle, Minus, RefreshCw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./product/types-and-api";
import {
  anyQueryable as hasQueryable, anySyncing as hasSyncing, bannerCopy, errorMessage, isActive, isIndeterminate, normalizeSyncItems,
  percent, pollInterval, progressView, shortLabel, stageLabel, summarize, summaryProgress, type SyncStatusItemDto, type ToolSyncState,
} from "./sync-status-logic";
import { providerLabel } from "./provider-labels";
import "./sync-status.css";

export type { ToolSyncState } from "./sync-status-logic";

export function useSyncStatus(orgId: string, opts?: { enabled?: boolean }): { tools: ToolSyncState[]; anySyncing: boolean; anyQueryable: boolean; loading: boolean; error: string | null; refresh(): void } {
  const enabled = opts?.enabled ?? true;
  const [tools, setTools] = useState<ToolSyncState[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const syncingRef = useRef(false);
  const refresh = useCallback(() => setTick((value) => value + 1), []);
  useEffect(() => {
    if (!enabled || !orgId) return;
    let cancelled = false; let timer: number | undefined; let controller: AbortController | null = null;
    const schedule = () => { if (!cancelled) timer = window.setTimeout(load, pollInterval(syncingRef.current)); };
    async function load() {
      if (cancelled) return;
      if (document.hidden) { schedule(); return; }
      controller?.abort(); controller = new AbortController();
      try {
        const data = await api<{ items: SyncStatusItemDto[] }>(`/library/sync-status?organization_id=${orgId}`, { cache: "no-store", signal: controller.signal });
        if (cancelled) return;
        const next = normalizeSyncItems(data.items);
        syncingRef.current = hasSyncing(next);
        setTools(next); setError(null);
      } catch (caught) {
        if (cancelled || controller?.signal.aborted) return;
        if (caught instanceof ApiError && caught.status === 404) { setTools([]); setError(null); }
        else setError("Não foi possível atualizar o andamento da sincronização.");
      } finally { if (!cancelled) { setLoaded(true); schedule(); } }
    }
    const onVisible = () => { if (!document.hidden) { window.clearTimeout(timer); void load(); } };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", onVisible);
    void load();
    return () => { cancelled = true; window.clearTimeout(timer); controller?.abort(); document.removeEventListener("visibilitychange", onVisible); window.removeEventListener("focus", onVisible); };
  }, [orgId, enabled, tick]);
  return { tools, anySyncing: hasSyncing(tools), anyQueryable: hasQueryable(tools), loading: enabled && Boolean(orgId) && !loaded, error, refresh };
}

export function ToolSyncBadge({ tool, compact = false, short = false }: { tool: ToolSyncState; compact?: boolean; short?: boolean }) {
  const active = isActive(tool);
  const problem = tool.state === "failed" || tool.state === "partial_failure";
  const view = progressView(tool);
  const label = `${providerLabel(tool.provider)}: ${active ? view.text : stageLabel(tool)}`;
  const icon = active ? <LoaderCircle size={14} className="sync-spin" aria-hidden="true" /> : problem ? <AlertTriangle size={14} aria-hidden="true" /> : tool.state === "ready" ? <Check size={14} aria-hidden="true" /> : null;
  if (!icon) return <span className="sync-badge sync-badge-idle" hidden={compact} />;
  if (compact) return <span className={`sync-badge sync-badge-compact sync-badge-${tool.state}`} title={label} role="img" aria-label={label}>{icon}</span>;
  // short = percent only (narrow lists); the step + count live in the tooltip and the aria label.
  const text = active ? (short ? (view.short ?? view.stage) : view.text) : tool.state === "ready" ? (tool.queryable ? "Pronto" : "Sem conteúdo") : tool.state === "failed" ? "Falhou" : "Parcial";
  return <span className={`sync-badge sync-badge-${tool.state}`} aria-label={label} title={label} data-indeterminate={isIndeterminate(tool) || undefined}>{icon}<span>{text}</span></span>;
}

/** Tiny status marker for dense lists: a coloured dot (or small % while syncing) with tooltip + aria-label. No pill, no spinner. */
export function ToolStatusDot({ tool }: { tool: ToolSyncState }) {
  const active = isActive(tool);
  const view = progressView(tool);
  const label = `${providerLabel(tool.provider)}: ${active ? view.text : stageLabel(tool)}`;
  if (tool.state === "idle") return null;
  if (active) return <span className="sync-dot-pct" title={label} role="img" aria-label={label}>{shortLabel(tool)}</span>;
  // Shape + colour: check (ready), minus (ready without chat content), triangle (partial), cross (failed).
  const kind = tool.state === "ready" && !tool.queryable ? "empty" : tool.state;
  const glyph = kind === "failed" ? <X size={10} strokeWidth={3} aria-hidden="true" /> : kind === "partial_failure" ? <AlertTriangle size={10} strokeWidth={2.5} aria-hidden="true" /> : kind === "empty" ? <Minus size={10} strokeWidth={3} aria-hidden="true" /> : <Check size={10} strokeWidth={3} aria-hidden="true" />;
  return <span className={`sync-dot sync-dot-${kind}`} title={label} role="img" aria-label={label}>{glyph}</span>;
}

/** Spinner drawn around a tool logo while it syncs. Reduced motion: no rotation, a static sync glyph instead. */
export function ToolLogoSpinner() {
  return <span className="ts-spinner" aria-hidden="true">
    <svg viewBox="0 0 40 40"><circle className="ts-spinner-track" cx="20" cy="20" r="18" /><circle className="ts-spinner-arc" cx="20" cy="20" r="18" /></svg>
    <RefreshCw className="ts-spinner-static" size={11} />
  </span>;
}

/** Thin bar + short percent for a sidebar row. Full details are in the row tooltip / description. */
export function ToolProgressMini({ tool }: { tool: ToolSyncState }) {
  const view = progressView(tool);
  return <span className="ts-meta" data-indeterminate={view.percent === null || undefined}>
    <span className="ts-bar" aria-hidden="true"><span style={view.percent === null ? undefined : { width: `${view.percent}%` }} /></span>
    <span className="ts-pct">{shortLabel(tool)}</span>
  </span>;
}

/** One-line indicator for the conversation top bar: spinner + "Etapa 1 de 2 · Lendo arquivos 79/167 · 47%" + thin bar. Renders nothing without an active sync. */
export function SyncIndicator({ tools, className = "" }: { tools: ToolSyncState[]; className?: string }) {
  const progress = summaryProgress(tools);
  if (!progress) return null;
  const pct = progress.percent;
  return <div className={`sync-chip ${className}`} role="progressbar" aria-label="Sincronização em andamento" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct ?? undefined} aria-valuetext={progress.speech} title={`Sincronizando sua base — ${progress.text}`} data-indeterminate={pct === null || undefined}>
    <LoaderCircle size={14} className="sync-spin" aria-hidden="true" />
    <span className="sync-chip-text">{progress.compact}</span>
    <span className="sync-chip-bar" aria-hidden="true"><span style={pct === null ? undefined : { width: `${pct}%` }} /></span>
  </div>;
}

export function SyncBanner({ tools, className = "" }: { tools: ToolSyncState[]; className?: string }) {
  const summary = summarize(tools);
  const copy = bannerCopy(summary);
  const issue = summary.errors[0];
  const progress = summaryProgress(tools);
  if (!copy && !issue) return null;
  return <div className={`sync-banner ${className}`} role="status" aria-live="polite" data-tone={copy ? "progress" : "warning"}>
    {copy ? <LoaderCircle size={16} className="sync-spin" aria-hidden="true" /> : <AlertTriangle size={16} aria-hidden="true" />}
    <div><p>{copy ?? errorMessage(issue)}</p>
      {copy && progress && <>
        <div className="sync-banner-bar" role="progressbar" aria-label="Progresso da sincronização" aria-valuemin={0} aria-valuemax={100} aria-valuenow={progress.percent ?? undefined} aria-valuetext={progress.speech} data-indeterminate={progress.percent === null || undefined}><span style={progress.percent === null ? undefined : { width: `${progress.percent}%` }} /></div>
        <p className="sync-banner-meta">{progress.text}</p>
      </>}
    </div>
  </div>;
}

export { percent as syncPercent };
