"use client";

import { ChevronRight, ExternalLink, FileText, HelpCircle, History, RefreshCw, Send, Sparkles, ThumbsUp, ThumbsDown } from "lucide-react";
import { useRouter } from "next/navigation";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { type OnboardingState } from "../organization-onboarding";
import { ConversationTour } from "../conversation-tour";
import { AnswerActions } from "../answer-actions";
import { clickUpConnected } from "../clickup-task-logic";
import { AnswerMarkdown } from "../answer-markdown";
import { REVEAL_MAX_MS, useAnswerReveal } from "../answer-reveal";
import { SourceReadingStatus, type EvidenceCitation } from "../source-reading";
import { FileViewerHost, type ViewerCitation, type ViewerTarget } from "../file-viewer";
import { HIGHLIGHT_MS, type SourceHighlight, citationTarget, highlightAnnouncement, isHighlighted, nextHighlight } from "../file-viewer-logic";
import { QuestionScopePicker, contextReady, toolLabel, providerKey } from "../question-scope";
import { SyncIndicator, useSyncStatus } from "../sync-status";
import { ToolsSidebar, useToolsSidebarCollapsed } from "../tools-sidebar";
import { MentionComposer, type MentionCandidate } from "../mention-composer";
import { mentionSummary } from "../mention-label";
import { FollowToggle } from "./follow-toggle";
import { usageLimitMessage } from "./usage-limit";
import { type Company, type LibraryNode, type LibraryPage, type LibraryContext, type LibrarySync, type SavedQuery, type Evidence, type Answer, type ConversationMessage as BaseConversationMessage, type PersistedConversationMessage as BasePersistedConversationMessage, api, messageFor, useLatestRequest, answerText, citationSourceKey, compactCitations, libraryPath } from "./types-and-api";
import { NewConversationButton } from "./shared-ui";
import { ConversationHistory } from "./conversation-history";

type ConversationMessage = BaseConversationMessage & { feedback?: "up" | "down"; persisted?: boolean; fresh?: boolean };
type PersistedConversationMessage = Omit<BasePersistedConversationMessage, "context"> & {
  context: (NonNullable<BasePersistedConversationMessage["context"]> & { feedback?: { vote: "up" | "down" } }) | null;
};

function restoredMessages(messages: PersistedConversationMessage[]): ConversationMessage[] {
  let previousProviders: string[] = [];
  return messages.map((message) => {
    const providers = message.context?.providers ?? (message.role === "assistant" ? previousProviders : []);
    if (message.role === "user") previousProviders = providers;
    const contextName = providers.length > 0 ? providers.map(toolLabel).join(", ") : "Todas as ferramentas";
    return message.role === "assistant"
      ? { id: message.id, role: "assistant", content: message.content, contextName, providers, persisted: true, feedback: message.context?.feedback?.vote, answer: message.response ? { ...message.response, citations: compactCitations(message.response.citations ?? []) } : undefined }
      : { id: message.id, role: "user", content: message.content, contextName, providers, mentions: message.context?.mentions, allTools: providers.length === 0 };
  });
}

