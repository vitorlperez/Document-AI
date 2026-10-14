"use client";

import { ArrowLeft, Check, CircleAlert, Clock3, Copy, ExternalLink, FolderClosed, FolderOpen, Link2, RefreshCw, ShieldCheck, Trash2, Unplug, UserRound, X } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { ModalOverlay } from "../modal-dismiss";
import { ProviderLogo } from "../provider-logo";
import { Spinner, btn } from "../ui";
import { driveShareApi, type DriveShareApi, type InboxFolder, type DriveShareState } from "./drive-share-api";
import {
  ROLE_HINT, SAMPLE_FOLDER_LINK, WORKSPACE_BLOCK_MESSAGE, POLL_INTERVAL_MS, checklistReach, driveFolderUrl, driveShareStatus, firstSyncEstimate, formatCount, initialPollState, itRequestText,
  parseDriveFolderLink, pollTick, relativeSync, resumePoll, verifyChecklist, verifyErrorMessage, daysUntil, type FolderLink, type VerifyResult,
} from "./drive-share-logic";
import { ApiError, messageFor, type Source } from "./types-and-api";
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

// ---- Tela 0: modal de método ----

export type DriveMethod = "share" | "oauth";

export function DriveMethodModal({ onCancel, onContinue }: { onCancel: () => void; onContinue: (method: DriveMethod) => void }) {
  const [method, setMethod] = useState<DriveMethod>("share");
  return <ModalOverlay onClose={onCancel} labelledBy="drive-method-title" className="integration-modal drive-share-modal aq-motion-overlay fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4">
    <section className="drive-share-panel max-w-xl" data-arquivio-motion="panel-scale">
      <header className="drive-share-head"><span className="drive-share-logo"><ProviderLogo provider="google" size={24} /></span><div className="min-w-0 flex-1"><h2 id="drive-method-title" className="text-xl font-semibold text-ink">Conectar Google Drive</h2><p className="mt-1 text-sm text-muted-foreground">Como você prefere dar acesso?</p></div><button type="button" onClick={onCancel} aria-label="Fechar" className={btn("ghost", "icon")}><X size={18} /></button></header>
      <div role="radiogroup" aria-label="Como dar acesso ao Google Drive" className="drive-method-list">
        <label className="drive-method" data-selected={method === "share" || undefined}>
          <input type="radio" name="drive-method" value="share" checked={method === "share"} onChange={() => setMethod("share")} />
          <span className="drive-method-body"><span className="drive-method-title">Compartilhar pastas com o ArquivIO<span className="drive-chip" data-tone="ok">Recomendado</span></span>
            <span className="drive-method-text">Você escolhe as pastas e as compartilha como “Leitor”. O ArquivIO não vê mais nada do seu Drive. Funciona com Gmail e com Google Workspace.</span></span>
        </label>
        <label className="drive-method" data-selected={method === "oauth" || undefined}>
          <input type="radio" name="drive-method" value="oauth" checked={method === "oauth"} onChange={() => setMethod("oauth")} />
          <span className="drive-method-body"><span className="drive-method-title">Entrar com a conta Google<span className="drive-chip">Modo atual</span></span>
            <span className="drive-method-text">Você autoriza a leitura do Drive e escolhe as pastas depois.</span></span>
        </label>
      </div>
      <footer className="drive-share-actions"><button type="button" className={btn("ghost")} onClick={onCancel}>Cancelar</button><button type="button" className={btn("primary")} onClick={() => onContinue(method)}>Continuar</button></footer>
    </section>
  </ModalOverlay>;
}

// ---- fluxo em 3 passos ----

type Step = 1 | 2 | 3;
type Robot = { sourceId: string; email: string };
export type DriveShareFlowProps = {
  organizationId: string; organizationName?: string; existingSource?: Pick<Source, "id"> | null;
  client?: DriveShareApi; onClose: () => void; onUseOAuth: () => void;
  /** Depois do vínculo: abre o seletor de escopo atual (loadCatalog). */
  onChooseScope: (sourceId: string) => void; onLinked?: () => void;
  /** Só para testes/preview: força o passo inicial e a fonte. */
  preview?: { step: Step; robot: Robot };
};

