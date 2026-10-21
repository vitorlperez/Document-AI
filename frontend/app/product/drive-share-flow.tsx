"use client";

import { ArrowLeft, Check, ChevronRight, CircleAlert, Clock3, Copy, ExternalLink, FolderClosed, FolderOpen, Link2, RefreshCw, ShieldCheck, Trash2, Unplug, UserRound, X } from "lucide-react";
import { createPortal } from "react-dom";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ModalOverlay } from "../modal-dismiss";
import { ProviderLogo } from "../provider-logo";
import { Spinner, btn } from "../ui";
import { driveShareApi, type DriveShareApi, type InboxFolder, type DriveShareState, type ProvisionStatus } from "./drive-share-api";
import {
  ROBOT_RETIRED_MESSAGE, ROLE_HINT, SAMPLE_FOLDER_LINK, WORKSPACE_BLOCK_MESSAGE, POLL_INTERVAL_MS, batchRowView, batchSummary, connectLabel, formatCount, foundFoldersLabel, initialPollState, isSelected, itRequestText,
  canLink, defaultSpaceSelection, knownAncestors, nestedSeparationHint, nestedWarning, nestedWarningText, toggleSpace, parseDriveFolderLink, pollTick, relativeSync, resumePoll, retryableIds, selectedIds, syncTargets, toggleAll, unlinkConfirmCopy, unlinkedFolders, verifyErrorMessage,
  type BatchRow, type FolderLink, type LinkSpaceOption, type SelectionChoices,
} from "./drive-share-logic";
import { ApiError, messageFor, type Folder, type Source } from "./types-and-api";
import { DISCLOSURE_TEXT } from "./spaces-api";
import { driveCardActions, driveCardStatus, driveConnectionIssue, filterDriveFolders, summarizeDriveFolders, unifiedDriveFolders, type DriveMethodKey, type UnifiedFolder } from "./drive-unified-logic";
import "./drive-share-flow.css";

const DRIVE_HOME = "https://drive.google.com/";

// ---- copiar com fallback + aria-live ----

type CopyState = "idle" | "copied" | "manual";
/** `navigator.clipboard` → `execCommand` → seleção manual (o texto fica selecionado e o aviso pede Ctrl/⌘+C). */
export function useCopy(select?: () => HTMLInputElement | HTMLTextAreaElement | null) {
  const [state, setState] = useState<CopyState>("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const copy = useCallback(async (text: string) => {
    let next: CopyState = "manual";
    try { await navigator.clipboard.writeText(text); next = "copied"; } catch {
      const field = select?.();
      if (field) { field.focus(); field.select(); try { if (document.execCommand("copy")) next = "copied"; } catch { /* seleção manual */ } }
    }
    setState(next); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setState("idle"), next === "copied" ? 2500 : 6000);
  }, [select]);
  return { state, copy };
}

function CopyButton({ text, label = "Copiar", select, variant = "secondary", size = "md" }: { text: string; label?: string; select?: () => HTMLInputElement | HTMLTextAreaElement | null; variant?: "secondary" | "ghost"; size?: "md" | "sm" }) {
  const { state, copy } = useCopy(select);
  return <>
    <button type="button" className={btn(variant, size, "drive-copy-btn")} onClick={() => void copy(text)} data-copied={state === "copied" || undefined}>
      {state === "copied" ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}<span>{state === "copied" ? "Copiado" : label}</span>
    </button>
    <span className="sr-only" role="status" aria-live="polite">{state === "copied" ? "Copiado para a área de transferência." : state === "manual" ? "Não foi possível copiar automaticamente. O texto está selecionado: use Ctrl+C ou ⌘+C." : ""}</span>
    {state === "manual" && <span className="drive-copy-fallback" aria-hidden="true">Selecionado — use Ctrl/⌘ + C</span>}
  </>;
}

function RobotEmail({ email }: { email: string }) {
  const input = useRef<HTMLInputElement>(null);
  const id = useId();
  return <div className="drive-robot">
    <label htmlFor={id} className="sr-only">E-mail do ArquivIO para compartilhar a pasta</label>
    <div className="drive-robot-row">
      <input id={id} ref={input} readOnly value={email} className="drive-robot-input" onFocus={(event) => event.currentTarget.select()} spellCheck={false} />
      <CopyButton text={email} label="Copiar" select={() => input.current} />
    </div>
  </div>;
}

// ---- fluxo em 3 passos (várias pastas de uma vez) ----

type Step = 1 | 2 | 3;
type Robot = { sourceId: string; email: string };
const PROVISION_POLL_MS = 3000; const PROVISION_TIMEOUT_MS = 5 * 60_000;
const SYNC_CONCURRENCY = 3;
type BatchState = { phase: "running" | "done" | "failed"; ids: string[]; rows: BatchRow[]; failure: string | null };
export type DriveShareFlowProps = {
  organizationId: string; organizationName?: string; existingSource?: Pick<Source, "id"> | null;
  client?: DriveShareApi; onClose: () => void; onUseOAuth: () => void;
  /** Seletor de escopo pasta-a-pasta (continua disponível depois do lote). */
  onChooseScope: (sourceId: string) => void; onLinked?: () => void;
  /** "Ver na Biblioteca" no resumo final. */
  onOpenLibrary?: () => void;
  /** Só para testes/preview: força o passo inicial, a fonte e dados de exemplo. */
  preview?: { step: Step; robot: Robot; inbox?: InboxFolder[]; batch?: BatchState; noneFound?: boolean; choices?: SelectionChoices };
};

function Stepper({ step }: { step: Step }) {
  return <ol className="drive-stepper" aria-label={`Passo ${step} de 3`}>{[1, 2, 3].map((n) => <li key={n} data-state={n < step ? "done" : n === step ? "current" : "todo"} aria-current={n === step ? "step" : undefined}><span>{n < step ? <Check size={12} aria-hidden="true" /> : n}</span></li>)}</ol>;
}