export function CompanyDashboard({ company, onboarding, onOnboardingChange, onConnect, setError, setNotice }: { company: Company; onboarding: OnboardingState; onOnboardingChange: (state: OnboardingState) => void; onConnect: () => void; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [replayTour, setReplayTour] = useState(false);
  return <><ConversationLibraryWorkspace key={company.id} company={company} onConnect={onConnect} onShowTour={() => setReplayTour(true)} setError={setError} setNotice={setNotice} />
    {(onboarding.tour_required || replayTour) && <ConversationTour key={`tour-${company.id}`} onComplete={async (exit) => {
      const firstTime = onboarding.tour_required;
      try {
        const progress = await api<OnboardingState>(`/organizations/${company.id}/onboarding/tour/complete`, { method: "POST" });
        onOnboardingChange(progress); setReplayTour(false);
        // Finishing the first-time tour hands the user the composer; closing/cancelling always returns to the trigger.
        window.requestAnimationFrame(() => {
          const visible = (element: HTMLElement | null) => element && element.getClientRects().length > 0 ? element : null;
          const composer = document.querySelector<HTMLTextAreaElement>('[data-tour="composer"] textarea');
          const target = exit === "finished" && firstTime ? composer : visible(document.querySelector<HTMLElement>('button[aria-label="Rever tour do app"]')) ?? visible(document.querySelector<HTMLElement>('button[aria-label="Abrir menu"]')) ?? composer;
          target?.focus();
        });
      } catch (caught) { throw new Error(messageFor(caught)); }
    }} />}
  </>;
}

function ConversationLibraryWorkspace({ company, onConnect, onShowTour, setError, setNotice }: { company: Company; onConnect: () => void; onShowTour: () => void; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const router = useRouter();
  const { collapsed: toolsCollapsed, toggle: toggleTools } = useToolsSidebarCollapsed();
  const syncStatus = useSyncStatus(company.id);
  const [roots, setRoots] = useState<LibraryNode[]>([]);
  const [contexts, setContexts] = useState<LibraryContext[]>([]);
  const [syncs, setSyncs] = useState<LibrarySync[]>([]);
  const { request: requestLibrary } = useLatestRequest<LibraryPage>();
  const { request: requestContexts } = useLatestRequest<{ items: LibraryContext[] }>();
  const { request: requestSyncs } = useLatestRequest<{ items: LibrarySync[] }>();
  const [contextLoading, setContextLoading] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedByMessage, setSavedByMessage] = useState<Record<string, SavedQuery & { followed?: boolean }>>({});
  const syncWasActive = useRef(false);
  const previousSyncStatuses = useRef(new Map<string, string>());
  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [allTools, setAllTools] = useState(true);
  const [queryProviders, setQueryProviders] = useState<string[]>([]);
  const [mentions, setMentions] = useState<MentionCandidate[]>([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [restoringConversation, setRestoringConversation] = useState(true);
  const [asking, setAsking] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [viewerTarget, setViewerTarget] = useState<ViewerTarget | null>(null);
  const viewerTrigger = useRef<HTMLElement | null>(null);
  const panelsRef = useRef<HTMLDivElement>(null);
  const openFile = useCallback((citation: ViewerCitation, number: number) => {
    if (document.activeElement instanceof HTMLElement && !viewerTarget) viewerTrigger.current = document.activeElement;
    setViewerTarget({ citation, number });
  }, [viewerTarget]);
  const closeViewer = useCallback(() => {
    setViewerTarget(null);
    const trigger = viewerTrigger.current;
    viewerTrigger.current = null;
    if (trigger?.isConnected) window.requestAnimationFrame(() => trigger.focus({ preventScroll: true }));
  }, []);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const conversationEpoch = useRef(0);
  const askSequence = useRef(0);
  const revealWaiters = useRef(new Map<string, () => void>());
  const followTranscript = useRef(true);
  const canManage = company.role !== "member";
  const mentionsOutsideSelection = mentions.filter((item) => !allTools && !queryProviders.includes(providerKey(item.source_provider)));
  const syncInProgress = syncs.some((item) => item.status === "queued" || item.status === "syncing");
  const canAsk = !restoringConversation && !contextLoading && !contextError && mentionsOutsideSelection.length === 0 && (allTools || queryProviders.length > 0) && contexts.some((item) => contextReady(item) && (allTools || queryProviders.includes(providerKey(item.source_provider))));

  const overviewProviders = allTools ? "" : [...queryProviders].sort().join(",");
  useEffect(() => {
    if (!canAsk) return;
    let cancelled = false;
    const query = overviewProviders ? overviewProviders.split(",").map((value) => `providers=${encodeURIComponent(value)}`).join("&") : "";
    void api<{ suggested_questions: string[] }>(`/organizations/${company.id}/library/overview${query ? `?${query}` : ""}`)
      .then((overview) => { if (!cancelled) setSuggestions(overview.suggested_questions); })
      .catch(() => { if (!cancelled) setSuggestions([]); });
    return () => { cancelled = true; };
  }, [canAsk, company.id, overviewProviders]);
  const loadLibrary = useCallback(() => {
    void requestLibrary(`/library?organization_id=${company.id}`, (result) => setRoots(result.items), () => undefined);
  }, [company.id, requestLibrary]);
  const loadOperations = useCallback((refreshContexts: "visible" | "silent" | "none" = "visible") => {
    if (refreshContexts !== "none") {
      const showLoading = refreshContexts === "visible";
      if (showLoading) setContextLoading(true);
      setContextError(null);
      void requestContexts(`/library/question-contexts?organization_id=${company.id}`, (result) => setContexts(result.items), (caught) => setContextError(messageFor(caught)), () => setContextLoading(false));
    }
    void requestSyncs(`/library/syncs?organization_id=${company.id}`, (result) => setSyncs(result.items), (caught) => setError(messageFor(caught)));
  }, [company.id, requestContexts, requestSyncs, setError]);
  useEffect(() => { void Promise.resolve().then(loadLibrary); }, [loadLibrary]);
  useEffect(() => { void Promise.resolve().then(() => loadOperations()); }, [loadOperations]);
  useEffect(() => {
    const key = `arquivio:conversation:${company.id}`;
    const stored = window.sessionStorage.getItem(key);
    const epoch = ++conversationEpoch.current;
    queueMicrotask(() => {
      if (conversationEpoch.current !== epoch) return;
      if (!stored) {
        setConversationId(null);
        setMessages([]);
        setRestoringConversation(false);
        return;
      }
      void api<{ id: string; messages: PersistedConversationMessage[] }>(
        `/organizations/${company.id}/conversations/${stored}`
      ).then((conversation) => {
        if (conversationEpoch.current !== epoch) return;
        setConversationId(conversation.id);
        setMessages(restoredMessages(conversation.messages));
      }).catch(() => {
        if (conversationEpoch.current !== epoch) return;
        window.sessionStorage.removeItem(key);
        setConversationId(null);
        setMessages([]);
      }).finally(() => {
        if (conversationEpoch.current === epoch) setRestoringConversation(false);
      });
    });
  }, [company.id]);
  function openConversation(id: string) {
    if (asking || id === conversationId) { setHistoryOpen(false); return; }
    const epoch = ++conversationEpoch.current;
    askSequence.current += 1;
    setViewerTarget(null);
    setRestoringConversation(true);
    void api<{ id: string; messages: PersistedConversationMessage[] }>(`/organizations/${company.id}/conversations/${id}`).then((conversation) => {
      if (conversationEpoch.current !== epoch) return;
      window.sessionStorage.setItem(`arquivio:conversation:${company.id}`, conversation.id);
      setConversationId(conversation.id);
      setMessages(restoredMessages(conversation.messages));
      setHistoryOpen(false);
    }).catch((caught) => { if (conversationEpoch.current === epoch) setError(messageFor(caught)); })
      .finally(() => { if (conversationEpoch.current === epoch) setRestoringConversation(false); });
  }
  function conversationDeleted(id: string) {
    if (id !== conversationId) return;
    conversationEpoch.current += 1;
    askSequence.current += 1;
    setViewerTarget(null);
    window.sessionStorage.removeItem(`arquivio:conversation:${company.id}`);
    setConversationId(null);
    setMessages([]);
  }
  function startNewConversation() {
    if (asking) return;
    conversationEpoch.current += 1;
    setViewerTarget(null);
    window.sessionStorage.removeItem(`arquivio:conversation:${company.id}`);
    setConversationId(null);
    setMessages([]);
    setRestoringConversation(false);
    setQuestion("");
    setMentions([]);
    composerRef.current?.focus();
  }
  useEffect(() => {
    let aSyncFinished = false;
    for (const item of syncs) {
      const previous = previousSyncStatuses.current.get(item.id);
      const wasActive = previous === "queued" || previous === "syncing";
      const isActive = item.status === "queued" || item.status === "syncing";
      if (wasActive && !isActive) aSyncFinished = true;
      previousSyncStatuses.current.set(item.id, item.status);
    }
    if (aSyncFinished && syncs.some((item) => item.status === "queued" || item.status === "syncing")) void Promise.resolve().then(() => loadOperations("silent"));
  }, [loadOperations, syncs]);
  useEffect(() => {
    const isActive = syncs.some((item) => item.status === "queued" || item.status === "syncing");
    if (!isActive) {
      if (syncWasActive.current) { syncWasActive.current = false; void Promise.resolve().then(() => loadOperations()); }
      return;
    }
    syncWasActive.current = true;
    const timer = window.setInterval(() => { loadOperations("none"); loadLibrary(); }, 5000);
    return () => window.clearInterval(timer);
  }, [loadOperations, loadLibrary, syncs]);
  useEffect(() => { const transcript = transcriptRef.current; if (transcript) { followTranscript.current = true; transcript.scrollTop = transcript.scrollHeight; } }, [messages]);
  // While an answer is being revealed the list does not change, so the transcript follows the text unless the reader scrolled up.
  const followReveal = useCallback(() => { const transcript = transcriptRef.current; if (transcript && followTranscript.current) transcript.scrollTop = transcript.scrollHeight; }, []);
  const revealFinished = useCallback((id: string) => { revealWaiters.current.get(id)?.(); }, []);
  async function saveQuestion(message: ConversationMessage) {
    if (!message.contextId || saving) return;
    setSaving(true);
    try { const saved = await api<SavedQuery & { followed?: boolean }>(`/workspace-folders/${message.contextId}/saved-queries?organization_id=${company.id}`, { method: "POST", body: JSON.stringify({ name: message.content.slice(0, 160), query: message.content, filters: {} }) }); setSavedByMessage((items) => ({ ...items, [message.id]: saved })); setNotice("Pergunta salva nesta pasta."); }
    catch (caught) { setError(messageFor(caught)); } finally { setSaving(false); }
  }
  async function restoreTranscript(savedConversationId: string, pendingId: string, requestEpoch: number, sequence: number) {
    await new Promise<void>((resolve) => {
      const timer = window.setTimeout(resolve, REVEAL_MAX_MS + 1500);
      revealWaiters.current.set(pendingId, () => { window.clearTimeout(timer); resolve(); });
    });
    revealWaiters.current.delete(pendingId);
    if (conversationEpoch.current !== requestEpoch || askSequence.current !== sequence) return;
    try {
      const saved = await api<{ messages: PersistedConversationMessage[] }>(`/organizations/${company.id}/conversations/${savedConversationId}`);
      if (conversationEpoch.current === requestEpoch && askSequence.current === sequence) setMessages(restoredMessages(saved.messages));
    } catch { /* Keep the delivered answer; feedback becomes available on successful restore. */ }
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    const submittedQuestion = question.trim();
    if (asking || !canAsk || !submittedQuestion) return;
    const requestId = crypto.randomUUID();
    const requestEpoch = conversationEpoch.current;
    const sequence = ++askSequence.current;
    const pendingId = `${requestId}:assistant`;
    const selectedProviders = allTools ? [...new Set(contexts.filter((item) => item.query_status === "ready" || item.query_status === "no_compatible_embeddings").map((item) => providerKey(item.source_provider)))] : [...queryProviders];
    const selectedMentions = [...mentions];
    const contextName = allTools ? "Todas as ferramentas" : selectedProviders.map(toolLabel).join(", ");
    const messageSnapshot = { providers: selectedProviders, mentions: selectedMentions, allTools, contextName };
    setMessages((items) => [
      ...items,
      { id: requestId, role: "user", content: submittedQuestion, ...messageSnapshot },
      { id: pendingId, role: "assistant", content: submittedQuestion, ...messageSnapshot, pending: true },
    ]);
    setQuestion("");
    setMentions([]);
    setAsking(true);
    try {
      const result = await api<Answer>(`/organizations/${company.id}/questions`, { method: "POST", body: JSON.stringify({ question: submittedQuestion, scope: "selection", providers: selectedProviders, mentions: selectedMentions.map((item) => ({ kind: item.kind, node_id: item.node_id, name: item.name })), conversation_id: conversationId }) });
      const answer = { ...result, citations: compactCitations(result.citations) };
      if (conversationEpoch.current !== requestEpoch) return;
      if (result.conversation_id) {
        setConversationId(result.conversation_id);
        window.sessionStorage.setItem(`arquivio:conversation:${company.id}`, result.conversation_id);
      }
      setMessages((items) => items.map((item) => item.id === pendingId ? { ...item, pending: false, fresh: true, answer } : item));
      // Refresh the canonical transcript once the answer finished appearing: never attach a vote to a temporary request UUID,
      // and never swap the list under a reveal in progress. A newer question or conversation supersedes this refresh.
      if (result.conversation_id) void restoreTranscript(result.conversation_id, pendingId, requestEpoch, sequence);
        } catch (caught) {
      if (conversationEpoch.current !== requestEpoch) return;
      const error = usageLimitMessage(caught) ?? messageFor(caught);
      setMessages((items) => items.map((item) => item.id === pendingId ? { ...item, pending: false, error } : item));
      setError(error);
    }
    finally { setAsking(false); }
  }
  return <><div className="workspace-frame chat-workspace overflow-hidden border border-line bg-panel">
    <div ref={panelsRef} className={`grid workspace-panels${toolsCollapsed ? " tools-collapsed" : ""}`}>
      <ToolsSidebar orgId={company.id} canManage={canManage} collapsed={toolsCollapsed} onToggle={toggleTools} tools={syncStatus.tools} loading={syncStatus.loading} libraryRoots={roots} onAdd={onConnect} onSelectTool={(tool) => router.push(libraryPath(company.id, tool.libraryNodeId))} />
      <main id="consultas" className="conversation-panel relative flex min-h-[560px] min-w-0 flex-col bg-panel">
        <div className="chat-topbar flex shrink-0 items-center justify-end gap-1 border-b border-line-soft bg-panel px-3 py-1.5 sm:px-5"><button type="button" onClick={() => setHistoryOpen((open) => !open)} aria-expanded={historyOpen} className="mr-auto inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground hover:bg-sage"><History size={16} aria-hidden="true" /><span className="hidden sm:inline">Conversas</span></button><SyncIndicator tools={syncStatus.tools} /><button type="button" onClick={onShowTour} className="inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2 text-xs text-muted-foreground hover:bg-sage" aria-label="Rever tour do app"><HelpCircle size={16} aria-hidden="true" /><span className="hidden sm:inline">Conhecer o app</span></button><NewConversationButton onClick={startNewConversation} disabled={asking} /></div>
        {historyOpen && <ConversationHistory organizationId={company.id} activeId={conversationId} refreshKey={conversationId} disabled={asking} onOpen={openConversation} onDeleted={conversationDeleted} onClose={() => setHistoryOpen(false)} />}
        <div ref={transcriptRef} onScroll={(event) => { const el = event.currentTarget; followTranscript.current = el.scrollHeight - el.scrollTop - el.clientHeight < 96; }} role="log" aria-label="Conversa com seus documentos" aria-live="polite" className="flex-1 overflow-y-auto px-5 py-6 sm:px-7">{messages.length > 0 ? <div className="mx-auto max-w-3xl space-y-5">{messages.map((message) => message.role === "user" ? <div key={message.id} className="ml-auto max-w-[85%]"><p className="mb-1 text-right text-xs font-medium text-muted-foreground">{message.contextName}</p><div className="conversation-question px-4 py-3 text-sm leading-6">{message.content}{Boolean(message.mentions?.length) && <span className="mt-2 block text-xs">{mentionSummary(message.mentions ?? [])}</span>}</div>{message.contextId && (savedByMessage[message.id] ? <div className="mt-1.5 flex items-center justify-end gap-2 text-xs text-muted-foreground">Pergunta salva<FollowToggle organizationId={company.id} savedQueryId={savedByMessage[message.id].id} followed={savedByMessage[message.id].followed ?? false} onError={setError} /></div> : <button disabled={saving} onClick={() => { void saveQuestion(message); }} className="mt-1.5 block ml-auto text-xs text-muted-foreground underline-offset-4 hover:underline disabled:opacity-40">Salvar pergunta</button>)}</div> : <article key={message.id} className="conversation-answer"><div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-sage-selected text-primary"><Sparkles size={15} /></span><div><p className="text-sm font-semibold text-ink">Arquivio</p><p className="text-xs text-muted-foreground">{message.contextName}</p></div></div>{(message.pending || (!message.error && message.answer && (message.fresh || Boolean(message.providers?.length)))) && <SourceReadingStatus providers={message.providers} reading={Boolean(message.pending)} />}{message.pending ? null : message.error ? <div className="mt-4 text-sm leading-6 text-rose-700"><p>Não foi possível concluir esta pergunta: {message.error}</p><button type="button" className="mt-2 min-h-11 underline" onClick={() => { setQuestion(message.content); setMentions(message.mentions ?? []); setAllTools(message.allTools ?? true); setQueryProviders(message.providers ?? []); composerRef.current?.focus(); }}>Repetir com este contexto</button></div> : message.answer ? <><AssistantAnswer onOpenFile={openFile} messageId={message.id} answer={message.answer} animate={Boolean(message.fresh)} onProgress={followReveal} onRevealed={() => revealFinished(message.id)} />
        {message.persisted && conversationId && message.answer?.answer && <AnswerActions organizationId={company.id} conversationId={conversationId} messageId={message.id} text={message.answer.answer} sources={message.answer.citations} clickUpEnabled={clickUpConnected(contexts)} />}
        {message.persisted && conversationId && <AnswerFeedback organizationId={company.id} conversationId={conversationId} messageId={message.id} initialVote={message.feedback} />}</> : null}</article>)}</div> : <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center py-16 text-center"><span className="grid size-12 place-items-center rounded-lg bg-sage text-primary"><Sparkles size={22} /></span><h2 className="mt-4 text-lg font-semibold text-ink">O que você quer descobrir?</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Pergunte sobre conteúdo indexado. Se quiser restringir a pergunta, escolha ferramentas abaixo ou mencione arquivos e pastas com @ ou /.</p>{canAsk && <div className="mt-6 flex flex-wrap justify-center gap-2">{(suggestions.length > 0 ? suggestions : ["Quais são os principais prazos?", "O que foi definido sobre as entregas?", "Quais são as responsabilidades da equipe?"]).map((prompt) => <button key={prompt} onClick={() => { setQuestion(prompt); setMentions([]); composerRef.current?.focus(); }} className="rounded-md border border-line px-3 py-2 text-xs text-muted-foreground hover:border-primary hover:bg-sage">{prompt}</button>)}</div>}</div>}</div>
        <form data-tour="composer" onSubmit={(event) => { void ask(event); }} className="conversation-composer shrink-0 bg-panel p-4 sm:px-7 sm:py-5">
          <div className="rounded-lg border border-line bg-panel p-2 shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-sage-selected">
            <MentionComposer organizationId={company.id} value={question} onChange={setQuestion} mentions={mentions} onMentionsChange={setMentions} all={allTools} providers={queryProviders} disabled={asking || restoringConversation} textareaRef={composerRef} onSubmit={() => composerRef.current?.form?.requestSubmit()} />
            <div className="composer-toolbar flex items-center justify-between gap-2 border-t border-line-soft px-2 pt-2">
              <div data-tour="tools"><QuestionScopePicker syncInProgress={syncInProgress || syncStatus.anySyncing} all={allTools} providers={queryProviders} contexts={contexts} loading={contextLoading} disabled={asking} error={contextError} onRetry={loadOperations} onChange={(all, providers) => { setAllTools(all); setQueryProviders(providers); }} /></div>
              <div className="flex shrink-0 items-center gap-2"><span className="text-xs text-muted-foreground">{question.length}/1000</span><button disabled={!canAsk || !question.trim() || asking} aria-label={asking ? "Consultando…" : "Enviar"} className="composer-send inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground hover:bg-forest-hover disabled:cursor-not-allowed disabled:opacity-40">{asking ? <RefreshCw size={15} className="motion-safe:animate-spin" aria-hidden="true" /> : <Send size={15} />}<span className="composer-send-label">{asking ? "Consultando…" : "Enviar"}</span></button></div>
            </div>
          </div>
          {mentionsOutsideSelection.length > 0 && <p role="alert" className="mt-2 text-xs text-amber-800">Marque {mentionsOutsideSelection.map((item) => toolLabel(item.source_provider)).join(", ")} ou remova a menção antes de enviar.</p>}
          <p className="mt-2 text-xs text-muted-foreground">@ menciona arquivos e pastas · / abre comandos.</p>
        </form>
      </main>
      <FileViewerHost organizationId={company.id} target={viewerTarget} panelsRef={panelsRef} onClose={closeViewer} />
    </div>
  </div></>;
}

function AnswerFeedback({ organizationId, conversationId, messageId, initialVote }: { organizationId: string; conversationId: string; messageId: string; initialVote?: "up" | "down" }) {
  const [vote, setVote] = useState(initialVote);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitting = useRef(false);
  async function submit(next: "up" | "down") {
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true); setError(null);
    try {
      await api(`/organizations/${organizationId}/conversations/${conversationId}/messages/${messageId}/feedback`, { method: "PUT", body: JSON.stringify({ vote: next }) });
      setVote(next);
    } catch (caught) { setError(messageFor(caught)); }
    finally { submitting.current = false; setBusy(false); }
  }
  return <div className="mt-3" aria-label="Avaliar resposta">
    <div className="flex items-center gap-1">{(["up", "down"] as const).map((value) => <button key={value} type="button" disabled={busy} aria-pressed={vote === value} aria-label={value === "up" ? "Resposta útil" : "Resposta não útil"} onClick={() => { void submit(value); }} className={`inline-flex min-h-11 min-w-11 items-center justify-center rounded-md hover:bg-sage disabled:opacity-40 ${vote === value ? "bg-sage-selected text-primary" : "text-muted-foreground"}`}>
      {value === "up" ? <ThumbsUp size={16} aria-hidden="true" /> : <ThumbsDown size={16} aria-hidden="true" />}
    </button>)}</div>
    {vote && !error && <p role="status" className="text-xs text-muted-foreground">Avaliação registrada.</p>}
    {error && <p role="alert" className="text-xs text-rose-700">Não foi possível registrar: {error}</p>}
  </div>;
}

function AssistantAnswer({ messageId, answer, animate, onProgress, onRevealed, onOpenFile }: { messageId: string; answer: Answer; animate: boolean; onProgress: () => void; onRevealed: () => void; onOpenFile: (citation: ViewerCitation, number: number) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [highlight, setHighlight] = useState<SourceHighlight>(null);
  const fullText = answerText(answer);
  const reveal = useAnswerReveal(fullText, animate, { onProgress, onDone: onRevealed });
  const sourceId = (number: number) => `source-${messageId}-${number}`;
  // The highlight lasts a few seconds, or until another [N] is picked.
  useEffect(() => {
    if (!highlight) return;
    const timer = window.setTimeout(() => setHighlight(null), HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [highlight]);
  // A [N] never opens anything: it only points at the matching file in this answer's source list.
  const pointToSource = (cited: number) => {
    const number = citationTarget(cited, answer.citations.length);
    if (number === null) return;
    setHighlight((current) => nextHighlight(current, number));
    setExpanded((open) => open || number > 3);
    // Wait for the expanded list to render before moving focus to the cited row.
    window.requestAnimationFrame(() => {
      const row = document.getElementById(sourceId(number));
      if (!row) return;
      row.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
      row.focus({ preventScroll: true });
    });
  };
  const settle = animate ? " answer-settle" : "";
  return <>
    {/* While the text is still arriving, assistive tech gets the whole answer once instead of every word. */}
    {!reveal.done && <p className="sr-only">{fullText}</p>}
    <div className={reveal.done ? undefined : "answer-revealing"} aria-hidden={reveal.done ? undefined : true} inert={!reveal.done}>
      <AnswerMarkdown text={reveal.text} fileNames={answer.citations.map((citation) => citation.document_name)} onCite={answer.citations.length > 0 ? pointToSource : undefined} />
    </div>
    {reveal.done && Boolean(answer.coverage?.pending_folders) && <p className={`mt-2 text-xs text-amber-800${settle}`}>Resposta baseada no que já foi sincronizado{answer.coverage!.total_folders > 0 ? ` — ${answer.coverage!.pending_folders} de ${Math.max(answer.coverage!.total_folders, answer.coverage!.pending_folders)} ${Math.max(answer.coverage!.total_folders, answer.coverage!.pending_folders) === 1 ? "pasta ainda está sincronizando" : "pastas ainda estão sincronizando"}` : ""}.</p>}
    {highlight && answer.citations[highlight.number - 1] && <p role="status" aria-live="polite" className="sr-only" key={highlight.nonce}>{highlightAnnouncement(highlight.number, answer.citations[highlight.number - 1].document_name)}</p>}
    {reveal.done && answer.citations.length > 0 && <div className={animate ? "answer-settle" : undefined}><SourceDocuments items={answer.citations} expanded={expanded} setExpanded={setExpanded} rowId={sourceId} highlight={highlight} onOpen={(number) => { setHighlight(null); onOpenFile(answer.citations[number - 1] as EvidenceCitation & ViewerCitation, number); }} /></div>}
  </>;
}

function SourceDocumentRow({ item, number, id, cited, onOpen }: { item: Evidence; number: number; id: string; cited: boolean; onOpen: (number: number) => void }) {
  return <li id={id} tabIndex={-1} aria-current={cited ? "true" : undefined} className={`source-row flex min-w-0 items-center gap-2 border-t border-line-soft first:border-t-0${cited ? " is-cited" : ""}`}>
    <button type="button" onClick={() => onOpen(number)} aria-label={`Visualizar arquivo ${number}: ${item.document_name}`} title="Visualizar arquivo" className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-md py-2.5 text-left hover:bg-sage focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
      <span className="w-5 shrink-0 text-right text-xs font-semibold text-primary">{number}.</span>
      <FileText size={15} className="shrink-0 text-primary" aria-hidden="true" />
      <span className="min-w-0 flex-1 break-words text-xs font-medium leading-5 text-ink">{item.document_name}</span>
      {item.source_provider && <span className="citation-tool mb-0 shrink-0">{toolLabel(item.source_provider)}</span>}
    </button>
    {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer" aria-label={`Abrir ${item.document_name} no original`} title="Abrir original" className="shrink-0 cursor-pointer rounded-md p-1.5 text-primary hover:bg-sage focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"><ExternalLink size={14} aria-hidden="true" /></a>}
  </li>;
}

function SourceDocuments({ items, expanded, setExpanded, rowId, highlight, onOpen }: { items: Evidence[]; expanded: boolean; setExpanded: (update: (open: boolean) => boolean) => void; rowId: (number: number) => string; highlight: SourceHighlight; onOpen: (number: number) => void }) {
  const remainingCount = Math.max(items.length - 3, 0);
  return <section className="mt-5 border-t border-line pt-4" aria-label="Documentos utilizados como fonte">
    <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fontes</h3>
    <ol>{items.slice(0, expanded ? undefined : 3).map((item, index) => <SourceDocumentRow key={citationSourceKey(item)} item={item} number={index + 1} id={rowId(index + 1)} cited={isHighlighted(highlight, index + 1)} onOpen={onOpen} />)}</ol>
    {remainingCount > 0 && <button type="button" onClick={() => setExpanded((open) => !open)} aria-expanded={expanded} className="flex items-center gap-1 border-t border-line-soft py-2 text-xs font-semibold text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
      {expanded ? "Mostrar menos" : `Ver mais ${remainingCount} ${remainingCount === 1 ? "documento" : "documentos"}`}
      <ChevronRight size={14} className={`transition-transform ${expanded ? "-rotate-90" : "rotate-90"}`} aria-hidden="true" />
    </button>}
  </section>;
}