function Stepper({ step }: { step: Step }) {
  return <ol className="drive-stepper" aria-label={`Passo ${step} de 3`}>{[1, 2, 3].map((n) => <li key={n} data-state={n < step ? "done" : n === step ? "current" : "todo"} aria-current={n === step ? "step" : undefined}><span>{n < step ? <Check size={12} aria-hidden="true" /> : n}</span></li>)}</ol>;
}

export function DriveShareFlow({ organizationId, organizationName, existingSource, client = driveShareApi, onClose, onUseOAuth, onChooseScope, onLinked, preview }: DriveShareFlowProps) {
  const [step, setStep] = useState<Step>(preview?.step ?? 1);
  const [robot, setRobot] = useState<Robot | null>(preview?.robot ?? null);
  const [enableError, setEnableError] = useState<string | null>(null);
  const [inbox, setInbox] = useState<InboxFolder[]>([]);
  const [poll, setPoll] = useState(initialPollState);
  const [paste, setPaste] = useState(""); const [pasteError, setPasteError] = useState<string | null>(null);
  const [verifying, setVerifying] = useState(false); const [target, setTarget] = useState<string | null>(null);
  const [result, setResult] = useState<VerifyResult | null>(null); const [verifyFailure, setVerifyFailure] = useState<string | null>(null);
  const [linking, setLinking] = useState(false); const [linkError, setLinkError] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const autoAdvanced = useRef(false);

  const enable = useCallback(() => {
    setEnableError(null);
    if (existingSource) { client.state(existingSource.id).then((s) => setRobot({ sourceId: s.source_id ?? existingSource.id, email: s.robot_email })).catch((e) => setEnableError(messageFor(e))); return; }
    client.enable(organizationId).then((r) => setRobot({ sourceId: r.source_id, email: r.robot_email })).catch((e) => setEnableError(e instanceof ApiError && e.status === 403 ? "Só responsáveis e administradores configuram o acesso ao Google Drive." : messageFor(e)));
  }, [client, existingSource, organizationId]);
  useEffect(() => { if (!preview) enable(); }, [enable, preview]);

  // Polling do inbox: 5 s, até 5 min, depois pausa (botão "Retomar"). Só nos passos 1 e 2.
  const pollActive = robot !== null && step < 3 && poll.phase === "polling" && !preview;
  useEffect(() => {
    if (!pollActive || !robot) return;
    let cancelled = false;
    const tick = async () => {
      let folders: InboxFolder[] = [];
      try { folders = await client.inbox(robot.sourceId); } catch { /* falha de rede: tenta no próximo tick */ }
      if (cancelled) return;
      setInbox(folders);
      const fresh = folders.some((f) => !f.linked);
      setPoll((state) => pollTick(state, fresh));
    };
    void tick();
    const timer = window.setInterval(() => void tick(), POLL_INTERVAL_MS);
    return () => { cancelled = true; window.clearInterval(timer); };
  }, [pollActive, robot, client]);
  const unlinked = useMemo(() => inbox.filter((f) => !f.linked), [inbox]);
  useEffect(() => {
    if (step === 1 && unlinked.length > 0 && !autoAdvanced.current) { autoAdvanced.current = true; setStep(2); setAnnounce(`${unlinked.length === 1 ? "Encontramos uma pasta compartilhada" : `Encontramos ${unlinked.length} pastas compartilhadas`} com o ArquivIO.`); }
  }, [step, unlinked.length]);

  async function runVerify(urlOrId: string, folderName?: string) {
    if (!robot) return;
    setStep(3); setVerifying(true); setResult(null); setVerifyFailure(null); setLinkError(null); setTarget(urlOrId);
    try {
      const res = await client.verify(robot.sourceId, urlOrId);
      setResult({ ...res, folder_name: res.folder_name ?? folderName });
      if (res.code === "ok" || res.code === "download_blocked_partial") setAnnounce("Acesso confirmado."); // erros já usam role="alert"
    } catch (error) {
      // O backend devolve o mesmo corpo para "não existe" e "sem acesso" (not_shared); 404/422 sem corpo estruturado = idem.
      if (error instanceof ApiError && (error.status === 404 || error.status === 422)) setResult({ code: error.status === 422 ? "invalid_link" : "not_shared" });
      else if (error instanceof ApiError && error.status === 429) setResult({ code: "rate_limited" });
      else if (error instanceof ApiError && error.status >= 500) setResult({ code: "provider_error" });
      else setVerifyFailure(messageFor(error));
    } finally { setVerifying(false); }
  }

  function submitPaste() {
    const parsed = parseDriveFolderLink(paste);
    if (parsed.kind === "invalid") { setPasteError(verifyErrorMessage(parsed.code, robot?.email ?? null).title); return; }
    setPasteError(null); void runVerify(paste.trim());
  }

  async function connectFolder() {
    if (!robot || !result?.folder_id) return;
    setLinking(true); setLinkError(null);
    try { await client.link(robot.sourceId, result.folder_id); onLinked?.(); onChooseScope(robot.sourceId); }
    catch (error) { setLinkError(messageFor(error)); } finally { setLinking(false); }
  }

  const busy = verifying || linking;
  const titleId = "drive-share-title";
  return <ModalOverlay onClose={onClose} busy={busy} labelledBy={titleId} className="integration-modal drive-share-modal aq-motion-overlay fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4">
    <section className="drive-share-panel max-w-2xl" data-arquivio-motion="panel-scale" data-step={step}>
      <header className="drive-share-head"><span className="drive-share-logo"><ProviderLogo provider="google" size={24} /></span><div className="min-w-0 flex-1"><h2 id={titleId} className="text-xl font-semibold text-ink">Compartilhar pastas com o ArquivIO</h2><p className="mt-1 text-sm text-muted-foreground">Passo {step} de 3 · {step === 1 ? "Compartilhe a pasta com este e-mail" : step === 2 ? "Confirmar pasta" : "Verificando acesso"}</p></div><Stepper step={step} /><button type="button" onClick={onClose} disabled={busy} aria-label="Fechar" className={btn("ghost", "icon")}><X size={18} /></button></header>
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>

      {!robot && !enableError && <div className="drive-loading" role="status"><Spinner size={18} /><span>Preparando o e-mail exclusivo da sua empresa…</span></div>}
      {enableError && <div className="drive-alert" data-tone="error" role="alert"><CircleAlert size={18} aria-hidden="true" /><div><p className="font-semibold">Não foi possível preparar o acesso.</p><p>{enableError}</p><div className="mt-3 flex flex-wrap gap-2"><button type="button" className={btn("secondary", "sm")} onClick={enable}><RefreshCw size={14} aria-hidden="true" />Tentar de novo</button><button type="button" className={btn("ghost", "sm")} onClick={onUseOAuth}>Usar “Entrar com a conta Google”</button></div></div></div>}

      {robot && step === 1 && <StepOne robot={robot.email} poll={poll} onResume={() => setPoll(resumePoll)} onPaste={() => setStep(2)} onUseOAuth={onUseOAuth} organizationName={organizationName} />}
      {robot && step === 2 && <StepTwo robot={robot.email} folders={unlinked} poll={poll} onResume={() => setPoll(resumePoll)} paste={paste} setPaste={(v) => { setPaste(v); setPasteError(null); }} pasteError={pasteError} onVerifyPaste={submitPaste} onConnect={(f) => void runVerify(f.id, f.name)} onBack={() => setStep(1)} />}
      {robot && step === 3 && <StepThree robot={robot.email} verifying={verifying} result={result} failure={verifyFailure} linking={linking} linkError={linkError}
        onRetry={() => target && void runVerify(target, result?.folder_name ?? undefined)} onBack={() => { setStep(2); setResult(null); setVerifyFailure(null); }} onConnect={() => void connectFolder()} onUseOAuth={onUseOAuth} organizationName={organizationName} />}
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

function StepOne({ robot, poll, onResume, onPaste, onUseOAuth, organizationName }: { robot: string; poll: ReturnType<typeof initialPollState>; onResume: () => void; onPaste: () => void; onUseOAuth: () => void; organizationName?: string }) {
  return <div className="drive-step">
    <RobotEmail email={robot} />
    <p className="drive-note">Este e-mail é exclusivo da sua empresa. Ninguém mais o usa.</p>
    <ol className="drive-instructions">
      <li><span>Abra o Google Drive em outra aba.</span><a className={btn("secondary", "sm")} href={DRIVE_HOME} target="_blank" rel="noopener noreferrer">Abrir o Google Drive<ExternalLink size={14} aria-hidden="true" /></a></li>
      <li><span>Clique com o botão direito na pasta → <b>Compartilhar</b>.</span></li>
      <li data-key><span>Cole o e-mail, escolha <b className="drive-role">Leitor</b> e <b>desmarque “Notificar pessoas”</b>.</span><p className="drive-role-hint">{ROLE_HINT}</p></li>
      <li><span>Clique em <b>Enviar</b>. Se o Drive avisar que o endereço não é uma conta Google, confirme o envio.</span></li>
    </ol>
    <div className="drive-feature"><ShieldCheck size={16} aria-hidden="true" /><span>Sem tela “Entrar com Google”: o ArquivIO só enxerga o que você compartilhar.</span></div>
    <WaitingLine poll={poll} onResume={onResume} />
    {poll.emptyHint && <WorkspaceHint robot={robot} organizationName={organizationName} onUseOAuth={onUseOAuth} />}
    <div className="drive-links"><span>Já compartilhou?</span><button type="button" className={btn("ghost", "sm")} onClick={onPaste}><Link2 size={14} aria-hidden="true" />Colar o link da pasta</button></div>
    <div className="drive-links"><span>Sua empresa bloqueia compartilhamento externo?</span><details className="drive-details"><summary>Ver o que fazer</summary><div className="mt-2"><WorkspaceHint robot={robot} organizationName={organizationName} onUseOAuth={onUseOAuth} /></div></details></div>
  </div>;
}

function StepTwo({ robot, folders, poll, onResume, paste, setPaste, pasteError, onVerifyPaste, onConnect, onBack }: { robot: string; folders: InboxFolder[]; poll: ReturnType<typeof initialPollState>; onResume: () => void; paste: string; setPaste: (v: string) => void; pasteError: string | null; onVerifyPaste: () => void; onConnect: (f: InboxFolder) => void; onBack: () => void }) {
  const now = Date.now();
  return <div className="drive-step">
    {folders.length > 0 ? <>
      <p className="drive-lead">Encontramos {folders.length === 1 ? "uma pasta compartilhada" : "pastas compartilhadas"} com o ArquivIO:</p>
      <ul className="drive-folder-list">{folders.map((f) => <li key={f.id}><FolderClosed size={20} aria-hidden="true" /><div className="min-w-0 flex-1"><b className="drive-folder-name">{f.name}</b><span className="drive-folder-meta">{f.shared_by_email ? `compartilhada por ${f.shared_by_email}` : "compartilhada com o ArquivIO"}{f.shared_at ? ` · ${relativeSync(f.shared_at, now).replace("sync ", "")}` : ""}</span></div><button type="button" className={btn("primary", "sm")} onClick={() => onConnect(f)}>Conectar esta pasta</button></li>)}</ul>
    </> : <><p className="drive-lead">Ainda não apareceu nenhuma pasta compartilhada com <span className="drive-mono">{robot}</span>.</p><WaitingLine poll={poll} onResume={onResume} /></>}
    <form className="drive-paste" onSubmit={(e) => { e.preventDefault(); onVerifyPaste(); }}>
      <label htmlFor="drive-link" className="drive-lead">{folders.length > 0 ? "Não apareceu? Cole o link da pasta:" : "Ou cole o link da pasta:"}</label>
      <div className="drive-paste-row"><input id="drive-link" type="url" inputMode="url" autoComplete="off" spellCheck={false} placeholder={SAMPLE_FOLDER_LINK} value={paste} onChange={(e) => setPaste(e.target.value)} aria-invalid={Boolean(pasteError)} aria-describedby={pasteError ? "drive-link-error" : "drive-link-hint"} /><button type="submit" className={btn("primary")} disabled={!paste.trim()}>Verificar</button></div>
      <p id="drive-link-hint" className="drive-note">Pode ser o link de uma subpasta de uma pasta já compartilhada. Links de “qualquer pessoa com o link” não são aceitos.</p>
      {pasteError && <p id="drive-link-error" className="drive-field-error" role="alert"><CircleAlert size={14} aria-hidden="true" />{pasteError} <span className="drive-mono">Exemplo: {SAMPLE_FOLDER_LINK}</span></p>}
    </form>
    <div className="drive-actions-start"><button type="button" className={btn("ghost", "sm")} onClick={onBack}><ArrowLeft size={14} aria-hidden="true" />Voltar ao passo 1</button></div>
  </div>;
}

function StepThree({ robot, verifying, result, failure, linking, linkError, onRetry, onBack, onConnect, onUseOAuth, organizationName }: { robot: string; verifying: boolean; result: VerifyResult | null; failure: string | null; linking: boolean; linkError: string | null; onRetry: () => void; onBack: () => void; onConnect: () => void; onUseOAuth: () => void; organizationName?: string }) {
  const ok = result?.code === "ok" || result?.code === "download_blocked_partial";
  const items = result ? verifyChecklist(result) : [];
  const reach = result ? checklistReach(result.code) : 0;
  const message = result && !ok ? verifyErrorMessage(result.code, robot, result.blocked_download_count) : null;
  return <div className="drive-step">
    <ul className="drive-checklist" aria-label="Verificação de acesso">
      {verifying && <li data-state="running"><Spinner size={16} /><span>Verificando o acesso à pasta…</span></li>}
      {!verifying && result && items.map((item, index) => {
        const state = index < reach ? "done" : index === reach && !ok ? "failed" : "todo";
        const warn = item.key === "download" && result.code === "download_blocked_partial";
        return <li key={item.key} data-state={warn ? "warn" : state} style={{ "--i": index } as CSSProperties}>{state === "done" ? (warn ? <CircleAlert size={16} aria-hidden="true" /> : <Check size={16} aria-hidden="true" />) : state === "failed" ? <X size={16} aria-hidden="true" /> : <span className="drive-dot" aria-hidden="true" />}<span>{item.label}</span><span className="sr-only">{state === "done" ? (warn ? " — atenção" : " — ok") : state === "failed" ? " — falhou" : " — não verificado"}</span></li>;
      })}
    </ul>
    {failure && <div className="drive-alert" data-tone="error" role="alert"><CircleAlert size={18} aria-hidden="true" /><div><p>{failure}</p><div className="mt-3"><button type="button" className={btn("secondary", "sm")} onClick={onRetry}>Tentar de novo</button></div></div></div>}
    {message && <div className="drive-alert" data-tone={message.retryLater ? "warning" : "error"} role="alert"><CircleAlert size={18} aria-hidden="true" /><div className="min-w-0"><p className="font-semibold">{message.title}</p>{message.hint && <p className="mt-1">{message.hint}</p>}
      {message.example && <p className="drive-mono mt-2">Exemplo: {SAMPLE_FOLDER_LINK}</p>}
      <div className="mt-3 flex flex-wrap gap-2">{message.share && <><CopyButton text={robot} label="Copiar e-mail" size="sm" /><button type="button" className={btn("primary", "sm")} onClick={onRetry}><RefreshCw size={14} aria-hidden="true" />Já compartilhei, verificar de novo</button></>}
        {!message.share && <button type="button" className={btn("secondary", "sm")} onClick={message.retryLater ? onRetry : onBack}>{message.retryLater ? "Tentar de novo" : "Colar outro link"}</button>}
        {message.share && result?.folder_id && <a className={btn("ghost", "sm")} href={driveFolderUrl(result.folder_id)} target="_blank" rel="noopener noreferrer">Abrir esta pasta no Drive<ExternalLink size={14} aria-hidden="true" /></a>}
        {message.share && <button type="button" className={btn("ghost", "sm")} onClick={onBack}>Colar outro link</button>}</div>
      {message.share && <details className="drive-details mt-3"><summary>Sua empresa bloqueia compartilhamento externo?</summary><div className="mt-2"><WorkspaceHint robot={robot} organizationName={organizationName} onUseOAuth={onUseOAuth} /></div></details>}
    </div></div>}
    {ok && result && <div className="drive-success">
      <p className="drive-success-title"><ShieldCheck size={20} aria-hidden="true" />Acesso confirmado</p>
      <p className="drive-note">{result.shared_by_email ? `Compartilhada por ${result.shared_by_email} · ` : ""}Seu e-mail do ArquivIO: <span className="drive-mono">{robot}</span></p>
      <p className="drive-note" id="drive-eta">{firstSyncEstimate(result.file_count ?? 0)}</p>
      {result.code === "download_blocked_partial" && <div className="drive-alert mt-3" data-tone="warning" role="note"><CircleAlert size={18} aria-hidden="true" /><div><p className="font-semibold">{verifyErrorMessage("download_blocked_partial", robot, result.blocked_download_count).title}</p><p className="mt-1">{verifyErrorMessage("download_blocked_partial", robot, result.blocked_download_count).hint}</p></div></div>}
      {linkError && <p className="drive-field-error mt-3" role="alert"><CircleAlert size={14} aria-hidden="true" />{linkError}</p>}
      <div className="drive-actions-end"><button type="button" className={btn("ghost")} onClick={onBack} disabled={linking}>Escolher outra pasta</button><button type="button" className={btn("primary")} onClick={onConnect} disabled={linking} aria-busy={linking || undefined} aria-describedby="drive-eta">{linking ? "Conectando…" : "Escolher o que sincronizar"}</button></div>
    </div>}
  </div>;
}

// ---- Tela 4: card conectado ----

export type DriveShareCardProps = {
  source: Source | null; client?: DriveShareApi; syncBadge?: ReactNode; disconnecting: boolean; initialState?: DriveShareState | null;
  onStart: () => void; onAddFolder: (source: Source) => void; onManage: (source: Source) => void; onDisconnect: (source: Source) => void; onChanged?: () => void;
};

export function DriveShareCard({ source, client = driveShareApi, syncBadge, disconnecting, initialState = null, onStart, onAddFolder, onManage, onDisconnect, onChanged }: DriveShareCardProps) {
  const [state, setState] = useState<DriveShareState | null>(initialState);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const sourceId = source?.id;
  useEffect(() => { if (!sourceId || initialState) return; let alive = true; client.state(sourceId).then((s) => alive && setState(s)).catch(() => undefined); return () => { alive = false; }; }, [client, sourceId, initialState]);
  const status = driveShareStatus(state?.status ?? source?.status ?? "awaiting_share");
  const folders = state?.folders ?? [];
  const robot = state?.robot_email ?? null;
  const connected = (state?.status ?? source?.status) === "connected";
  const lost = (state?.status ?? source?.status) === "access_lost";
  const fresh = useCallback(async (fn: () => Promise<unknown>, key: string, done: string) => { setBusy(key); setError(null); try { await fn(); if (sourceId) setState(await client.state(sourceId)); setAnnounce(done); onChanged?.(); } catch (e) { setError(messageFor(e)); } finally { setBusy(null); } }, [client, sourceId, onChanged]);
  const purgeNow = (link: FolderLink) => { if (!window.confirm(`Apagar agora o conteúdo de “${link.name}”? Isso remove os documentos indexados desta pasta e não pode ser desfeito.`)) return; if (sourceId) void fresh(() => client.unlink(sourceId, link.id, true), `purge-${link.id}`, "Conteúdo apagado."); };
  const now = Date.now();
  return <section className="integration-tool-card drive-card h-full rounded-lg border border-card-edge bg-raised p-4 shadow-sm" data-status={state?.status ?? source?.status ?? "available"}>
    <button type="button" onClick={() => { if (source && connected) onManage(source); else if (source) onAddFolder(source); else onStart(); }} className="integration-tool-header mo-interactive flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-sage"><ProviderLogo provider="google" size={26} /></span><b className="integration-tool-title min-w-0 flex-1">Google Drive · Pasta compartilhada</b></button>
    {!source ? <>
      <p className="integration-tool-description">Compartilhe pastas com o e-mail exclusivo do ArquivIO. Ele só enxerga o que você compartilhar.</p>
      <div className="integration-tool-footer border-t border-line-soft text-xs"><div className="integration-tool-state"><span className="drive-dot-status" data-tone="neutral" /><span className="font-medium text-muted-foreground">Disponível</span></div><span className="integration-tool-actions flex items-center gap-2"><button type="button" onClick={onStart} className="mo-interactive rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground">Conectar</button></span></div>
    </> : <>
      <div className="drive-card-status"><span className="drive-dot-status" data-tone={status.tone} /><b>{status.label}</b>{syncBadge}</div>
      <p className="integration-tool-description">{status.description}</p>
      {robot && <div className="drive-card-robot"><span className="drive-mono" title={robot}>Robô: {robot}</span><CopyButton text={robot} label="Copiar" variant="ghost" size="sm" /></div>}
      {folders.length > 0 && <ul className="drive-card-folders">{folders.map((f) => {
        const days = daysUntil(f.purge_after, now); const lostFolder = f.status === "access_lost" || f.status === "purge_scheduled";
        return <li key={f.id} data-lost={lostFolder || undefined}><FolderOpen size={16} aria-hidden="true" /><div className="min-w-0 flex-1"><b className="drive-folder-name">{f.name}</b><span className="drive-folder-meta">{lostFolder ? `acesso removido${days !== null ? ` · apagando em ${days} ${days === 1 ? "dia" : "dias"}` : ""}` : `${f.file_count != null ? formatCount(f.file_count, "arquivo", "arquivos") : "contando arquivos"} · ${relativeSync(f.last_synced_at, now)}`}</span></div>
          {lostFolder && <button type="button" className={btn("danger-ghost", "sm")} disabled={busy !== null} onClick={() => purgeNow(f)}><Trash2 size={14} aria-hidden="true" />Apagar agora</button>}</li>;
      })}</ul>}
      {error && <p className="drive-field-error" role="alert"><CircleAlert size={14} aria-hidden="true" />{error}</p>}
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>
      <div className="integration-tool-footer border-t border-line-soft text-xs"><span className="integration-tool-actions flex items-center gap-2">
        {source.status !== "disconnected" && <button type="button" onClick={() => onDisconnect(source)} disabled={disconnecting} className={btn("danger-ghost", "sm")}><Unplug size={14} aria-hidden="true" />{disconnecting ? "Desconectando…" : "Desconectar"}</button>}
        {lost && <button type="button" onClick={() => sourceId && void fresh(() => client.recheck(sourceId), "recheck", "Acesso verificado novamente.")} disabled={busy !== null} aria-busy={busy === "recheck" || undefined} className={btn("secondary", "sm")}><RefreshCw size={14} aria-hidden="true" />Verificar agora</button>}
        {(connected || lost || status.tone === "pending") && <button type="button" onClick={() => onAddFolder(source)} className={btn("secondary", "sm")}>{connected || lost ? "Adicionar outra pasta" : "Compartilhar pasta"}</button>}
        {connected && <button type="button" onClick={() => onManage(source)} className="mo-interactive rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground">Gerenciar</button>}
      </span></div>
      {connected && <p className="integration-tool-note drive-add-note"><UserRound size={12} aria-hidden="true" /> Para incluir outra pasta, compartilhe com o mesmo e-mail e atualize.</p>}
    </>}
  </section>;
}