export function DriveShareFlow({ organizationId, organizationName, existingSource, client = driveShareApi, onClose, onUseOAuth, onChooseScope, onLinked, onOpenLibrary, preview }: DriveShareFlowProps) {
  const [step, setStep] = useState<Step>(preview?.step ?? 1);
  const [robot, setRobot] = useState<Robot | null>(preview?.robot ?? null);
  const [enableError, setEnableError] = useState<string | null>(null);
  const [inbox, setInbox] = useState<InboxFolder[]>(preview?.inbox ?? []);
  const [extras, setExtras] = useState<InboxFolder[]>([]);
  const [choices, setChoices] = useState<SelectionChoices>(preview?.choices ?? {});
  const [poll, setPoll] = useState(initialPollState);
  const [checking, setChecking] = useState(false); const [noneFound, setNoneFound] = useState(preview?.noneFound ?? false);
  const [paste, setPaste] = useState(""); const [pasteError, setPasteError] = useState<string | null>(null); const [pasteChecking, setPasteChecking] = useState(false);
  const [batch, setBatch] = useState<BatchState | null>(preview?.batch ?? null);
  const [syncNote, setSyncNote] = useState("");
  // Espaços que verão as pastas ligadas. `null` = lista indisponível (o passo é omitido e o servidor usa o Espaço padrão).
  const [spaces, setSpaces] = useState<LinkSpaceOption[] | null>(null);
  const [spaceIds, setSpaceIds] = useState<string[]>([]);
  const [announce, setAnnounce] = useState("");

  const [pendingSource, setPendingSource] = useState<string | null>(null);
  const enabledOnce = useRef(false);
  const settle = useCallback((r: { source_id: string; robot_email: string | null; status?: ProvisionStatus }) => {
    if (r.status === "failed") { setEnableError("Não foi possível preparar o e-mail da sua empresa agora. Tente de novo em instantes."); return; }
    if (r.status === "provisioning" || !r.robot_email) { setPendingSource(r.source_id); return; }
    setPendingSource(null); setRobot({ sourceId: r.source_id, email: r.robot_email });
  }, []);
  const enable = useCallback(() => {
    setEnableError(null);
    if (existingSource) { client.state(existingSource.id).then((s) => settle({ source_id: existingSource.id, robot_email: s.robot_email, status: s.provision })).catch((e) => setEnableError(messageFor(e))); return; }
    client.enable(organizationId).then(settle).catch((e) => setEnableError(e instanceof ApiError && e.status === 403 ? "Só responsáveis e administradores configuram o acesso ao Google Drive." : messageFor(e)));
  }, [client, existingSource, organizationId, settle]);
  // Uma única chamada ao abrir (StrictMode/re-render não repetem); "Tentar de novo" chama enable() direto.
  useEffect(() => { if (preview || enabledOnce.current) return; enabledOnce.current = true; enable(); }, [enable, preview]);
  // Robô sob demanda: o worker cria o e-mail exclusivo (30–120 s no pior caso); poll leve até ficar pronto.
  useEffect(() => {
    if (!pendingSource || preview) return;
    let cancelled = false; const started = Date.now();
    const timer = window.setInterval(() => {
      void client.provisioning(pendingSource).then((r) => {
        if (cancelled) return;
        if (r.status === "ready" && r.robot_email) { settle(r); }
        else if (r.status === "failed") { setPendingSource(null); settle(r); }
        else if (Date.now() - started > PROVISION_TIMEOUT_MS) { setPendingSource(null); setEnableError("Está demorando mais que o normal para preparar o e-mail da sua empresa. Tente de novo em alguns minutos."); }
      }).catch(() => undefined);
    }, PROVISION_POLL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [pendingSource, client, settle, preview]);

  useEffect(() => {
    if (preview || !client.listSpaces) return;
    let alive = true;
    void client.listSpaces(organizationId).then((items) => { if (!alive || items.length === 0) return; setSpaces(items); setSpaceIds((current) => current.length ? current : defaultSpaceSelection(items)); }).catch(() => undefined);
    return () => { alive = false; };
  }, [client, organizationId, preview]);

  // Todas as pastas conhecidas (inbox + coladas por link); só as não vinculadas podem ser conectadas.
  const all = useMemo(() => [...inbox, ...extras.filter((e) => !inbox.some((f) => f.id === e.id))], [inbox, extras]);
  const folders = useMemo(() => unlinkedFolders(all), [all]);
  const picked = useMemo(() => selectedIds(folders, choices), [folders, choices]);

  // Polling do inbox: 5 s, até 5 min, depois pausa (botão "Retomar"). A lista cresce ao vivo nos passos 1 e 2.
  const pollActive = robot !== null && step < 3 && poll.phase === "polling" && !preview;
  const lastCount = useRef(0);
  useEffect(() => {
    if (!pollActive || !robot) return;
    let cancelled = false;
    const tick = async () => {
      let found: InboxFolder[] | null = null;
      try { found = await client.inbox(robot.sourceId); } catch { /* falha de rede: tenta no próximo tick */ }
      if (cancelled) return;
      if (found) setInbox(found);
      setPoll((state) => pollTick(state, (found ?? []).some((f) => !f.linked)));
    };
    void tick();
    const timer = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [pollActive, robot, client]);
  // Anuncia só quando o total muda (leitor de tela não repete o mesmo número a cada 5 s).
  useEffect(() => {
    if (folders.length === lastCount.current) return;
    lastCount.current = folders.length; if (folders.length > 0) setNoneFound(false);
  }, [folders.length]);

  async function continueFromStepOne() {
    if (!robot) return;
    if (folders.length > 0) { setStep(2); return; }
    // Nada detectado ainda: verificação imediata antes de dizer que não encontramos.
    setChecking(true); setNoneFound(false);
    try {
      const found = await client.inbox(robot.sourceId);
      setInbox(found);
      if (found.some((f) => !f.linked)) setStep(2); else { setNoneFound(true); setAnnounce("Não encontramos nenhuma pasta compartilhada ainda."); }
    } catch { setNoneFound(true); } finally { setChecking(false); }
  }

  async function addPasted() {
    if (!robot) return;
    const parsed = parseDriveFolderLink(paste);
    if (parsed.kind === "invalid") { setPasteError(verifyErrorMessage(parsed.code, robot.email).title); return; }
    setPasteError(null); setPasteChecking(true);
    try {
      const res = await client.verify(robot.sourceId, paste.trim());
      if ((res.code === "ok" || res.code === "download_blocked_partial") && res.folder_id) {
        const id = res.folder_id;
        if (all.some((f) => f.id === id && f.linked)) { setPasteError("Essa pasta já está conectada."); return; }
        setExtras((list) => list.some((f) => f.id === id) ? list : [...list, { id, name: res.name ?? res.folder_name ?? "Pasta do Drive", shared_by_email: res.shared_by_email, via: "link" }]);
        setChoices((c) => ({ ...c, [id]: true })); setPaste(""); setAnnounce(`Pasta “${res.name ?? "do Drive"}” adicionada à lista.`);
      } else { const m = verifyErrorMessage(res.code, robot.email); setPasteError([m.title, m.hint].filter(Boolean).join(" ")); }
    } catch (error) {
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) { const m = verifyErrorMessage(error.status === 422 ? "invalid_link" : "not_shared", robot.email); setPasteError([m.title, m.hint].filter(Boolean).join(" ")); }
      else setPasteError(messageFor(error));
    } finally { setPasteChecking(false); }
  }

  /** Passo 3: verifica e conecta todas de uma vez; depois dispara a sincronização de cada pasta conectada. */
  async function connectSelected(ids: string[], previous: BatchRow[] = []) {
    if (!robot || ids.length === 0) return;
    setStep(3); setSyncNote("");
    setBatch({ phase: "running", ids: [...new Set([...previous.map((r) => r.folder_id), ...ids])], rows: previous, failure: null });
    try {
      const fresh = await client.linkBatch(robot.sourceId, ids, spaces ? spaceIds : undefined);
      const rows = [...previous.filter((r) => !ids.includes(r.folder_id)), ...fresh];
      setBatch((b) => ({ phase: "done", ids: b?.ids ?? ids, rows, failure: null }));
      const targets = syncTargets(fresh);
      const summary = batchSummary(rows);
      setAnnounce(summary.text);
      if (fresh.some((r) => r.status === "ok")) onLinked?.();
      if (targets.length > 0) {
        setSyncNote("Iniciando a sincronização das pastas…");
        const queue = [...targets];
        await Promise.all(Array.from({ length: Math.min(SYNC_CONCURRENCY, queue.length) }, async () => { for (let next = queue.shift(); next; next = queue.shift()) await client.startSync(next).catch(() => undefined); }));
        setSyncNote("Sincronização iniciada. Você pode fechar esta janela: o trabalho continua em segundo plano.");
      }
    } catch (error) { setBatch((b) => ({ phase: "failed", ids: b?.ids ?? ids, rows: previous, failure: messageFor(error) })); }
  }

  const busy = checking || pasteChecking || batch?.phase === "running";
  const titleId = "drive-share-title";
  const subtitle = step === 1 ? "Compartilhe as pastas com este e-mail" : step === 2 ? "Escolha as pastas" : batch?.phase === "done" ? "Pastas conectadas" : "Conectando as pastas";
  return <ModalOverlay onClose={onClose} busy={busy} labelledBy={titleId} className="integration-modal drive-share-modal aq-motion-overlay fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4">
    <section className="drive-share-panel max-w-2xl" data-arquivio-motion="panel-scale" data-step={step}>
      <header className="drive-share-head"><span className="drive-share-logo"><ProviderLogo provider="google" size={24} /></span><div className="min-w-0 flex-1"><h2 id={titleId} className="text-xl font-semibold text-ink">Compartilhar pastas com o ArquivIO</h2><p className="mt-1 text-sm text-muted-foreground">Passo {step} de 3 · {subtitle}</p></div><Stepper step={step} /><button type="button" onClick={onClose} disabled={busy} aria-label="Fechar" className={btn("ghost", "icon")}><X size={18} /></button></header>
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>

      {!robot && !enableError && <div className="drive-loading" role="status"><Spinner size={18} /><span>Preparando o e-mail exclusivo da sua empresa…</span></div>}
      {enableError && <div className="drive-alert" data-tone="error" role="alert"><CircleAlert size={18} aria-hidden="true" /><div><p className="font-semibold">Não foi possível preparar o acesso.</p><p>{enableError}</p><div className="mt-3 flex flex-wrap gap-2">{enableError !== ROBOT_RETIRED_MESSAGE && <button type="button" className={btn("secondary", "sm")} onClick={enable}><RefreshCw size={14} aria-hidden="true" />Tentar de novo</button>}<button type="button" className={btn("ghost", "sm")} onClick={onUseOAuth}>Usar “Entrar com a conta Google”</button></div></div></div>}

      {robot && step === 1 && <StepOne robot={robot.email} folders={folders} poll={poll} checking={checking} noneFound={noneFound} hasExisting={Boolean(existingSource)} onResume={() => setPoll(resumePoll)} onContinue={() => void continueFromStepOne()} onSkipToPick={() => setStep(2)} onPaste={() => setStep(2)} onUseOAuth={onUseOAuth} organizationName={organizationName} />}
      {robot && step === 2 && <StepTwo robot={robot.email} folders={folders} all={all} choices={choices} setChoices={setChoices} picked={picked.length} poll={poll} onResume={() => setPoll(resumePoll)} paste={paste} setPaste={(v) => { setPaste(v); setPasteError(null); }} pasteError={pasteError} pasteChecking={pasteChecking} onAddPasted={() => void addPasted()} spaces={spaces} spaceIds={spaceIds} setSpaceIds={setSpaceIds} onConnect={() => void connectSelected(picked)} onBack={() => setStep(1)} />}
      {robot && step === 3 && batch && <StepThree robot={robot.email} all={all} batch={batch} syncNote={syncNote} onRetryFailed={() => void connectSelected(retryableIds(batch.rows), batch.rows)} onRetryAll={() => void connectSelected(batch.ids)} onBack={() => { setStep(2); setBatch(null); }} onChooseScope={() => onChooseScope(robot.sourceId)} onOpenLibrary={onOpenLibrary} onDone={onClose} />}
    </section>
  </ModalOverlay>;
}

function WaitingLine({ poll, onResume }: { poll: ReturnType<typeof initialPollState>; onResume: () => void }) {
  return poll.phase === "polling"
    ? <p className="drive-waiting" role="status"><Spinner size={14} /><span>Aguardando você compartilhar… verificando a cada 5 s</span></p>
    : <p className="drive-waiting" data-paused><Clock3 size={14} aria-hidden="true" /><span>Pausamos a verificação automática.</span><button type="button" className={btn("secondary", "sm")} onClick={onResume}><RefreshCw size={14} aria-hidden="true" />Retomar</button></p>;
}

function WorkspaceHint({ robot, organizationName, onUseOAuth }: { robot: string; organizationName?: string; onUseOAuth: () => void }) {
  const text = itRequestText(robot, organizationName);
  return <div className="drive-alert" data-tone="warning" role="note"><CircleAlert size={18} aria-hidden="true" /><div><p>{WORKSPACE_BLOCK_MESSAGE}</p><div className="mt-3 flex flex-wrap gap-2"><CopyButton text={text} label="Copiar texto para o TI" size="sm" /><button type="button" className={btn("ghost", "sm")} onClick={onUseOAuth}>Usar “Entrar com a conta Google”</button></div></div></div>;
}

function StepOne({ robot, folders, poll, checking, noneFound, hasExisting, onResume, onContinue, onSkipToPick, onPaste, onUseOAuth, organizationName }: { robot: string; folders: InboxFolder[]; poll: ReturnType<typeof initialPollState>; checking: boolean; noneFound: boolean; hasExisting: boolean; onResume: () => void; onContinue: () => void; onSkipToPick: () => void; onPaste: () => void; onUseOAuth: () => void; organizationName?: string }) {
  return <div className="drive-step">
    <RobotEmail email={robot} />
    <p className="drive-note">Este e-mail é exclusivo da sua empresa. Ninguém mais o usa. <b className="drive-many">Você pode compartilhar quantas pastas quiser com o mesmo e-mail</b> — uma de cada vez ou todas em seguida.</p>
    <ol className="drive-instructions">
      <li><span>Abra o Google Drive em outra aba.</span><a className={btn("secondary", "sm")} href={DRIVE_HOME} target="_blank" rel="noopener noreferrer">Abrir o Google Drive<ExternalLink size={14} aria-hidden="true" /></a></li>
      <li><span>Clique com o botão direito na pasta → <b>Compartilhar</b>. Dica: selecione várias pastas (⌘/Ctrl + clique) para compartilhar todas de uma vez.</span></li>
      <li data-key><span>Cole o e-mail, escolha <b className="drive-role">Leitor</b> e <b>desmarque “Notificar pessoas”</b>.</span><p className="drive-role-hint">{ROLE_HINT}</p></li>
      <li><span>Clique em <b>Enviar</b>. Se o Drive avisar que o endereço não é uma conta Google, confirme o envio. Repita para as outras pastas.</span></li>
    </ol>
    <div className="drive-feature"><ShieldCheck size={16} aria-hidden="true" /><span>Sem tela “Entrar com Google”: o ArquivIO só enxerga o que você compartilhar.</span></div>
    <section className="drive-found" aria-labelledby="drive-found-title" data-empty={folders.length === 0 || undefined}>
      <div className="drive-found-head"><b id="drive-found-title" className="drive-found-count" role="status" aria-live="polite" aria-atomic="true">{foundFoldersLabel(folders.length)}</b>{poll.phase === "polling" && <span className="drive-found-live"><Spinner size={12} />verificando a cada 5 s</span>}</div>
      {folders.length > 0 && <ul className="drive-found-list">{folders.map((f) => <li key={f.id}><FolderClosed size={16} aria-hidden="true" /><span className="min-w-0 flex-1"><b className="drive-folder-name">{f.name}</b></span>{f.shared_by_email && <span className="drive-folder-meta">{f.shared_by_email}</span>}</li>)}</ul>}
      {poll.phase === "paused" && <WaitingLine poll={poll} onResume={onResume} />}
    </section>
    {noneFound && folders.length === 0 && <div className="drive-alert" data-tone="warning" role="alert"><CircleAlert size={18} aria-hidden="true" /><div className="min-w-0"><p className="font-semibold">Ainda não encontramos nenhuma pasta compartilhada com <span className="drive-mono">{robot}</span>.</p>
      <ul className="drive-tips"><li>Confira se o e-mail foi digitado exatamente como acima e se escolheu <b>Leitor</b> (ou Editor).</li><li>O Google pode levar alguns segundos para liberar o acesso. Esperamos mais um pouco e verificamos sozinhos.</li><li>Compartilhe a <b>pasta</b>, não um arquivo, e não use “qualquer pessoa com o link”.</li><li>Se a sua empresa bloqueia compartilhamento externo, veja o aviso abaixo.</li></ul></div></div>}
    {(poll.emptyHint || noneFound) && folders.length === 0 && <WorkspaceHint robot={robot} organizationName={organizationName} onUseOAuth={onUseOAuth} />}
    <div className="drive-actions-end drive-actions-split">
      {hasExisting && <button type="button" className={btn("ghost")} onClick={onSkipToPick}>Já compartilhei antes — escolher agora</button>}
      <button type="button" className={btn("primary")} onClick={onContinue} disabled={checking} aria-busy={checking || undefined}>{checking ? "Verificando…" : "Já compartilhei todas as pastas"}</button>
    </div>
    <div className="drive-links drive-links-oauth"><span>Prefere entrar com a conta Google?</span><button type="button" className={btn("ghost", "sm")} onClick={onUseOAuth}>Entrar com a conta Google</button></div>
    <div className="drive-links"><span>Prefere colar o link?</span><button type="button" className={btn("ghost", "sm")} onClick={onPaste}><Link2 size={14} aria-hidden="true" />Colar o link da pasta</button></div>
    <div className="drive-links"><span>Sua empresa bloqueia compartilhamento externo?</span><details className="drive-details"><summary>Ver o que fazer</summary><div className="mt-2"><WorkspaceHint robot={robot} organizationName={organizationName} onUseOAuth={onUseOAuth} /></div></details></div>
  </div>;
}

function StepTwo({ robot, folders, all, choices, setChoices, picked, poll, onResume, paste, setPaste, pasteError, pasteChecking, onAddPasted, spaces, spaceIds, setSpaceIds, onConnect, onBack }: { spaces: LinkSpaceOption[] | null; spaceIds: string[]; setSpaceIds: (updater: (current: string[]) => string[]) => void; robot: string; folders: InboxFolder[]; all: InboxFolder[]; choices: SelectionChoices; setChoices: (updater: (c: SelectionChoices) => SelectionChoices) => void; picked: number; poll: ReturnType<typeof initialPollState>; onResume: () => void; paste: string; setPaste: (v: string) => void; pasteError: string | null; pasteChecking: boolean; onAddPasted: () => void; onConnect: () => void; onBack: () => void }) {
  // eslint-disable-next-line react-hooks/purity -- timestamp only labels relative "agora"; recomputed each render by design
  const now = Date.now();
  const allOn = folders.length > 0 && picked === folders.length;
  return <div className="drive-step">
    {folders.length > 0 ? <>
      <div className="drive-pick-head"><label className="drive-check drive-check-all"><input type="checkbox" checked={allOn} ref={(el) => { if (el) el.indeterminate = picked > 0 && !allOn; }} onChange={() => setChoices((c) => toggleAll(folders, c))} /><span>Selecionar todas</span></label><span className="drive-pick-count" role="status" aria-live="polite">{picked} de {folders.length} {folders.length === 1 ? "selecionada" : "selecionadas"}</span></div>
      <ul className="drive-pick-list" aria-label="Pastas compartilhadas com o ArquivIO">{folders.map((f) => {
        const checked = isSelected(f, all, choices); const parent = knownAncestors(f, all)[0]; const warn = nestedWarning(f, all, choices);
        const hintId = `drive-pick-${f.id}-hint`;
        return <li key={f.id} data-checked={checked || undefined} data-nested={parent ? "" : undefined}>
          <label className="drive-check drive-pick-row"><input type="checkbox" checked={checked} aria-describedby={parent ? hintId : undefined} onChange={() => setChoices((c) => ({ ...c, [f.id]: !checked }))} /><FolderClosed size={20} aria-hidden="true" /><span className="min-w-0 flex-1"><b className="drive-folder-name">{f.name}</b><span className="drive-folder-meta">{f.via === "link" ? "adicionada por link" : f.shared_by_email ? `compartilhada por ${f.shared_by_email}` : "compartilhada com o ArquivIO"}{f.shared_at ? ` · ${relativeSync(f.shared_at, now).replace("sync ", "")}` : ""}</span></span></label>
          {parent && <p id={hintId} className="drive-nested-hint" data-active={warn ? "" : undefined}><CircleAlert size={14} aria-hidden="true" />{nestedWarningText(parent.name)}{spaces && spaces.length > 1 ? ` ${nestedSeparationHint}` : ""}</p>}
        </li>; })}</ul>
      {poll.phase === "paused" ? <WaitingLine poll={poll} onResume={onResume} /> : <p className="drive-note drive-live-note"><Spinner size={12} />Novas pastas compartilhadas aparecem aqui sozinhas.</p>}
    </> : <><p className="drive-lead">Ainda não apareceu nenhuma pasta compartilhada com <span className="drive-mono">{robot}</span>.</p><WaitingLine poll={poll} onResume={onResume} /></>}
    {spaces && <fieldset className="drive-spaces" aria-describedby="drive-spaces-disclosure">
      <legend className="drive-lead">Quem poderá ver {picked === 1 ? "esta pasta" : "estas pastas"}?</legend>
      <ul className="drive-spaces-list">{spaces.map((space) => <li key={space.id}><label className="drive-check"><input type="checkbox" checked={spaceIds.includes(space.id)} onChange={() => setSpaceIds((current) => toggleSpace(current, space.id))} /><span>{space.name}{space.is_default ? " (padrão)" : ""}</span></label></li>)}</ul>
      <p id="drive-spaces-disclosure" className="drive-note">{DISCLOSURE_TEXT}</p>
      {!canLink({ spaceIds }) && <p className="drive-field-error" role="alert"><CircleAlert size={14} aria-hidden="true" />Escolha pelo menos um Espaço para conectar.</p>}
    </fieldset>}
    <form className="drive-paste" noValidate onSubmit={(e) => { e.preventDefault(); onAddPasted(); }}>
      <label htmlFor="drive-link" className="drive-lead">{folders.length > 0 ? "Não apareceu? Cole o link da pasta:" : "Ou cole o link da pasta:"}</label>
      <div className="drive-paste-row"><input id="drive-link" type="url" inputMode="url" autoComplete="off" spellCheck={false} placeholder={SAMPLE_FOLDER_LINK} value={paste} onChange={(e) => setPaste(e.target.value)} aria-invalid={Boolean(pasteError)} aria-describedby={pasteError ? "drive-link-error" : "drive-link-hint"} /><button type="submit" className={btn("secondary")} disabled={!paste.trim() || pasteChecking} aria-busy={pasteChecking || undefined}>{pasteChecking ? "Verificando…" : "Adicionar à lista"}</button></div>
      <p id="drive-link-hint" className="drive-note">Pode ser o link de uma subpasta de uma pasta já compartilhada. Links de “qualquer pessoa com o link” não são aceitos.</p>
      {pasteError && <p id="drive-link-error" className="drive-field-error" role="alert"><CircleAlert size={14} aria-hidden="true" />{pasteError} <span className="drive-mono">Exemplo: {SAMPLE_FOLDER_LINK}</span></p>}
    </form>
    <div className="drive-actions-end drive-actions-split"><button type="button" className={btn("ghost")} onClick={onBack}><ArrowLeft size={14} aria-hidden="true" />Voltar ao passo 1</button><button type="button" className={btn("primary")} onClick={onConnect} disabled={picked === 0 || !canLink({ spaceIds, spacesKnown: spaces !== null })}>{connectLabel(picked)}</button></div>
  </div>;
}

function StepThree({ robot, all, batch, syncNote, onRetryFailed, onRetryAll, onBack, onChooseScope, onOpenLibrary, onDone }: { robot: string; all: InboxFolder[]; batch: BatchState; syncNote: string; onRetryFailed: () => void; onRetryAll: () => void; onBack: () => void; onChooseScope: () => void; onOpenLibrary?: () => void; onDone: () => void }) {
  const running = batch.phase === "running";
  const summary = batchSummary(batch.rows);
  const byId = new Map(batch.rows.map((r) => [r.folder_id, r]));
  const name = (id: string) => byId.get(id)?.name ?? all.find((f) => f.id === id)?.name ?? "Pasta do Drive";
  const retryable = retryableIds(batch.rows).length;
  return <div className="drive-step">
    <ul className="drive-checklist drive-batch" aria-label="Pastas sendo conectadas" aria-busy={running || undefined}>
      {batch.ids.map((id, index) => {
        const row = byId.get(id); const view = row ? batchRowView(row, robot) : null;
        const state = !row ? "running" : view!.tone === "ok" ? "done" : view!.tone === "warn" ? "warn" : view!.tone === "info" ? "info" : "failed";
        return <li key={id} data-state={state} style={{ "--i": index } as CSSProperties}>
          {state === "running" ? <Spinner size={16} /> : state === "done" ? <Check size={16} aria-hidden="true" /> : state === "failed" ? <X size={16} aria-hidden="true" /> : <CircleAlert size={16} aria-hidden="true" />}
          <span className="min-w-0 flex-1"><b className="drive-folder-name">{name(id)}</b><span className="drive-folder-meta">{view ? view.label : "Verificando acesso, permissões e arquivos…"}</span>{view?.hint && view.tone !== "ok" && <span className="drive-folder-meta">{view.hint}</span>}</span>
          <span className="sr-only">{state === "done" ? " — conectada" : state === "warn" ? " — conectada com atenção" : state === "info" ? " — já incluída" : state === "failed" ? " — com problema" : " — verificando"}</span>
        </li>; })}
    </ul>
    {batch.failure && <div className="drive-alert" data-tone="error" role="alert"><CircleAlert size={18} aria-hidden="true" /><div><p>{batch.failure}</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" className={btn("secondary", "sm")} onClick={onRetryAll}><RefreshCw size={14} aria-hidden="true" />Tentar de novo</button><button type="button" className={btn("ghost", "sm")} onClick={onBack}>Voltar à lista</button></div></div></div>}
    {batch.phase === "done" && <div className="drive-success">
      <p className="drive-success-title" role="status" aria-live="polite"><ShieldCheck size={20} aria-hidden="true" />{summary.text}</p>
      <p className="drive-note">Seu e-mail do ArquivIO: <span className="drive-mono">{robot}</span>. Para incluir mais pastas, compartilhe com o mesmo e-mail.</p>
      {syncNote && <p className="drive-note" id="drive-eta">{syncNote}</p>}
      {retryable > 0 && <div className="drive-alert mt-3" data-tone="warning" role="note"><CircleAlert size={18} aria-hidden="true" /><div><p>{retryable === 1 ? "Uma pasta não pôde ser conectada." : `${retryable} pastas não puderam ser conectadas.`} Confira o compartilhamento no Drive e tente de novo.</p><div className="mt-3 flex flex-wrap gap-2"><CopyButton text={robot} label="Copiar e-mail" size="sm" /><button type="button" className={btn("primary", "sm")} onClick={onRetryFailed}><RefreshCw size={14} aria-hidden="true" />Tentar de novo as que falharam</button></div></div></div>}
      <div className="drive-actions-end"><button type="button" className={btn("ghost")} onClick={summary.connected > 0 ? onChooseScope : onBack}>{summary.connected > 0 ? "Escolher o que sincronizar em cada pasta" : "Voltar à lista"}</button>{onOpenLibrary && summary.connected > 0 && <button type="button" className={btn("secondary")} onClick={onOpenLibrary}>Ver na Biblioteca</button>}<button type="button" className={btn("primary")} onClick={onDone}>Concluir</button></div>
    </div>}
  </div>;
}

// ---- Tela 4: card único "Google Drive" (pasta compartilhada + conta Google) ----

export type GoogleDriveCardProps = {
  oauth: Source | null; share: Source | null; oauthFolders: Folder[]; workspaceFolders?: Folder[]; client?: DriveShareApi; syncBadge?: ReactNode; disconnectingId: string | null; initialState?: DriveShareState | null;
  onStart: () => void; onAddFolders: (source: Source | null) => void; onManage: (source: Source) => void; onDisconnect: (source: Source) => void; onReconnectOauth: (sourceId: string) => void; onChanged?: () => void;
};

export function GoogleDriveCard({ oauth, share, oauthFolders, workspaceFolders = [], client = driveShareApi, syncBadge, disconnectingId, initialState = null, onStart, onAddFolders, onManage, onDisconnect, onReconnectOauth, onChanged }: GoogleDriveCardProps) {
  const [state, setState] = useState<DriveShareState | null>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const sourceId = share?.id; const shareRaw = share?.status;
  useEffect(() => { if (!sourceId || initialState) return; let alive = true; client.state(sourceId, shareRaw).then((s) => alive && setState(s)).catch(() => undefined); return () => { alive = false; }; }, [client, sourceId, initialState, shareRaw]);
  const shareStatus = state?.status ?? share?.status;
  const liveShare = share ? { ...share, status: shareStatus ?? share.status } : null;
  const [now] = useState(() => Date.now());
  const rows = unifiedDriveFolders({ shareFolders: state?.folders ?? [], oauthFolders, workspaceFolders, oauthSourceId: oauth?.id ?? null, now });
  const status = driveCardStatus({ oauth, share: liveShare, healthyShareFolders: rows.filter((r) => r.method === "share" && !r.lost).length });
  const actions = driveCardActions({ oauth, share: liveShare });
  const summary = summarizeDriveFolders(rows);
  const [managing, setManaging] = useState(false);
  const shareIssue = driveConnectionIssue("share", liveShare); const oauthIssue = driveConnectionIssue("oauth", oauth);
  const issueCount = [shareIssue, oauthIssue].filter(Boolean).length;
  const robot = state?.robot_email ?? null;
  const lost = shareStatus === "access_lost";
  const both = Boolean(oauth && share);
  const fresh = useCallback(async (fn: () => Promise<unknown>, key: string, done: string) => { setBusy(key); setError(null); try { await fn(); if (sourceId) setState(await client.state(sourceId, shareRaw)); setAnnounce(done); onChanged?.(); } catch (e) { setError(messageFor(e)); } finally { setBusy(null); } }, [client, sourceId, shareRaw, onChanged]);
  const [unlinking, setUnlinking] = useState<FolderLink | null>(null);
  const unlink = (link: FolderLink, purge: boolean) => { setUnlinking(null); if (sourceId) void fresh(() => client.unlink(sourceId, link.link_id ?? link.id, purge), `unlink-${link.id}`, purge ? "Conteúdo apagado." : `Pasta “${link.name}” desvinculada.`); };
  const primary = () => { if (actions.primary.kind === "start-share") onStart(); else onAddFolders(share); };
  const disconnectButton = (method: DriveMethodKey, source: Source, compact = false) => <button key={`disc-${method}`} type="button" onClick={() => onDisconnect(source)} disabled={disconnectingId !== null} className={btn("danger-ghost", "sm")}><Unplug size={14} aria-hidden="true" />{disconnectingId === source.id ? "Desconectando…" : compact ? "Desconectar" : method === "share" ? "Desconectar pastas compartilhadas" : "Desconectar conta Google"}</button>;
  const folderRow = (f: UnifiedFolder, manager = false) => {
    const link = f.method === "share" ? (state?.folders ?? []).find((x) => `share:${x.id}` === f.key) : undefined;
    return <li key={f.key} data-lost={f.lost || undefined}><FolderOpen size={16} aria-hidden="true" /><div className="min-w-0 flex-1"><b className="drive-folder-name">{f.name}</b><span className="drive-folder-meta">{f.lost ? f.meta : `${f.fileCount != null ? `${formatCount(f.fileCount, "arquivo", "arquivos")} · ` : ""}${relativeSync(f.lastSyncedAt, now)}`}</span></div>
      {manager && <span className="drive-folder-badge" data-tone={f.badge.tone}>{f.badge.label}</span>}
      {link && f.canUnlink && <button type="button" className={btn("danger-ghost", "sm")} disabled={busy !== null} onClick={() => setUnlinking(link)}>{f.lost ? <Trash2 size={14} aria-hidden="true" /> : <Unplug size={14} aria-hidden="true" />}{f.lost ? "Apagar agora" : "Desvincular"}</button>}</li>;
  };
  return <section className="integration-tool-card drive-card h-full rounded-lg border border-card-edge bg-raised p-4 shadow-sm" data-status={status.tone}>
    <button type="button" onClick={primary} className="integration-tool-header mo-interactive flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-sage"><ProviderLogo provider="google" size={26} /></span><b className="integration-tool-title min-w-0 flex-1">Google Drive</b><ChevronRight className="mo-arrow shrink-0 text-muted-foreground" size={18} aria-hidden="true" /></button>
    {actions.primary.kind === "start-share" ? <>
      <p className="integration-tool-description">Compartilhe pastas do seu Google Drive com o e-mail exclusivo do ArquivIO. Ele só enxerga o que você compartilhar.</p>
      <div className="integration-tool-footer border-t border-line-soft text-xs"><div className="integration-tool-state"><span className="drive-dot-status" data-tone="neutral" /><span className="font-medium text-muted-foreground">Disponível</span></div><span className="integration-tool-actions flex items-center gap-2"><button type="button" onClick={onStart} className="mo-interactive rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground">Conectar</button></span></div>
    </> : <>
      <div className="drive-card-status"><span className="drive-dot-status" data-tone={status.tone} /><b>{status.label}</b>{syncBadge}{oauth?.account_email && !share && <span className="truncate text-muted-foreground" title={oauth.account_email}>· {oauth.account_email}</span>}</div>
      <p className="integration-tool-description">{status.description}</p>
      {robot && <div className="drive-card-robot"><span className="drive-mono" title={robot}>Compartilhe com: {robot}</span><CopyButton text={robot} label="Copiar" variant="ghost" size="sm" /></div>}
      {summary.total > 0 && <div className="drive-card-summary"><p className="drive-card-summary-text" data-warn={summary.lostCount > 0 || undefined}>{summary.lostCount > 0 && <CircleAlert size={14} aria-hidden="true" />}{summary.text}</p>
        <button type="button" className={btn("secondary", "sm", "drive-card-viewall")} onClick={() => setManaging(true)} aria-haspopup="dialog">Ver pastas ({summary.total})</button></div>}
      {error && <p className="drive-field-error" role="alert"><CircleAlert size={14} aria-hidden="true" />{error}</p>}
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>
      <div className="integration-tool-footer border-t border-line-soft text-xs"><span className="integration-tool-actions flex flex-wrap items-center gap-2">
        {!both && actions.disconnect.map((item) => disconnectButton(item.method, item.source, true))}
        {lost && sourceId && <button type="button" onClick={() => void fresh(() => client.recheck(sourceId), "recheck", "Acesso verificado novamente.")} disabled={busy !== null} aria-busy={busy === "recheck" || undefined} className={btn("secondary", "sm")}><RefreshCw size={14} aria-hidden="true" />Verificar agora</button>}
        {actions.reconnectOauth && oauth && <button type="button" onClick={() => onReconnectOauth(oauth.id)} className={btn("secondary", "sm")}>Reconectar conta Google</button>}
        {actions.manage && <button type="button" onClick={() => onManage(actions.manage!)} className={btn("secondary", "sm")}>Gerenciar</button>}
        <button type="button" onClick={primary} className="mo-interactive rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground">{actions.primary.label}</button>
      </span></div>
      {both && <details className="drive-details drive-card-methods"><summary>Detalhes das conexões{issueCount > 0 && <span className="drive-folder-badge" data-tone={shareIssue?.tone === "error" ? "error" : "warning"}>{issueCount} com problema</span>}</summary>
        <ul>{share && <li><span className="min-w-0 flex-1"><b>Pastas compartilhadas</b>{shareIssue && <span className="drive-folder-badge" data-tone={shareIssue.tone}>{shareIssue.label}</span>}{robot && <span className="drive-folder-meta drive-mono">{robot}</span>}</span>{disconnectButton("share", share)}</li>}
          {oauth && <li><span className="min-w-0 flex-1"><b>Conta Google</b>{oauthIssue && <span className="drive-folder-badge" data-tone={oauthIssue.tone}>{oauthIssue.label}</span>}{oauth.account_email && <span className="drive-folder-meta">{oauth.account_email}</span>}</span>{disconnectButton("oauth", oauth)}</li>}</ul>
      </details>}
      {actions.primary.kind === "add-folders" && !oauth && <p className="integration-tool-note drive-add-note"><UserRound size={12} aria-hidden="true" /> Use o mesmo e-mail para todas as pastas: compartilhe cada nova pasta com ele e clique em “{actions.primary.label}”.</p>}
    </>}
    {managing && <DriveFoldersPanel covered={unlinking !== null} rows={rows} renderRow={(f) => folderRow(f, true)} onClose={() => setManaging(false)} />}
    {unlinking && <UnlinkConfirm link={unlinking} lost={unlinking.status !== "verified"} onCancel={() => setUnlinking(null)} onUnlink={(purge) => unlink(unlinking, purge)} />}
  </section>;
}


/** Painel com a lista completa: busca, rolagem interna, status por pasta e ações (a confirmação de desvincular abre por cima). */
function DriveFoldersPanel({ covered, rows, renderRow, onClose }: { covered: boolean; rows: UnifiedFolder[]; renderRow: (f: UnifiedFolder) => ReactNode; onClose: () => void }) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const search = useRef<HTMLInputElement>(null);
  // A confirmação de desvincular fica por cima: ao fechá-la, o foco volta ao painel (senão Esc/Tab deixam de chegar nele).
  const wasCovered = useRef(false);
  useEffect(() => { if (wasCovered.current && !covered) search.current?.focus({ preventScroll: true }); wasCovered.current = covered; }, [covered]);
  const shown = filterDriveFolders(rows, query);
  const summary = summarizeDriveFolders(rows, 0);
  return createPortal(<ModalOverlay onClose={onClose} labelledBy="drive-folders-title" className="integration-modal drive-share-modal aq-motion-overlay fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4">
    <section className="drive-share-panel drive-folders-panel max-w-2xl" data-arquivio-motion="panel-scale">
      <header className="drive-share-head"><span className="drive-share-logo"><ProviderLogo provider="google" size={24} /></span><div className="min-w-0 flex-1"><h2 id="drive-folders-title" className="text-xl font-semibold text-ink">Pastas do Google Drive</h2><p className="mt-1 text-sm text-muted-foreground">{summary.text}</p></div><button type="button" onClick={onClose} aria-label="Fechar" className={btn("ghost", "icon")}><X size={18} /></button></header>
      <div className="drive-folders-search"><label htmlFor={searchId} className="sr-only">Buscar pasta por nome</label><input id={searchId} ref={search} type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Buscar pasta por nome" autoComplete="off" spellCheck={false} /></div>
      <p className="sr-only" role="status" aria-live="polite">{shown.length === 1 ? "1 pasta encontrada." : `${shown.length} pastas encontradas.`}</p>
      {shown.length > 0 ? <ul className="drive-card-folders drive-folders-list" aria-label="Todas as pastas">{shown.map((f) => renderRow(f))}</ul> : <p className="drive-note drive-folders-empty">Nenhuma pasta com “{query.trim()}”.</p>}
      <footer className="drive-share-actions"><button type="button" className={btn("primary")} onClick={onClose}>Fechar</button></footer>
    </section>
  </ModalOverlay>, document.body);
}

function UnlinkConfirm({ link, lost, onCancel, onUnlink }: { link: FolderLink; lost: boolean; onCancel: () => void; onUnlink: (purge: boolean) => void }) {
  const copy = unlinkConfirmCopy(link.name);
  // Portal: o card tem transform/motion, então um `fixed` interno ficaria preso ao card.
  return createPortal(<ModalOverlay onClose={onCancel} labelledBy="drive-unlink-title" className="integration-modal drive-share-modal aq-motion-overlay fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4">
    <section className="drive-share-panel max-w-lg" data-arquivio-motion="panel-scale" role="alertdialog" aria-describedby="drive-unlink-body">
      <header className="drive-share-head"><span className="drive-share-logo"><Unplug size={20} aria-hidden="true" /></span><div className="min-w-0 flex-1"><h2 id="drive-unlink-title" className="text-xl font-semibold text-ink">{lost ? `Apagar “${link.name}” agora?` : copy.title}</h2></div><button type="button" onClick={onCancel} aria-label="Fechar" className={btn("ghost", "icon")}><X size={18} /></button></header>
      <p id="drive-unlink-body" className="drive-note">{lost ? "O acesso a esta pasta já foi removido. Você pode esperar o prazo de 14 dias ou apagar os documentos indexados agora, sem volta." : copy.body}</p>
      {!lost && <p className="drive-note mt-2">{copy.purgeHint}</p>}
      <footer className="drive-share-actions"><button type="button" className={btn("ghost")} onClick={onCancel} autoFocus>Cancelar</button>{!lost && <button type="button" className={btn("secondary")} onClick={() => onUnlink(false)}>{copy.keep}</button>}<button type="button" className={btn("destructive")} onClick={() => onUnlink(true)}><Trash2 size={14} aria-hidden="true" />{copy.purge}</button></footer>
    </section>
  </ModalOverlay>, document.body);
}
