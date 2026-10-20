"use client";

import { ArrowLeft, ChevronRight, CircleAlert, ExternalLink, FolderOpen, HardDrive, History, Plus, RefreshCw, Search, Trash2, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { ApiError, type Company, type Folder, type DocumentFailure, type LibraryNode, type LibraryPage, type ManualSync, api, messageFor, statusLabel, documentFailureLabel, skippedReasonLabel, LibraryNodeIcon, useLatestRequest, libraryPath, ProviderMark } from "./types-and-api";
import { LibrarySidebarHeader } from "./shared-ui";
import { EmptyState, ErrorState, LoadingBlock, ProgressIndicator, SkeletonList, Spinner, btn, closeDialogAnimated, staggerStyle } from "../ui";
import { useLibraryItems } from "./use-library-items";
import { LibraryGrid, LibraryLoadingSkeleton, LibraryViewControls } from "./library-grid";
import { LibraryIndexingBadge } from "./library-indexing-badge";
import { LibraryAccessBadge } from "./library-access-badge";
import { DEFAULT_LIBRARY_VIEW, LIBRARY_VIEW_KEY, buildLibraryQuery, parseLibraryView, serializeLibraryView, withSpaceHeadings, type LibraryView } from "../library-view-logic";
import { SpaceBadges, SpaceChips, SpaceGroupToggle, spaceEmptyState, useLibrarySpaces } from "./library-spaces";

import { toolLabel } from "../question-scope";
import { UNAVAILABLE_ITEM_MESSAGE, chatMentionPath, locateQuery, parseLibraryFocus } from "../nav-bridges";
import { mergeToolRoots, pickTool, rootCoversTool } from "../tool-groups";
import { ToolLogoSpinner, ToolStatusDot, useSyncStatus, syncPercent } from "../sync-status";
import { useToolsSidebarCollapsed } from "../tools-sidebar";
import "../tools-sidebar.css";
import "../interface-motion.css";
import { useDialogBackdropClose } from "../modal-dismiss";
import { errorMessage, isActive, progressView } from "../sync-status-logic";

export function LibraryScreen({ company, onConnect, setError, setNotice }: { company: Company; onConnect: () => void; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const router = useRouter();
  const params = useSearchParams();
  const sourceParam = params.get("source");
  const syncingParam = params.get("syncing");
  const syncStatus = useSyncStatus(company.id);
  const { collapsed: sidebarCollapsed, toggle: toggleSidebar } = useToolsSidebarCollapsed();
  const [spacesPanelOpen, setSpacesPanelOpen] = useState(false);
  const closeSpacesPanel = useCallback(() => closeDialogAnimated(syncDialog.current, () => setSpacesPanelOpen(false)), []);
  const syncDialog = useRef<HTMLDialogElement>(null);
  const [manualSyncs, setManualSyncs] = useState<ManualSync[]>([]);
  const [syncHistoryError, setSyncHistoryError] = useState<string | null>(null);
  const { request: requestHistory } = useLatestRequest<{ items: ManualSync[] }>();
  const loadHistory = useCallback(() => {
    void requestHistory(`/library/sync-history?organization_id=${company.id}`, (result) => { setManualSyncs(result.items); setSyncHistoryError(null); }, (caught) => setSyncHistoryError(messageFor(caught)));
  }, [company.id, requestHistory]);
  useEffect(() => {
    const dialog = syncDialog.current;
    if (spacesPanelOpen) dialog?.showModal(); else dialog?.close();
  }, [spacesPanelOpen]);
  const [roots, setRoots] = useState<LibraryNode[]>([]); const [rootsLoading, setRootsLoading] = useState(true); const [rootsError, setRootsError] = useState<string | null>(null);
  const [path, setPath] = useState<LibraryNode[]>([]); const [folders, setFolders] = useState<Folder[]>([]); const [foldersLoading, setFoldersLoading] = useState(true); const [busyFolderId, setBusyFolderId] = useState<string | null>(null); const [busyFolderAction, setBusyFolderAction] = useState<"sync" | "remove" | null>(null); const [busyFileId, setBusyFileId] = useState<string | null>(null); const [busyNodeId, setBusyNodeId] = useState<string | null>(null);
  useDialogBackdropClose(syncDialog, closeSpacesPanel, busyNodeId !== null || busyFolderId !== null);
  const [documentFailures, setDocumentFailures] = useState<Record<string, DocumentFailure[]>>({}); const [failureLoadError, setFailureLoadError] = useState<Record<string, boolean>>({}); const [folderActionErrors, setFolderActionErrors] = useState<Record<string, string>>({}); const [folderSyncJobs, setFolderSyncJobs] = useState<Record<string, string>>({}); const [folderSyncAnnouncements, setFolderSyncAnnouncements] = useState<Record<string, string>>({});
  const canManage = company.role !== "member"; const current = path.at(-1);
  const [view, setView] = useState<LibraryView>(DEFAULT_LIBRARY_VIEW);
  useEffect(() => {
    let stored: string | null = null;
    try { stored = window.localStorage.getItem(LIBRARY_VIEW_KEY); } catch { /* storage unavailable */ }
    const parsed = parseLibraryView(stored);
    queueMicrotask(() => setView(parsed));
  }, []);
  const changeView = (next: LibraryView) => { setView(next); try { window.localStorage.setItem(LIBRARY_VIEW_KEY, serializeLibraryView(next)); } catch { /* storage unavailable */ } };
  const spaceFilter = useLibrarySpaces(company.id);
  const spaceQuery = buildLibraryQuery({ spaces: spaceFilter.selected });
  const spaceEmpty = spaceEmptyState({ spaces: spaceFilter.spaces, selected: spaceFilter.selected, canManage: company.role !== "member", atRoot: path.length === 0 });
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  // Search as the user types: from 2 characters on, after a short pause; shorter text returns to the normal listing.
  useEffect(() => {
    const text = query.trim();
    if (text.length < 2) { if (searchTerm) queueMicrotask(() => setSearchTerm("")); return; }
    if (text === searchTerm) return;
    const timer = window.setTimeout(() => { setSearchTerm(text); }, 300);
    return () => window.clearTimeout(timer);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);
  const clearSearch = () => { setQuery(""); setSearchTerm(""); };
  const endpoint = !spaceFilter.ready ? null : searchTerm ? `/library/search?organization_id=${company.id}&query=${encodeURIComponent(searchTerm)}${spaceQuery}` : current ? `/library/nodes/${current.id}/children?organization_id=${company.id}${spaceQuery}` : null;
  const { items, loading, loadingMore, hasMore, error: itemsError, sentinel, loadMore, reload: loadItems, refreshDuringSync } = useLibraryItems(endpoint);
  const loadError = itemsError ? messageFor(itemsError) : null;
  const { request: requestRoots } = useLatestRequest<LibraryPage>();
  const openPath = (nodes: LibraryNode[]) => { setPath(nodes); setQuery(""); setSearchTerm(""); };
  const loadRoots = useCallback(() => { setRootsLoading(true); setRootsError(null); void requestRoots(`/library?organization_id=${company.id}${spaceQuery}`, (result) => setRoots(mergeToolRoots(result.items)), (caught) => setRootsError(messageFor(caught)), () => setRootsLoading(false)); }, [company.id, requestRoots, spaceQuery]);
  useEffect(() => { void Promise.resolve().then(loadRoots); }, [loadRoots]);
  useEffect(() => {
    // Route-driven selection: ?source=<library root id> opens that tool and shows its folders.
    if (!sourceParam) return;
    const root = roots.find((item) => item.id === sourceParam);
    if (root && path[0]?.id !== root.id) queueMicrotask(() => openPath([root]));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roots, sourceParam]);
  // Ponte Conversa → Biblioteca: ?focus=<nó> | ?focusDoc=<documento citado> abre a pasta do item e o destaca. O backend decide o que a pessoa vê (404 igual ao de item inexistente).
  const focusSearch = params.toString();
  const focusTarget = parseLibraryFocus(focusSearch);
  const focusKey = focusTarget ? `${focusTarget.nodeId ?? ""}|${focusTarget.documentId ?? ""}` : null;
  const [focusId, setFocusId] = useState<string | null>(null);
  const appliedFocus = useRef<string | null>(null);
  const scrolledFocus = useRef<string | null>(null);
  useEffect(() => {
    if (!focusKey || !focusTarget) { appliedFocus.current = null; scrolledFocus.current = null; queueMicrotask(() => setFocusId(null)); return; }
    if (!spaceFilter.ready || rootsLoading || appliedFocus.current === focusKey) return;
    appliedFocus.current = focusKey;
    type Located = { mention: { node_id: string }; ancestors: LibraryNode[] };
    void api<Located>(`/library/locate?${locateQuery(company.id, focusTarget, spaceFilter.selected)}`).then((located) => {
      const [first, ...rest] = located.ancestors;
      const root = first && roots.find((item) => item.id === first.id || (item as { merged_root_ids?: string[] }).merged_root_ids?.includes(first.id));
      if (!root) { setNotice(UNAVAILABLE_ITEM_MESSAGE); return; }
      scrolledFocus.current = null;
      openPath([root, ...rest]); setFocusId(located.mention.node_id);
    }).catch((caught) => { setNotice(caught instanceof ApiError && caught.status === 404 ? UNAVAILABLE_ITEM_MESSAGE : messageFor(caught)); });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusKey, spaceFilter.ready, rootsLoading, roots]);
  useEffect(() => {
    if (!focusId || scrolledFocus.current === focusId) return;
    const card = document.querySelector<HTMLElement>(`[data-node-id="${focusId}"]`);
    if (card) {
      scrolledFocus.current = focusId;
      card.scrollIntoView({ block: "center", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
      card.querySelector<HTMLElement>(".library-card-main")?.focus({ preventScroll: true });
    } else if (hasMore && !loadingMore && !loading) loadMore();
  }, [focusId, items, hasMore, loadingMore, loading, loadMore]);
  const selectTool = (item: LibraryNode) => { openPath([item]); router.replace(libraryPath(company.id, item.id)); };
  const refreshLibrary = () => { loadRoots(); loadItems(); syncStatus.refresh(); };
  const missingTools = syncStatus.tools.filter((tool) => !roots.some((root) => rootCoversTool(root, tool)));
  const selectedSync = syncingParam ? syncStatus.tools.find((tool) => tool.sourceId === syncingParam) : path[0] ? pickTool(syncStatus.tools, path[0]) : undefined;
  const toolLevel = path.length > 0 || Boolean(syncingParam) || Boolean(searchTerm);
  const hasTools = roots.length > 0 || syncStatus.tools.length > 0;
  const selectSync = (sourceId: string) => { openPath([]); router.replace(`/companies/${company.id}/library?syncing=${encodeURIComponent(sourceId)}`); };
  // Library roots appear progressively; follow the selected source as its root arrives.
  const rootIds = syncStatus.tools.map((tool) => tool.libraryNodeId ?? "").join(",");
  useEffect(() => { queueMicrotask(loadRoots); }, [rootIds, loadRoots]);
  useEffect(() => {
    if (!syncingParam) return;
    const root = roots.find((item) => item.source_id === syncingParam || (item as { merged_source_ids?: string[] }).merged_source_ids?.includes(syncingParam));
    queueMicrotask(() => {
      if (root) { openPath([root]); router.replace(libraryPath(company.id, root.id)); }
      else if (path.length > 0) openPath([]);
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [syncingParam, roots]);

  useEffect(() => {
    if (!syncStatus.anySyncing) return;
    const timer = window.setInterval(() => { loadRoots(); refreshDuringSync(); }, 5000);
    return () => window.clearInterval(timer);
  }, [syncStatus.anySyncing, loadRoots, refreshDuringSync]);
  const loadFolders = useCallback(() => { setFoldersLoading(true); void api<Folder[]>(`/workspace-folders?organization_id=${company.id}`).then((items) => {
    setFolders(items);
    const terminal = items.filter((folder) => folder.status !== "queued" && folder.status !== "syncing");
    setFolderActionErrors((current) => {
      const next = { ...current };
      terminal.forEach((folder) => { if (next[folder.id]?.startsWith("Não foi possível consultar o progresso")) delete next[folder.id]; });
      return next;
    });
    setFolderSyncAnnouncements((current) => {
      const next = { ...current };
      terminal.forEach((folder) => {
        if (!next[folder.id]?.startsWith("Não foi possível atualizar o progresso")) return;
        next[folder.id] = folder.status === "ready" ? "Sincronização concluída." : folder.status === "partial_failure" ? "Sincronização concluída com algumas falhas." : folder.status === "failed" ? "A sincronização falhou." : "Estado da sincronização atualizado.";
      });
      return next;
    });
  }).catch((caught) => setError(messageFor(caught))).finally(() => setFoldersLoading(false)); }, [company.id, setError]);
  useEffect(() => { void Promise.resolve().then(loadFolders); }, [loadFolders]);
  useEffect(() => {
    if (!folders.some((folder) => folder.status === "queued" || folder.status === "syncing")) return;
    const timer = window.setInterval(loadFolders, 5000);
    return () => window.clearInterval(timer);
  }, [folders, loadFolders]);
  useEffect(() => {
    const jobs = Object.entries(folderSyncJobs);
    if (jobs.length === 0) return;
    let active = true;
    async function refreshSyncJobs() {
      const results = await Promise.all(jobs.map(async ([folderId, jobId]) => {
        try { return [folderId, jobId, await api<{ status: string; error_code: string | null }>(`/workspace-folders/${folderId}/syncs/${jobId}?organization_id=${company.id}`), null] as const; }
        catch (caught) { return [folderId, jobId, null, messageFor(caught)] as const; }
      }));
      if (!active) return;
      const completed = results.filter(([, , job]) => job && job.status !== "queued" && job.status !== "syncing");
      const pollingErrors = results.filter(([, , job, error]) => !job && error);
      if (pollingErrors.length > 0) {
        setFolderActionErrors((currentErrors) => {
          const nextErrors = { ...currentErrors };
          pollingErrors.forEach(([folderId, , , error]) => { nextErrors[folderId] = `Não foi possível consultar o progresso da sincronização. Atualize as pastas conectadas para conferir o estado. ${error}`; });
          return nextErrors;
        });
        setFolderSyncJobs((currentJobs) => {
          const nextJobs = { ...currentJobs };
          pollingErrors.forEach(([folderId, jobId]) => { if (nextJobs[folderId] === jobId) delete nextJobs[folderId]; });
          return nextJobs;
        });
        setFolderSyncAnnouncements((current) => {
          const next = { ...current };
          pollingErrors.forEach(([folderId]) => { next[folderId] = "Não foi possível atualizar o progresso. Atualize as pastas conectadas para conferir o estado."; });
          return next;
        });
        loadFolders();
      }
      const inProgress = results.filter(([, , job]) => job && (job.status === "queued" || job.status === "syncing"));
      if (inProgress.length > 0) {
        setFolderSyncAnnouncements((current) => {
          const next = { ...current };
          inProgress.forEach(([folderId, , job]) => { next[folderId] = job?.status === "queued" ? "Sincronização na fila." : "Sincronização em andamento."; });
          return next;
        });
      }
      if (completed.length === 0) return;
      setFolders((currentFolders) => currentFolders.map((folder) => {
        const result = completed.find(([folderId]) => folderId === folder.id)?.[2];
        return result ? { ...folder, status: result.status } : folder;
      }));
      setFolderSyncJobs((currentJobs) => {
        const nextJobs = { ...currentJobs };
        completed.forEach(([folderId, jobId]) => { if (nextJobs[folderId] === jobId) delete nextJobs[folderId]; });
        return nextJobs;
      });
      setFolderActionErrors((currentErrors) => {
        const nextErrors = { ...currentErrors };
        completed.forEach(([folderId, , job]) => {
          if (job?.status === "failed") nextErrors[folderId] = `A sincronização falhou${job.error_code ? ` (${job.error_code})` : ""}. Tente novamente.`;
          else delete nextErrors[folderId];
        });
        return nextErrors;
      });
      setFolderSyncAnnouncements((current) => {
        const next = { ...current };
        completed.forEach(([folderId, , job]) => {
          next[folderId] = job?.status === "ready" ? "Sincronização concluída." : job?.status === "partial_failure" ? "Sincronização concluída com algumas falhas." : "A sincronização falhou.";
        });
        return next;
      });
      loadFolders(); loadItems();
    }
    void refreshSyncJobs();
    const timer = window.setInterval(() => { void refreshSyncJobs(); }, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [company.id, folderSyncJobs, loadFolders, loadItems]);
  useEffect(() => {
    if (!canManage) return;
    let active = true;
    const partialFolders = folders.filter((folder) => folder.status === "partial_failure");
    void Promise.all(partialFolders.map(async (folder) => {
      try {
        const rows = await api<DocumentFailure[]>(`/workspace-folders/${folder.id}/documents/failures?organization_id=${company.id}`);
        return [folder.id, rows, false] as const;
      } catch {
        return [folder.id, [] as DocumentFailure[], true] as const;
      }
    })).then((results) => {
      if (!active) return;
      setDocumentFailures(Object.fromEntries(results.map(([id, rows]) => [id, rows])));
      setFailureLoadError(Object.fromEntries(results.map(([id, , failed]) => [id, failed])));
    });
    return () => { active = false; };
    }, [canManage, company.id, folders]);
  useEffect(() => {
    if (!spacesPanelOpen) return;
    void Promise.resolve().then(loadHistory);
    const timer = window.setInterval(() => { loadHistory(); loadFolders(); }, 3000);
    return () => window.clearInterval(timer);
  }, [spacesPanelOpen, loadHistory, loadFolders]);
  const folderSyncActive = (folderId: string) => Boolean(folderSyncJobs[folderId]) || manualSyncs.some((run) => run.tasks.some((task) => task.workspace_folder_id === folderId && (task.status === "queued" || task.status === "syncing")));
  function openItem(item: LibraryNode) { if (item.kind === "file") { if (item.source_url) window.open(item.source_url, "_blank", "noopener,noreferrer"); return; } openPath(searchTerm ? [item] : [...path, item]); }
  async function confirmResyncHistory(runId: string | undefined) {
    if (!runId) throw new Error("O serviço não confirmou o registro da ressincronização. Atualize a Biblioteca para conferir antes de tentar novamente.");
    const history = await api<{ items: ManualSync[] }>(`/library/sync-history?organization_id=${company.id}`, { cache: "no-store" });
    setManualSyncs(history.items);
    if (!history.items.some((run) => run.id === runId)) throw new Error("A ressincronização foi solicitada, mas seu registro não apareceu no histórico. Atualize a Biblioteca para conferir antes de tentar novamente.");
    setSyncHistoryError(null);
  }
  async function reprocessFolderNode(item: LibraryNode) {
    setBusyNodeId(item.id); setError(null);
    try { const result = await api<{ run_id: string; job_ids: string[] }>(`/library/nodes/${item.id}/reprocess?organization_id=${company.id}&reprocess_all=false`, { method: "POST" }); await confirmResyncHistory(result.run_id); if (!result.job_ids?.length) throw new Error("Nenhum trabalho de ressincronização foi iniciado. Selecione uma pasta conectada na integração e tente novamente."); setNotice(`Sincronização incremental de “${item.name}” agendada: só o que é novo ou mudou na origem é atualizado.`); setSpacesPanelOpen(true); loadHistory(); loadFolders(); }
    catch (caught) { const cooldown = messageFor(caught).includes("too soon"); const detail = cooldown ? `“${item.name}” foi sincronizada há instantes. Aguarde cerca de um minuto para sincronizar de novo.` : `Não foi possível confirmar a sincronização de “${item.name}”. ${messageFor(caught)}`; setError(detail); setSyncHistoryError(detail); } finally { setBusyNodeId(null); }
  }
  async function removeFolderNode(item: LibraryNode) {
    if (!window.confirm(`Remover a pasta “${item.name}” da Biblioteca? Ela, suas subpastas e seus arquivos serão removidos do índice e da Biblioteca e não voltarão nas próximas sincronizações ou ressincronizações. Os originais continuarão na fonte conectada.`)) return;
    setBusyNodeId(item.id); setError(null);
    try { const result = await api<{ documents: number }>(`/library/nodes/${item.id}/index?organization_id=${company.id}`, { method: "DELETE" }); setNotice(`“${item.name}” foi removida do índice local (${result.documents} arquivo${result.documents === 1 ? "" : "s"}).`); loadItems(); loadFolders(); }
    catch (caught) { setError(messageFor(caught)); } finally { setBusyNodeId(null); }
  }
  function backToToolList() { openPath([]); router.replace(`/companies/${company.id}/library`); }
  function goBack() { if (searchTerm) { setQuery(""); setSearchTerm(""); return; } if (path.length > 1) openPath(path.slice(0, -1)); }
  async function syncFolder(folder: Folder) { setBusyFolderId(folder.id); setBusyFolderAction("sync"); setError(null); setFolderActionErrors((currentErrors) => { const nextErrors = { ...currentErrors }; delete nextErrors[folder.id]; return nextErrors; }); setFolderSyncAnnouncements((current) => ({ ...current, [folder.id]: "Sincronização na fila." })); try { const result = await api<{ run_id: string; job_id: string; status: string }>(`/library/workspaces/${folder.id}/reprocess?organization_id=${company.id}`, { method: "POST" }); await confirmResyncHistory(result.run_id); if (!result.job_id) throw new Error("Nenhum trabalho de ressincronização foi confirmado."); setFolders((currentFolders) => currentFolders.map((currentFolder) => currentFolder.id === folder.id ? { ...currentFolder, status: result.status } : currentFolder)); setFolderSyncJobs((currentJobs) => ({ ...currentJobs, [folder.id]: result.job_id })); setNotice(`Sincronização incremental de “${folder.name}” iniciada em segundo plano: só o que é novo ou mudou na origem é atualizado.`); loadHistory(); } catch (caught) { const detail = messageFor(caught); setFolderActionErrors((currentErrors) => ({ ...currentErrors, [folder.id]: `Não foi possível resincronizar esta pasta conectada. ${detail}` })); } finally { setBusyFolderId(null); setBusyFolderAction(null); } }
  async function removeFolder(folder: Folder) { if (!window.confirm(`Excluir a pasta conectada “${folder.name}” e todos os dados locais dele no Arquivio? Isso remove documentos indexados, trechos, embeddings e consultas salvas. Nenhum arquivo ou pasta será apagado da fonte original.`)) return; setBusyFolderId(folder.id); setBusyFolderAction("remove"); setError(null); setFolderActionErrors((currentErrors) => { const nextErrors = { ...currentErrors }; delete nextErrors[folder.id]; return nextErrors; }); try { await api<void>(`/workspace-folders/${folder.id}?organization_id=${company.id}`, { method: "DELETE" }); setFolders((currentFolders) => currentFolders.filter((currentFolder) => currentFolder.id !== folder.id)); setNotice(`A pasta conectada “${folder.name}” e seus dados locais foram excluídos do Arquivio.`); loadFolders(); loadItems(); } catch (caught) { const detail = messageFor(caught); setFolderActionErrors((currentErrors) => ({ ...currentErrors, [folder.id]: `Não foi possível excluir os dados locais desta pasta conectada. ${detail}` })); } finally { setBusyFolderId(null); setBusyFolderAction(null); } }
  async function reprocessFileNode(item: LibraryNode) {
    const refs = item.workspace_documents ?? [];
    if (refs.length === 0) { setError("Este arquivo não possui uma cópia indexada disponível para reprocessar."); return; }
    setBusyFileId(item.id); setError(null);
    try { for (const ref of refs) await api<{ job_id: string; status: string }>(`/workspace-folders/${ref.workspace_folder_id}/documents/${ref.document_id}/reprocess?organization_id=${company.id}`, { method: "POST" }); setNotice(`Reprocessamento de “${item.name}” agendado. O conteúdo será preparado novamente em segundo plano.`); loadItems(); loadFolders(); }
    catch (caught) { setError(messageFor(caught)); } finally { setBusyFileId(null); }
  }
  async function removeFileNode(item: LibraryNode) { const refs = item.workspace_documents ?? []; if (refs.length === 0) { setError("Este arquivo não possui uma cópia indexada disponível para remover."); return; } if (!window.confirm(`Remover “${item.name}” da Biblioteca? O arquivo será removido do índice e da Biblioteca e não voltará nas próximas sincronizações ou ressincronizações. O original continuará na fonte conectada.`)) return; setBusyFileId(item.id); setError(null); try { for (const ref of refs) await api<void>(`/workspace-folders/${ref.workspace_folder_id}/documents/${ref.document_id}?organization_id=${company.id}`, { method: "DELETE" }); setNotice(`“${item.name}” foi removido do índice local.`); loadItems(); loadFolders(); } catch (caught) { setError(messageFor(caught)); } finally { setBusyFileId(null); } }
  return <><div className="workspace-frame overflow-hidden border border-line bg-panel"><div className={`grid library-panels min-h-[calc(100vh-14rem)]${sidebarCollapsed ? " library-collapsed" : ""}`} data-mobile-level={toolLevel ? "tool" : "list"}><aside aria-label="Ferramentas integradas" data-collapsed={sidebarCollapsed ? "true" : "false"} className="library-sidebar border-b border-line bg-sage xl:border-b-0 xl:border-r"><LibrarySidebarHeader canManage={canManage} onConnect={onConnect} onRefresh={refreshLibrary} collapsed={sidebarCollapsed} onToggle={toggleSidebar} /><p className="px-4 pb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Ferramentas integradas</p><nav id="library-tool-list" className="library-tool-list max-h-72 space-y-0.5 overflow-y-auto px-2 pb-4 xl:max-h-[calc(100vh-18rem)]">{(rootsLoading || syncStatus.loading) && !hasTools ? <LoadingBlock label="Carregando ferramentas…" className="p-3"><SkeletonList rows={4} /></LoadingBlock> : rootsError ? <div role="alert" className="px-2 py-3 text-sm text-rose-700">{rootsError}<button onClick={loadRoots} className="mt-2 block font-semibold underline">Tentar novamente</button></div> : !hasTools ? <div className="px-2 py-3 text-sm text-muted-foreground"><HardDrive size={18} className="mb-2 text-primary" />{syncStatus.error ?? "Nenhuma ferramenta conectada."}{canManage && <button onClick={onConnect} className="mt-2 block font-semibold text-primary underline">Conectar uma fonte</button>}</div> : <>{roots.map((item) => { const active = path[0]?.id === item.id; const rootTool = syncStatus.tools.find((tool) => tool.libraryNodeId === item.id || tool.sourceId === item.source_id); return <div key={item.id} className="flex items-center gap-1"><button onClick={() => selectTool(item)} aria-current={active ? "true" : undefined} aria-label={sidebarCollapsed ? `${item.name}${rootTool ? `: ${isActive(rootTool) ? progressView(rootTool).text : "sincronização concluída"}` : ""}` : undefined} title={sidebarCollapsed ? item.name : undefined} className={`library-tool-select flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors ${active ? "bg-panel font-semibold text-ink shadow-sm ring-1 ring-line" : "text-ink hover:bg-panel/70"}`}>{(() => { const spinning = Boolean(rootTool) && isActive(rootTool!); return <span className="ts-logo grid size-7 shrink-0 place-items-center rounded-lg bg-sage-selected text-primary" data-syncing={spinning || undefined}><LibraryNodeIcon item={item} size={14} />{spinning && <ToolLogoSpinner />}{rootTool && <span className="library-tool-status"><ToolStatusDot tool={rootTool} /></span>}</span>; })()}<span className="library-tool-name min-w-0 flex-1 truncate" title={item.name}>{item.name}</span></button>{<button disabled={busyNodeId !== null} onClick={() => { void reprocessFolderNode(item); }} aria-label={`Sincronizar alterações de ${item.name}`} title={`Sincronizar alterações de ${item.name}`} className="library-tool-resync grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-panel hover:text-primary disabled:opacity-40">{busyNodeId === item.id ? <Spinner size={14} /> : <RefreshCw size={14} />}</button>}</div>; })}{missingTools.map((tool) => <div key={tool.sourceId} className="flex items-center gap-1"><button type="button" onClick={() => selectSync(tool.sourceId)} aria-label={sidebarCollapsed ? `${toolLabel(tool.provider)}: ${isActive(tool) ? progressView(tool).text : "sincronização"}` : undefined} title={sidebarCollapsed ? toolLabel(tool.provider) : undefined} aria-current={syncingParam === tool.sourceId ? "true" : undefined} className={`flex min-h-11 min-w-0 flex-1 items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-ink ${syncingParam === tool.sourceId ? "bg-panel ring-1 ring-line" : "hover:bg-panel/70"}`}><span className="ts-logo" data-syncing={isActive(tool) || undefined}><ProviderMark provider={tool.provider} size="sm" />{isActive(tool) && <ToolLogoSpinner />}<span className="library-tool-status"><ToolStatusDot tool={tool} /></span></span><span className="library-tool-name min-w-0 flex-1 truncate" title={toolLabel(tool.provider)}>{toolLabel(tool.provider)}</span></button></div>)}</>}</nav>{canManage && <div className="library-sidebar-foot"><button type="button" onClick={onConnect} className="ts-add" aria-label="Adicionar fonte" title="Adicionar fonte"><Plus size={18} aria-hidden="true" /></button></div>}</aside><main className="relative min-w-0 p-4 sm:p-5" aria-busy={loading}><div className="library-head flex items-center gap-2"><>{!searchTerm && path.length <= 1 && <button type="button" onClick={backToToolList} aria-label="Voltar para a lista de ferramentas" title="Voltar para a lista de ferramentas" className="library-back-list size-9 shrink-0 place-items-center rounded-lg border border-line text-ink hover:bg-sage"><ArrowLeft size={16} aria-hidden="true" /></button>}<button type="button" onClick={goBack} disabled={!searchTerm && path.length <= 1} aria-label={searchTerm ? "Sair da busca" : "Voltar para a pasta anterior"} title={searchTerm ? "Sair da busca" : "Voltar para a pasta anterior"} className={`${!searchTerm && path.length <= 1 ? "library-back-desktop " : ""}grid size-9 shrink-0 place-items-center rounded-lg border border-line text-ink hover:bg-sage disabled:cursor-not-allowed disabled:opacity-40`}><ArrowLeft size={16} aria-hidden="true" /></button></><nav aria-label="Caminho da pasta" className="flex min-w-0 flex-1 flex-wrap items-center gap-0.5 text-sm">{searchTerm ? <span className="truncate px-1.5 font-semibold text-ink">Resultados para “{searchTerm}”</span> : path.length === 0 ? <span className="px-1.5 font-semibold text-ink">{selectedSync ? toolLabel(selectedSync.provider) : "Selecione uma ferramenta"}</span> : path.map((node, index) => <span key={node.id} className="flex min-w-0 items-center">{index > 0 && <ChevronRight size={13} className="shrink-0 text-muted-foreground" aria-hidden="true" />}<button onClick={() => openPath(path.slice(0, index + 1))} aria-current={index === path.length - 1 ? "page" : undefined} className={`max-w-40 truncate rounded-md px-1.5 py-1 ${index === path.length - 1 ? "font-semibold text-ink" : "text-primary hover:bg-sage"}`}>{node.name}</button></span>)}</nav>{(current || searchTerm) && <span className="library-count shrink-0 rounded-full bg-sage px-2.5 py-1 text-xs tabular-nums text-muted-foreground">{items.length} {(items.length) === 1 ? "item" : "itens"}</span>}{(current || searchTerm) && <LibraryViewControls view={view} onChange={changeView} />}<button type="button" onClick={() => { setSpacesPanelOpen(true); loadHistory(); }} aria-haspopup="dialog" aria-label="Sincronizações" title="Sincronizações" className={btn("secondary", "sm", "shrink-0")}><History size={15} aria-hidden="true" /><span className="hidden sm:inline">Sincronizações</span></button></div><form role="search" onSubmit={(event) => { event.preventDefault(); const text = query.trim(); setSearchTerm(text); }} className="relative mt-3"><label htmlFor="library-search" className="sr-only">Buscar arquivos e pastas por nome</label><Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" /><input id="library-search" type="text" autoComplete="off" value={query} onChange={(event) => { const next = event.target.value; setQuery(next); if (next.trim().length < 2 && searchTerm) { setSearchTerm(""); } }} onKeyDown={(event) => { if (event.key === "Escape" && query) { event.preventDefault(); clearSearch(); } }} maxLength={500} placeholder="Buscar pelo nome em toda a biblioteca" className="w-full min-w-0 rounded-md border border-line py-2.5 pl-9 pr-11 text-sm" />{searchTerm && loading ? <Spinner size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground" /> : query && <button type="button" onClick={clearSearch} aria-label="Limpar busca" title="Limpar busca (Esc)" className="absolute right-0.5 top-1/2 grid size-10 -translate-y-1/2 place-items-center rounded-md text-muted-foreground hover:text-ink"><X size={16} aria-hidden="true" /></button>}</form><p className="sr-only" role="status" aria-live="polite">{searchTerm && !loading && !loadError ? (items.length === 0 ? "Nenhum resultado encontrado." : `${items.length} ${(items.length) === 1 ? "resultado" : "resultados"} para ${searchTerm}.`) : ""}</p>{searchTerm && <p className="mt-2 text-xs text-muted-foreground">Busca por nome em todas as fontes conectadas.</p>}
      {spaceFilter.spaces && spaceFilter.spaces.length > 1 && <div className="flex flex-wrap items-start gap-2"><div className="min-w-0 flex-1"><SpaceChips spaces={spaceFilter.spaces} selected={spaceFilter.selected} onChange={spaceFilter.change} /></div>{(current || searchTerm) && <SpaceGroupToggle pressed={view.groupBySpace} onToggle={() => changeView({ ...view, groupBySpace: !view.groupBySpace })} />}</div>}
      {syncStatus.error && hasTools && <p role="alert" className="mt-3 text-sm text-amber-800">{syncStatus.error} <button type="button" onClick={syncStatus.refresh} className="underline">Tentar novamente</button></p>}
      {selectedSync && (isActive(selectedSync) || selectedSync.state === "failed" || selectedSync.state === "partial_failure") && <div className="library-tool-sync" role="status" aria-label={`Sincronização de ${toolLabel(selectedSync.provider)}`}>
        {isActive(selectedSync) ? <>
          <p><b>{toolLabel(selectedSync.provider)}</b> · {progressView(selectedSync).text}</p>
          <div className="library-tool-progress" role="progressbar" aria-label={`Progresso de ${toolLabel(selectedSync.provider)}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={syncPercent(selectedSync) ?? undefined} aria-valuetext={progressView(selectedSync).speech} data-indeterminate={selectedSync.total <= 0}><span style={{ width: selectedSync.total > 0 ? `${syncPercent(selectedSync)}%` : "35%" }} /></div>
        </> : <p>{errorMessage(selectedSync)} {canManage ? <button type="button" onClick={onConnect} className="font-semibold text-primary underline">Revisar em Integrações</button> : "Peça a um administrador para revisar a ferramenta."}</p>}
      </div>}
      {(loading && items.length === 0) || syncStatus.loading && !hasTools ? <LibraryLoadingSkeleton view={view} /> : loadError && items.length === 0 ? <ErrorState className="library-empty-state" icon={<CircleAlert size={22} />} title={loadError} actions={<button onClick={loadItems} className="mo-interactive text-sm font-semibold text-primary underline">Tentar novamente</button>} /> : items.length === 0 ? <EmptyState className="library-empty-state" icon={<FolderOpen size={22} />} title={searchTerm ? "Nenhum resultado encontrado" : spaceEmpty ? spaceEmpty.title : syncStatus.anySyncing && (!current || selectedSync && isActive(selectedSync)) ? "Sincronizando…" : current ? "Esta pasta está vazia" : hasTools ? selectedSync ? "Conteúdo ainda indisponível" : "Escolha uma ferramenta" : syncStatus.error ? "Não foi possível consultar as ferramentas" : "Sua biblioteca começa aqui"} description={searchTerm ? "Tente uma palavra diferente ou parte do nome do arquivo." : spaceEmpty ? spaceEmpty.description : syncStatus.anySyncing && (!current || selectedSync && isActive(selectedSync)) ? "As pastas aparecem conforme os arquivos ficam prontos." : current ? "Nenhum arquivo disponível nesta pasta." : hasTools ? selectedSync ? "Confira o estado da ferramenta acima. Os arquivos aparecem aqui quando estiverem disponíveis." : "Selecione uma ferramenta na barra lateral para explorar seus arquivos e pastas." : syncStatus.error ? "Tente atualizar a biblioteca para conferir suas ferramentas conectadas." : canManage ? "Conecte uma fonte e escolha as pastas que sua equipe pode consultar." : "Um administrador precisa conectar uma fonte e sincronizar as pastas da equipe."} actions={!current && !searchTerm && canManage && !hasTools && !syncStatus.error && <button onClick={onConnect} className={btn("primary", "md")}>Conectar uma fonte</button>} /> : view.mode === "grid" ? <LibraryGrid items={items} groupBySpace={view.groupBySpace} size={view.size} loading={loading} canManage={canManage} busyNodeId={busyNodeId} busyFileId={busyFileId} onOpen={openItem} onReprocessFile={(item) => { void reprocessFileNode(item); }} onRemoveFile={(item) => { void removeFileNode(item); }} onSyncFolder={(item) => { void reprocessFolderNode(item); }} onRemoveFolder={(item) => { void removeFolderNode(item); }} onAsk={(item) => router.push(chatMentionPath(company.id, item.id, spaceFilter.selected))} focusId={focusId} /> : <ul aria-busy={loading} className={`library-list-wrap mt-3 divide-y divide-line overflow-hidden rounded-lg border border-dialog-edge bg-raised transition-opacity ${loading ? "opacity-60" : ""}`} aria-label="Arquivos e pastas">{withSpaceHeadings(items, view.groupBySpace).map((entry, index) => { if (entry.type === "heading") return <li key={entry.key} className="library-group-heading">{entry.label}<span>{entry.count} {entry.count === 1 ? "item" : "itens"}</span></li>; const item = entry.item; const isFolder = item.kind !== "file"; const indexed = item.kind === "file" && (item.workspace_documents?.length ?? 0) > 0; const busy = busyNodeId === item.id; return <li key={entry.key} style={staggerStyle(index) as CSSProperties} className="library-file-row mo-stagger-item group flex min-h-11 flex-wrap items-center gap-1 px-2 py-1 hover:bg-sage/60"><button onClick={() => openItem(item)} className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-1 py-1 text-left"><span className={`grid size-8 shrink-0 place-items-center rounded-md ${isFolder ? "bg-sage-selected text-primary" : "bg-sage text-muted-foreground"}`}><LibraryNodeIcon item={item} size={16} /></span><span className="min-w-0 flex-1"><b className="block truncate text-sm font-medium text-ink">{item.name}</b><SpaceBadges spaces={item.spaces} /></span><span className="hidden shrink-0 text-xs text-muted-foreground sm:block">{item.kind === "file" ? (item.mime_type?.split("/").pop() ?? "Arquivo") : item.kind === "source" ? "Integração" : "Pasta"}</span>{isFolder ? <ChevronRight size={15} className="shrink-0 text-muted-foreground" aria-hidden="true" /> : item.source_url ? <ExternalLink size={14} className="shrink-0 text-muted-foreground" aria-hidden="true" /> : null}</button>{!isFolder && <div className="library-row-indexing"><LibraryIndexingBadge item={item} /></div>}{item.access_state && <div className="library-row-indexing"><LibraryAccessBadge item={item} /></div>}{canManage && item.kind === "file" && indexed && <button disabled={busyFileId !== null} onClick={() => { void reprocessFileNode(item); }} title="Reprocessar arquivo" aria-label={`Reprocessar ${item.name}`} className={btn("ghost", "icon", "shrink-0")}><RefreshCw size={15} aria-hidden="true" /></button>}{canManage && item.kind === "file" && indexed && <button disabled={busyFileId !== null} aria-busy={busyFileId === item.id} onClick={() => { void removeFileNode(item); }} title="Remover do índice" aria-label={`Remover ${item.name} do índice`} className={btn("danger-ghost", "icon", "shrink-0")}>{busyFileId === item.id ? <Spinner size={15} /> : <Trash2 size={15} aria-hidden="true" />}</button>}{item.kind === "folder" && <><button disabled={busyNodeId !== null} onClick={() => { void reprocessFolderNode(item); }} title="Sincronizar só o que mudou (incremental)" aria-label={`Sincronizar alterações da pasta ${item.name}`} className={btn("ghost", "icon", "shrink-0")}>{busy ? <Spinner size={15} /> : <RefreshCw size={15} aria-hidden="true" />}</button>{canManage && <button disabled={busyNodeId !== null} onClick={() => { void removeFolderNode(item); }} title="Remover pasta" aria-label={`Remover pasta ${item.name}`} className={btn("danger-ghost", "icon", "shrink-0")}><Trash2 size={15} aria-hidden="true" /></button>}</>}</li>; })}</ul>}{items.length > 0 && <><div ref={sentinel} aria-hidden="true" className="h-px shrink-0" /><div className="library-foot -mx-4 sm:-mx-5">
      {loadingMore ? <span role="status" aria-live="polite" className="inline-flex items-center gap-2"><Spinner size={16} /><span>Carregando mais arquivos e pastas…</span></span> : loadError ? <div role="alert">{loadError}<button type="button" onClick={loadMore} className="ml-2 cursor-pointer font-semibold text-primary underline">Tentar novamente</button></div> : hasMore ? <button type="button" onClick={loadMore} className="cursor-pointer font-semibold text-primary underline">Carregar mais</button> : <p role="status">Todos os itens foram carregados.</p>}
    </div></>}</main></div></div><dialog ref={syncDialog} onClose={() => setSpacesPanelOpen(false)} onCancel={(event) => { event.preventDefault(); closeSpacesPanel(); }} aria-labelledby="library-sync-title" className="library-sync-dialog" data-arquivio-motion-root=""><section className="p-5 sm:p-6" data-arquivio-motion="panel"><div className="flex items-start justify-between gap-4"><div><h2 id="library-sync-title" className="text-xl font-semibold text-ink">Sincronizações</h2><p className="mt-1 text-sm text-muted-foreground">Acompanhe o histórico e gerencie suas pastas conectadas.</p></div><button onClick={closeSpacesPanel} className={btn("ghost", "icon", "shrink-0")} aria-label="Fechar sincronizações"><X size={18} /></button></div><div className="mt-6 flex items-center justify-between"><h3 className="text-sm font-semibold">Histórico de sincronizações</h3><button onClick={() => { loadHistory(); loadFolders(); }} aria-label="Atualizar sincronizações" className="grid size-10 place-items-center rounded-lg hover:bg-sage"><RefreshCw size={15} /></button></div><p className="text-xs text-muted-foreground">Sincronizações e ressincronizações, incluindo subpastas. O histórico atualiza a cada 3 segundos.</p>{syncHistoryError && <p role="alert" className="mt-3 text-sm text-rose-700">{syncHistoryError}</p>}<div aria-live="polite" className="mt-3 space-y-3">{manualSyncs.length === 0 ? <p className="rounded-lg border border-dashed border-line p-4 text-sm text-muted-foreground">Nenhuma sincronização registrada.</p> : manualSyncs.map((run, runIndex) => <article key={run.id} style={staggerStyle(runIndex) as CSSProperties} className="library-sync-run rounded-lg border border-line bg-panel p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-[11px] uppercase tracking-wide text-muted-foreground">{run.operation === "sync" ? "Sincronização" : "Ressincronização"}{run.mode && <> · <b className="font-semibold">{run.mode === "full" ? "Completa" : "Incremental"}</b></>} · {run.scope_kind === "source" ? "Integração" : run.scope_kind === "folder" ? "Pasta e subpastas" : "Pasta conectada sincronizada"}</p><h4 className="mt-1 font-semibold text-ink">{run.scope_name}</h4></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${run.status === "ready" ? "bg-emerald-100 text-emerald-800" : run.status === "failed" ? "bg-rose-100 text-rose-800" : run.status === "partial_failure" ? "bg-amber-100 text-amber-800" : "bg-sage text-primary"}`}>{{ queued: "Na fila", syncing: "Rodando", ready: "Concluído", failed: "Falhou", partial_failure: "Parcial" }[run.status] ?? run.status}</span></div><p className="mt-2 break-all text-xs text-muted-foreground">{run.triggered_by ? `Disparado por ${run.triggered_by}` : "Sincronização da pasta conectada"} · {new Date(run.created_at).toLocaleString("pt-BR")}</p><p className="mt-1 text-xs text-muted-foreground">Início: {run.started_at ? new Date(run.started_at).toLocaleString("pt-BR") : "Aguardando"} · Fim: {run.completed_at ? new Date(run.completed_at).toLocaleString("pt-BR") : "—"}</p><p className="mt-3 text-xs font-medium text-ink">{run.total === null ? "Contagem de arquivos indisponível para esta sincronização." : <>{run.processed} de {run.total} arquivos processados · {run.failed} falhas{(run.skipped ?? 0) > 0 ? ` · ${run.skipped} ignorados` : ""}{run.status === "syncing" && run.total === 0 ? " · Descobrindo arquivos…" : ""}</>}</p>{run.total !== null && run.total > 0 && <ProgressIndicator label={`Progresso de ${run.scope_name}`} value={(run.processed ?? 0) / run.total * 100} className="mt-2" />}{run.failures.length > 0 && <details className="mt-3 text-xs text-rose-800"><summary className="cursor-pointer font-semibold">Falhas por documento ({run.failed})</summary><ul className="mt-2 space-y-2">{run.failures.map((file) => <li key={file.external_id} className="break-words">{file.name} · {documentFailureLabel(file.error_code)} ({file.error_code})</li>)}</ul></details>}{(run.skipped ?? 0) > 0 && <details className="mt-3 text-xs text-muted-foreground"><summary className="cursor-pointer font-medium">{run.skipped} {run.skipped === 1 ? "arquivo ignorado" : "arquivos ignorados"}{(run.skipped_items ?? []).length > 0 && (run.skipped_items ?? []).every((file) => file.reason === "empty_content") ? " (vazios)" : ""}</summary>{(run.skipped_items ?? []).length > 0 && <ul className="mt-2 space-y-1">{(run.skipped_items ?? []).map((file, index) => <li key={`${file.name}-${index}`} className="break-words">{file.name} · {skippedReasonLabel(file.reason)}</li>)}</ul>}{(run.skipped_items ?? []).length > 0 && (run.skipped_items ?? []).length < (run.skipped ?? 0) && <p className="mt-1">Mostrando {(run.skipped_items ?? []).length} de {run.skipped}.</p>}</details>}{run.tasks.some((task) => task.error_code) && <ul className="mt-3 space-y-1 text-xs text-rose-700">{run.tasks.filter((task) => task.error_code).map((task, index) => <li key={index}>{task.workspace_name}: {task.error_code}</li>)}</ul>}</article>)}</div><h3 className="mt-7 text-sm font-semibold">Pastas conectadas</h3><p className="mt-1 text-xs text-muted-foreground">Gerencie o índice local de cada pasta conectada.</p><div className="mt-4 space-y-3">{foldersLoading && folders.length === 0 ? <LoadingBlock label="Carregando pastas conectadas…" className="rounded-md border border-dashed p-4"><SkeletonList rows={2} avatar={false} /></LoadingBlock> : folders.length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">Nenhuma pasta conectada.</p> : folders.map((folder) => <article key={folder.id} className="rounded-lg border border-line bg-panel p-4"><div className="flex items-start justify-between gap-2"><b className="min-w-0 truncate text-sm text-ink">{folder.name}</b><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${folderSyncActive(folder.id) ? "bg-sage-selected text-primary" : folder.status === "ready" ? "bg-emerald-100 text-emerald-800" : folder.status === "partial_failure" ? "bg-amber-100 text-amber-800" : "bg-sage-selected text-primary"}`}>{(folderSyncActive(folder.id) || folder.status === "queued" || folder.status === "syncing") && <Spinner size={11} className="mr-1 inline" />}{folderSyncActive(folder.id) ? "Sincronizando" : statusLabel(folder.status)}</span></div><p className="mt-2 text-xs text-muted-foreground">{folder.last_synced_at ? `Última sincronização: ${new Date(folder.last_synced_at).toLocaleString("pt-BR")}` : "Ainda não sincronizado"}</p><p role="status" aria-live="polite" className="mt-2 text-xs font-medium text-primary">{folderSyncActive(folder.id) ? `${folderSyncAnnouncements[folder.id] ?? "Sincronização em andamento."} A exclusão dos dados locais ficará disponível quando a operação terminar.` : folderSyncAnnouncements[folder.id] ?? ""}</p>{canManage && folder.status === "partial_failure" && <section className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3" aria-label={`Falhas da pasta ${folder.name}`}><p className="text-xs font-semibold text-amber-900">Arquivos com falha</p>{failureLoadError[folder.id] ? <p className="mt-2 text-xs text-amber-900">Não foi possível carregar os detalhes. Atualize as pastas conectadas e tente novamente.</p> : documentFailures[folder.id] ? documentFailures[folder.id].length === 0 ? <p className="mt-2 text-xs text-amber-900">Nenhuma falha de arquivo encontrada.</p> : <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto">{documentFailures[folder.id].map((file) => <li key={file.id} className="border-t border-amber-200 pt-2"><p className="break-words text-xs font-medium text-ink">{file.name}</p><p className="mt-0.5 text-[11px] text-amber-900">{documentFailureLabel(file.error_code)} <code>({file.error_code ?? "sem código"})</code></p></li>)}</ul> : <p role="status" className="mt-2 text-xs text-amber-900">Carregando detalhes…</p>}</section>}{folderActionErrors[folder.id] && <div role="alert" className="library-space-error mt-3"><CircleAlert size={15} aria-hidden="true" /><p>{folderActionErrors[folder.id]}</p></div>}{canManage && <div className="library-space-actions mt-4"><button disabled={busyFolderId !== null || Boolean(folderSyncActive(folder.id)) || folder.status === "queued" || folder.status === "syncing"} aria-busy={busyFolderId === folder.id && busyFolderAction === "sync"} onClick={() => { void syncFolder(folder); }} className={btn("secondary", "sm", "flex-1")}>{busyFolderId === folder.id && busyFolderAction === "sync" ? <Spinner size={14} /> : <RefreshCw size={14} aria-hidden="true" />}{busyFolderId === folder.id && busyFolderAction === "sync" ? "Iniciando…" : folderSyncActive(folder.id) || folder.status === "queued" || folder.status === "syncing" ? "Sincronizando…" : "Ressincronizar"}</button><button disabled={busyFolderId !== null || Boolean(folderSyncActive(folder.id)) || folder.status === "queued" || folder.status === "syncing"} onClick={() => { void removeFolder(folder); }} className={btn("danger-ghost", "sm", "flex-1")} title={folderSyncActive(folder.id) || folder.status === "queued" || folder.status === "syncing" ? "Aguarde o fim da sincronização para excluir os dados locais" : "Excluir pasta conectada e dados locais"} aria-busy={busyFolderId === folder.id && busyFolderAction === "remove"}>{busyFolderId === folder.id && busyFolderAction === "remove" ? <Spinner size={14} /> : <Trash2 size={14} aria-hidden="true" />}{busyFolderId === folder.id && busyFolderAction === "remove" ? "Excluindo…" : "Excluir dados locais"}</button></div>}</article>)}</div></section></dialog></>;
}
