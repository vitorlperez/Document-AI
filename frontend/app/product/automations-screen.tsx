"use client";

import "./automation-modal.css";

import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, CheckCircle2, Clock3, Plus, Trash2 } from "lucide-react";
import { EmptyState, Enter, LoadingBlock, ProgressIndicator, SkeletonCard, Spinner, StaggerItem, Toast, ToastViewport, btn } from "../ui";
import { exitDelayMs, MOTION_MS } from "../ui/motion-logic";
import { type Company, type Folder, companyPath } from "./types-and-api";
import type { RecipientOption } from "./automation-recipients";
import { AutomationWebhooks } from "./automation-webhooks";
import { AutomationEditor } from "./automation-editor";
import { AutomationDeleteDialog } from "./automation-delete-dialog";
import { AutomationReportView } from "./automation-report-view";
import { AutomationHistory, automationDate } from "./automation-history";
import { canEditAutomation, newAutomationDraft, scopeNames, triggerLabel, type AutomationDraft } from "./automations-model";
import { api, automationError, automationPath, automationPayload, automationToDraft, runStatusLabel, type Automation, type AutomationRun } from "./automations-api";

export function AutomationsScreen({ company, currentUserId }: { company: Company; currentUserId?: string | null }) {
  const [items, setItems] = useState<Automation[]>([]);
  const [limit, setLimit] = useState(20);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [folderError, setFolderError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ id: string | null; draft: AutomationDraft; closing?: boolean; origin?: HTMLElement } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<{ item: Automation; origin?: HTMLElement; closing?: boolean } | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [leavingId, setLeavingId] = useState<string | null>(null);
  const [toast, setToast] = useState<{ tone: "success" | "error"; title: string; open: boolean } | null>(null);
  const [historyId, setHistoryId] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const emailLinkHandled = useRef(false);
  const [sharedRun, setSharedRun] = useState<{ automationId: string; runId: string } | null>(null);
  const [emailRun, setEmailRun] = useState<{ automationId: string; runId: string | null } | null>(null);
  const base = automationPath(company.id);
  const canManage = company.role === "owner" || company.role === "admin";
  const load = useCallback(async (signal?: AbortSignal) => {
    try { const data = await api<{ items: Automation[]; limit: number }>(base, { signal, cache: "no-store" }); if (!signal?.aborted) { setItems(data.items); setLimit(data.limit); setError(null);
      // Apply the e-mail deep link once, after the authenticated list arrives.
      if (!emailLinkHandled.current) {
        const query = new URLSearchParams(window.location.search);
        const selected = data.items.find((item) => item.id === query.get("automation"));
        emailLinkHandled.current = true;
        if (selected) {
          setHistoryId(selected.id);
          setEmailRun({ automationId: selected.id, runId: query.get("run") });
          if (query.get("edit") === "1") setEditor({ id: selected.id, draft: automationToDraft(selected) });
        } else if (query.get("automation") && query.get("run")) {
          // A recipient who cannot manage this automation still gets the read-only report from the e-mail link.
          setSharedRun({ automationId: query.get("automation")!, runId: query.get("run")! });
        }
      } } }
    catch (caught) { if (!signal?.aborted) setError(automationError(caught)); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [base]);
  const loadRecipients = useCallback(async (query: string, signal: AbortSignal) => {
    try { return (await api<{ items: RecipientOption[] }>(`/organizations/${company.id}/automation-recipients?${query}`, { signal, cache: "no-store" })).items; }
    catch (caught) { throw new Error(automationError(caught)); }
  }, [company.id]);
  const fetchLibrary = useCallback(<T,>(path: string, signal: AbortSignal) => api<T>(path, { signal, cache: "no-store" }), []);
  const loadOptions = useCallback(async (signal?: AbortSignal) => {
    try { const data = await api<Folder[]>(`/workspace-folders?organization_id=${company.id}`, { signal, cache: "no-store" }); if (!signal?.aborted) { setFolders(data); setFolderError(null); } }
    catch (caught) { if (!signal?.aborted) setFolderError(automationError(caught)); }
  }, [company.id]);
  useEffect(() => { const controller = new AbortController(); void Promise.resolve().then(() => { if (!controller.signal.aborted) { void load(controller.signal); void loadOptions(controller.signal); } }); return () => controller.abort(); }, [load, loadOptions]);
  const hasPendingRuns = items.some((item) => item.last_run?.status === "queued" || item.last_run?.status === "running");
  useEffect(() => {
    if (!hasPendingRuns) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function tick() { await load(controller.signal); if (!controller.signal.aborted) timer = setTimeout(() => void tick(), 3000); }
    timer = setTimeout(() => void tick(), 3000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [hasPendingRuns, load]);
  const history = items.find((item) => item.id === historyId);
  const historySettled = useCallback(() => { void load(); }, [load]);
  function closeEditor() { setEditor(null); setSaveError(null); }
  async function save(draft: AutomationDraft) {
    if (!editor || busy) return;
    setBusy("save"); setSaveError(null);
    try {
      const item = await api<Automation>(editor.id ? `${base}/${editor.id}` : base, { method: editor.id ? "PATCH" : "POST", body: JSON.stringify(automationPayload(draft)) });
      setItems((current) => editor.id ? current.map((existing) => existing.id === item.id ? item : existing) : [item, ...current]);
      setEditor((current) => current ? { ...current, closing: true } : null); setNotice("Automação salva. Você pode executá-la agora ou aguardar o próximo gatilho.");
    } catch (caught) { setSaveError(automationError(caught)); } finally { setBusy(null); }
  }
  async function toggle(item: Automation) {
    if (busy) return;
    setBusy(item.id); setError(null);
    try { const updated = await api<Automation>(`${base}/${item.id}/enabled`, { method: "PUT", body: JSON.stringify({ enabled: !item.enabled }) }); setItems((current) => current.map((existing) => existing.id === updated.id ? updated : existing)); setNotice(updated.enabled ? "Automação ligada." : "Automação desligada. Você ainda pode executá-la manualmente."); }
    catch (caught) { setError(automationError(caught)); } finally { setBusy(null); }
  }
  function showToast(tone: "success" | "error", title: string) { setToast({ tone, title, open: true }); }
  async function confirmDelete() {
    if (!deleting || busy) return;
    const target = deleting.item;
    setBusy("delete"); setDeleteError(null);
    try {
      await api<void>(`${base}/${target.id}`, { method: "DELETE" });
      setDeleting((current) => current ? { ...current, closing: true } : null);
      setHistoryId((current) => current === target.id ? null : current);
      setLeavingId(target.id);
      window.setTimeout(() => { setItems((current) => current.filter((existing) => existing.id !== target.id)); setLeavingId(null); }, exitDelayMs(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false, MOTION_MS.base));
      showToast("success", `Automação "${target.name}" excluída.`);
    } catch (caught) { const message = automationError(caught); setDeleteError(message); showToast("error", `Não foi possível excluir "${target.name}". ${message}`); }
    finally { setBusy(null); }
  }
  async function run(item: Automation) {
    if (busy) return;
    setBusy(item.id); setError(null);
    try {
      const started = await api<AutomationRun>(`${base}/${item.id}/run`, { method: "POST" });
      setItems((current) => current.map((existing) => existing.id === item.id ? { ...existing, last_run: { id: started.id, status: started.status, finished_at: started.finished_at } } : existing));
      setHistoryId(item.id); setRevision((value) => value + 1); setNotice("Execução solicitada. Acompanhe o resultado no histórico abaixo.");
    } catch (caught) { setError(automationError(caught)); } finally { setBusy(null); }
  }
  return <div className="min-w-0">
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-start"><div><h1 className="flex items-center gap-3 text-2xl font-semibold"><Clock3 aria-hidden="true" size={26} />Automações</h1><p className="mt-2 max-w-2xl text-sm text-muted-foreground">Transforme suas pastas em resumos, tabelas e alertas recorrentes, com as fontes de cada resultado.</p></div><button disabled={loading || busy !== null || editor !== null || items.length >= limit} className={btn("primary", "md", "shrink-0")} onClick={(event) => { setSaveError(null); setEditor({ id: null, draft: newAutomationDraft(), origin: event.currentTarget }); }}><Plus size={16} aria-hidden="true" />Criar automação</button></div>
    {notice && <Enter key={notice} variant="slide"><p role="status" className="mt-4 flex items-start gap-2 rounded-lg bg-sage p-3 text-sm"><CheckCircle2 aria-hidden="true" size={16} className="mo-check-pop mt-0.5 shrink-0" />{notice}</p></Enter>}
    {error && <div role="alert" className="mt-4 rounded-lg border border-rose-200 p-3 text-sm text-rose-700"><p>{error}</p><button className={btn("secondary", "sm", "mt-2")} onClick={() => void load()}>Atualizar lista</button></div>}
    {folderError && <div role="alert" className="mt-4 text-sm text-rose-700"><p>Não foi possível carregar as pastas: {folderError}</p><button className={btn("secondary", "sm", "mt-2")} onClick={() => void loadOptions()}>Tentar carregar pastas novamente</button></div>}
    {items.length >= limit && <p role="status" className="mt-4 text-sm">Limite de {limit} automações atingido. Você pode editar as existentes.</p>}
    {editor && <AutomationEditor fetchJson={fetchLibrary} organizationId={company.id} key={editor.id ?? "new"} initial={editor.draft} editing={editor.id !== null} isOpen={!editor.closing} returnFocus={editor.origin} folders={folders} loadRecipients={loadRecipients} canChooseRecipients={canManage} saving={busy === "save"} serverError={saveError} onSave={(draft) => void save(draft)} onCancel={closeEditor} />}
    {loading ? <LoadingBlock label="Carregando automações…" className="mt-6"><div className="grid min-w-0 gap-4 lg:grid-cols-2"><SkeletonCard lines={3} /><SkeletonCard lines={3} /></div></LoadingBlock> : !items.length && !error ? <section className="mt-6 rounded-lg border border-dashed border-line"><EmptyState icon={<CalendarClock size={28} />} title="Seu próximo relatório pode chegar sozinho" description="Escolha uma agenda ou uma mudança de pasta, escreva o que quer descobrir e receba o resultado com fontes." actions={<><a href={companyPath(company.id, "/integrations")} className="mo-arrow inline-flex min-h-11 items-center text-sm text-primary underline">Conectar pastas em Integrações</a><button type="button" disabled={busy !== null || editor !== null} className={btn("primary")} onClick={(event) => { setSaveError(null); setEditor({ id: null, draft: newAutomationDraft(), origin: event.currentTarget }); }}>Criar automação</button></>} /></section> : <ul aria-label="Automações" className="mt-6 grid min-w-0 gap-4 lg:grid-cols-2">{items.map((item, index) => {
      const draft = automationToDraft(item);
      const folderNames = scopeNames(draft, draft.legacyFolderIds.map((id) => folders.find((folder) => folder.id === id)?.name).filter((name): name is string => !!name));
      const running = item.last_run?.status === "queued" || item.last_run?.status === "running";
      return <StaggerItem as="li" key={item.id} index={index} step="md" className={`automation-card min-w-0 rounded-lg border border-line bg-panel p-4 sm:p-5${leavingId === item.id ? " automation-card-leaving" : ""}`}><div className="flex items-start justify-between gap-3"><h2 className="min-w-0 break-words text-lg font-semibold">{item.name}</h2><label className="flex min-h-11 shrink-0 items-center gap-2 text-sm"><input type="checkbox" role="switch" aria-label={`Ativar automação ${item.name}`} checked={item.enabled} disabled={busy !== null} onChange={() => void toggle(item)} />{item.enabled ? "Ligada" : "Desligada"}</label></div><p className="mt-2 break-words text-sm">{triggerLabel(draft, folderNames)}{item.trigger_kind === "schedule" ? ` (${draft.timezone})` : ""}</p>{folderNames.length > 0 && <p className="mt-1 break-words text-sm text-muted-foreground">{folderNames.length === 1 ? "Pasta" : "Pastas"}: {draft.scopeFolders.length ? draft.scopeFolders.map((folder) => folder.path).join(" · ") : folderNames.join(" · ")}</p>}<p className="mt-3 text-sm text-muted-foreground">Última execução: {automationDate(item.last_run_at)}{item.last_run ? ` · ${runStatusLabel(item.last_run.status)}` : ""}</p>{running && <div className="mt-2" role="status"><p className="flex items-center gap-2 text-sm"><Spinner size={14} />{item.last_run?.status === "queued" ? "Na fila para executar…" : "Executando agora…"}</p><ProgressIndicator label="Executando automação" className="mt-2" /></div>}{item.next_run_at && <p className="mt-1 text-sm text-muted-foreground">Próxima: {automationDate(item.next_run_at)}</p>}<div className="mt-4 flex flex-wrap gap-2"><button disabled={busy !== null || running || editor !== null || deleting !== null} className={btn("primary")} aria-label={`Executar agora: ${item.name}`} onClick={() => void run(item)}>{busy === item.id ? <span className="inline-flex items-center gap-2"><Spinner size={14} />Aguarde…</span> : running ? "Execução em andamento" : "Executar agora"}</button><button disabled={busy !== null || editor !== null || deleting !== null} className={btn("secondary")} aria-label={`Editar automação: ${item.name}`} onClick={(event) => { setSaveError(null); setEditor({ id: item.id, draft, origin: event.currentTarget }); }}>Editar</button><button className={btn("ghost")} aria-label={`Ver histórico: ${item.name}`} aria-expanded={historyId === item.id} onClick={() => setHistoryId(historyId === item.id ? null : item.id)}>Ver histórico</button>{canEditAutomation(company.role, item.created_by_user_id, currentUserId) && <button disabled={busy !== null || editor !== null || deleting !== null || leavingId !== null} className={btn("danger-ghost", "md", "sm:ml-auto")} aria-label={`Excluir automação: ${item.name}`} onClick={(event) => { setDeleteError(null); setDeleting({ item, origin: event.currentTarget }); }}><Trash2 size={16} aria-hidden="true" />Excluir</button>}</div></StaggerItem>;
    })}</ul>}
    {deleting && <AutomationDeleteDialog name={deleting.item.name} busy={busy === "delete"} error={deleteError} isOpen={!deleting.closing} returnFocus={deleting.origin} onConfirm={() => void confirmDelete()} onCancel={() => { setDeleting(null); setDeleteError(null); }} />}
    <ToastViewport>{toast && <Toast key={toast.title} open={toast.open} tone={toast.tone} title={toast.title} duration={toast.tone === "error" ? null : 6000} dismissLabel="Fechar aviso" onDismiss={() => setToast((current) => current ? { ...current, open: false } : null)} />}</ToastViewport>
    {sharedRun && !history && <AutomationReportView key={sharedRun.runId} organizationId={company.id} automationId={sharedRun.automationId} runId={sharedRun.runId} />}
    {history && <AutomationHistory key={history.id} organizationId={company.id} automation={history} revision={revision} targetRunId={emailRun?.automationId === history.id ? emailRun.runId : null} onClose={() => setHistoryId(null)} onSettled={historySettled} />}
    {canManage && <AutomationWebhooks key={company.id} organizationId={company.id} />}
  </div>;
}
