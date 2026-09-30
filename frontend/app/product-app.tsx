"use client";

import { ArrowLeft, ChevronRight, CircleAlert, ExternalLink, FileText, FolderOpen, HardDrive, LogOut, PanelRightClose, PanelRightOpen, Plus, RefreshCw, Search, Send, Settings2, ShieldCheck, Sparkles, Table2, Trash2, Unplug, Users, X } from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { AccessSettings } from "./access-settings";
import { LandingPage } from "./landing-page";
import { cleanAnswerForDisplay } from "./answer-display";
import { AnswerMarkdown } from "./answer-markdown";
import "./chat-workspace.css";
import "./product-layout.css";
import { Brand } from "./brand";
import { QuestionScopePicker, contextReady, toolLabel, providerKey, type QuestionContext } from "./question-scope";
import { MentionComposer, type MentionCandidate } from "./mention-composer";
import { mentionSummary } from "./mention-label";
import { newSpaceOptions } from "./new-space-options";
import { ProviderLogo, type ProviderLogoName } from "./provider-logo";
import { oauthErrorMessage, providerLabel } from "./provider-labels";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const SESSION_PATH = API_BASE.replace(/\/$/, "") === "/api" ? "/session" : "/me";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Role = "owner" | "admin" | "member";
type Screen = "home" | "company" | "library" | "team" | "integrations" | "staff" | "invitation";
type Company = { id: string; name: string; membership_id: string; role: Role };
type User = { id: string; email: string; is_platform_staff?: boolean };
type Folder = { id: string; name: string; status: string; last_synced_at: string | null; source_id?: string; external_folder_id?: string; selection_kind?: string; selection_folder_ids?: string[] };
type DocumentFailure = { id: string; name: string; status: "failed"; error_code: string | null; source_url: string };
type LibraryDocumentRef = { workspace_folder_id: string; document_id: string };
type LibraryNode = { id: string; parent_id: string | null; source_id: string; source_provider?: string | null; kind: "source" | "folder" | "file"; external_id?: string; name: string; mime_type: string | null; source_url: string | null; workspace_documents?: LibraryDocumentRef[] };
type LibraryPage = { items: LibraryNode[]; page?: number; pages?: number; total?: number };
type LibraryContext = QuestionContext;
type LibrarySync = { id: string; source_id: string; workspace_folder_id: string; workspace_name: string; status: string; created_at: string; started_at: string | null; completed_at: string | null; error_code: string | null };
const FULL_RESYNC_CONFIRM = "Ressincronização completa: todos os arquivos serão relidos e reconstruídos (texto, OCR, trechos e embeddings), mesmo os que não mudaram. Pode levar bastante tempo e consumir a cota de processamento. Continuar?";
type ManualSync = { id: string; operation: "sync" | "resync"; mode?: "incremental" | "full" | null; scope_kind: string; scope_name: string; triggered_by: string | null; status: string; created_at: string; started_at: string | null; completed_at: string | null; total: number | null; processed: number | null; failed: number | null; failures: { external_id: string; name: string; error_code: string }[]; tasks: { workspace_folder_id: string; workspace_name: string; status: string; error_code: string | null }[] };
type Member = { id: string; email: string; role: Role };
type Source = { id: string; provider: string; status: string; account_email: string | null; connected_by_email?: string | null };
const latestSourcePerProvider = (items: Source[]) => [...new Map(items.map((item) => [item.provider, item])).values()];
type ToolCategory = "Arquivos" | "Documentação";
type RemoteFolder = { id: string; name: string; selectable?: boolean; parent_ids?: string[] };
type ScopeCatalog = { folders: RemoteFolder[]; root_files: { available: boolean; label: string }; all_accessible: { available: boolean; label: string } };
type SavedQuery = { id: string; workspace_folder_id: string; name: string; query: string };
type Evidence = { document_id: string; document_name: string; excerpt: string; page_number: number | null; source_url: string | null; source_provider?: string | null };
type Answer = { answer: string | null; confidence: string; citations: Evidence[]; retrieval_status: string; coverage?: { total_folders: number; eligible_folders: number; pending_folders: number }; conversation_id?: string };
type ConversationMessage = { id: string; role: "user" | "assistant"; content: string; contextName: string; contextId?: string; mentions?: MentionCandidate[]; providers?: string[]; allTools?: boolean; answer?: Answer; pending?: boolean; error?: string };
type PersistedConversationMessage = { id: string; role: "user" | "assistant"; content: string; context: { providers?: string[]; mentions?: MentionCandidate[] } | null; response: Answer | null };
type StaffCompany = { organization_id: string; name: string };
type StaffFolder = Folder & { failure_summary: { error_code: string; count: number }[] };
type StaffOverview = { organization_id: string; name: string; folders: StaffFolder[] };

class ApiError extends Error { constructor(public readonly status: number, message: string) { super(message); } }
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, ...init });
  if (response.status === 204) return undefined as T;
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string" ? body.detail : "Não foi possível concluir esta ação.";
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
const isUuid = (value: string | undefined): value is string => Boolean(value && UUID.test(value));
const isInvitationToken = (value: string | undefined): value is string => Boolean(value && /^[A-Za-z0-9_-]{20,128}$/.test(value));
const messageFor = (error: unknown) => error instanceof TypeError ? "Não conseguimos nos conectar ao serviço. Confira sua conexão e tente novamente." : error instanceof ApiError && error.status >= 500 ? "O serviço está temporariamente indisponível. Tente novamente em instantes." : error instanceof ApiError && error.status === 403 ? "Você não tem permissão para esta ação." : error instanceof Error ? error.message : "Ocorreu um erro inesperado.";
const roleLabel = (role: Role) => ({ owner: "Responsável", admin: "Administrador", member: "Membro" })[role];
const statusLabel = (status: string) => ({ ready: "Pronto", queued: "Na fila", syncing: "Sincronizando", partial_failure: "Com falhas", failed: "Falhou", pending: "Aguardando", connected: "Conectado", disconnected: "Desconectado", reauth_required: "Reconexão necessária" } as Record<string, string>)[status] ?? "Aguardando";
const documentFailureLabel = (code: string | null) => ({
  source_file_unavailable: "A fonte conectada não permitiu ler este arquivo.",
  text_extraction_failed: "Não foi possível extrair texto; o arquivo pode estar danificado ou usar uma estrutura não suportada.",
  file_too_large: "O arquivo excede o tamanho máximo suportado para indexação.",
  file_encrypted: "O arquivo está protegido por senha e não pode ser lido.",
  ocr_budget_exceeded: "O limite de OCR desta sincronização foi atingido; o arquivo será tentado novamente na próxima.",
  ocr_failed: "Não foi possível reconhecer o texto deste arquivo escaneado.",
  ocr_document_too_large: "O documento escaneado tem páginas demais para o OCR automático.",
  empty_extracted_text: "Nenhum texto foi extraído. Se o PDF é escaneado, o OCR não está ativo neste ambiente; peça ao administrador para ativá-lo.",
  empty_document: "O documento está vazio (não há texto para indexar).",
} as Record<string, string>)[code ?? ""] ?? "Não há uma explicação disponível para este código.";
const providerFromName = (name: string) => ({
  "google drive": "google_drive",
  onedrive: "onedrive",
  sharepoint: "sharepoint",
  notion: "notion",
} as Record<string, string | undefined>)[name.trim().toLowerCase()];
function ProviderMark({ provider, size = "md" }: { provider?: string | null; size?: "sm" | "md" }) {
  const key = providerKey(provider ?? "");
  if (["google", "onedrive", "sharepoint", "notion", "github", "teams"].includes(key)) return <ProviderLogo provider={key as ProviderLogoName} size={size === "sm" ? 18 : 26} />;
  return <HardDrive aria-hidden="true" size={size === "sm" ? 16 : 20} />;
}
function LibraryNodeIcon({ item, size = 16 }: { item: LibraryNode; size?: number }) {
  const isRoot = item.kind === "source" || item.parent_id === null;
  const provider = isRoot ? item.source_provider ?? providerFromName(item.name) : undefined;
  if (provider) return <ProviderMark provider={provider} size={size <= 14 ? "sm" : "md"} />;
  return item.kind === "file" ? <FileText size={size} /> : <FolderOpen size={size} />;
}
function useLatestRequest<T>() {
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const cancel = useCallback(() => controller.current?.abort(), []);
  const request = useCallback(async (path: string, onSuccess: (value: T) => void, onError: (error: unknown) => void, onSettled?: () => void) => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    try { const value = await api<T>(path, { signal: next.signal, cache: "no-store" }); if (!next.signal.aborted) onSuccess(value); }
    catch (error) { if (!next.signal.aborted) onError(error); }
    finally { if (!next.signal.aborted) onSettled?.(); }
  }, []);
  return { request, cancel };
}
const companyPath = (companyId: string, suffix = "") => `/companies/${companyId}${suffix}`;
const retrievalMessage = (status: string) => status === "no_indexed_content" ? "Ainda não há conteúdo consultável neste escopo. Aguarde a sincronização ou escolha outra pasta." : status === "no_compatible_embeddings" ? "O conteúdo foi encontrado, mas a indexação de IA ainda não terminou. Tente novamente em alguns instantes." : status === "invalid_generation_output" ? "Encontrei trechos relevantes, mas não foi possível produzir uma resposta verificável. Tente novamente." : "Não encontrei evidência suficiente neste escopo para responder com segurança.";
const answerText = (answer: Answer) => cleanAnswerForDisplay(answer.answer) || (answer.answer === null ? retrievalMessage(answer.retrieval_status) : "Confira as fontes abaixo.");
const citationSourceKey = (citation: Evidence) => {
  if (!citation.source_url?.trim()) return `document:${citation.document_id}`;
  try {
    const source = new URL(citation.source_url.trim());
    source.hash = "";
    if (source.pathname !== "/") source.pathname = source.pathname.replace(/\/+$/, "");
    return `source:${source.toString()}`;
  } catch {
    return `source:${citation.source_url.trim()}`;
  }
};
const compactCitations = (citations: Evidence[]): Evidence[] => {
  const grouped = new Map<string, Evidence>();
  for (const citation of citations) {
    const key = citationSourceKey(citation);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, citation);
      continue;
    }
    if (!existing.source_url && citation.source_url) existing.source_url = citation.source_url;
    if (!existing.source_provider && citation.source_provider) existing.source_provider = citation.source_provider;
  }
  return [...grouped.values()];
};

export function ProductApp({ screen }: { screen: Screen }) {
  const router = useRouter(); const pathname = usePathname(); const searchParams = useSearchParams(); const params = useParams<{ companyId?: string; token?: string }>();
  const [user, setUser] = useState<User | null>(null); const [companies, setCompanies] = useState<Company[]>([]); const [loading, setLoading] = useState(true); const [notice, setNotice] = useState<string | null>(null); const [error, setError] = useState<string | null>(null);
    const loadSession = useCallback(async () => {
      setLoading(true); setError(null);
    try { const current = await api<User | null>(SESSION_PATH); setUser(current); if (!current) { setCompanies([]); return; } const memberships = await api<Company[]>("/organizations"); setCompanies(memberships); if (screen === "home" && memberships[0]) router.replace(companyPath(memberships[0].id)); }
    catch (caught) { if (!(caught instanceof ApiError && caught.status === 401)) setError(messageFor(caught)); }
    finally { setLoading(false); }
  }, [router, screen]);
  useEffect(() => { void Promise.resolve().then(loadSession); }, [loadSession]);
  const oauthProvider = screen === "integrations" ? searchParams.get("connected") : null;
  const oauthError = screen === "integrations" ? searchParams.get("error") : null;
  const oauthFailure = oauthErrorMessage(oauthError);
  const oauthNotice = oauthProvider === "google_drive" ? "Google Drive conectado. Abra a ferramenta para definir o escopo e iniciar uma sincronização." : oauthProvider === "onedrive" ? "OneDrive conectado. Escolha as pastas que sua equipe pode consultar e inicie a sincronização." : oauthProvider === "sharepoint" ? "SharePoint conectado. Escolha as bibliotecas que sua equipe pode consultar e inicie a sincronização." : null;
  const dismissAlert = useCallback(() => { setNotice(null); setError(null); if (oauthNotice || oauthFailure) router.replace(pathname); }, [oauthFailure, oauthNotice, pathname, router]);
  const alertMessage = error ?? notice ?? oauthFailure ?? oauthNotice;
  useEffect(() => {
    if (!alertMessage || error) return;
    const timeout = window.setTimeout(dismissAlert, 6000);
    return () => window.clearTimeout(timeout);
  }, [alertMessage, dismissAlert, error]);
  const company = useMemo(() => companies.find((item) => item.id === params.companyId) ?? null, [companies, params.companyId]);
  const goCompany = (id: string) => { const suffix = pathname.endsWith("/team") ? "/team" : pathname.endsWith("/integrations") ? "/integrations" : pathname.endsWith("/library") ? "/library" : ""; router.push(companyPath(id, suffix)); };
  const beginLogin = (screenHint: "sign-in" | "sign-up") => { const query = new URLSearchParams({ screen_hint: screenHint }); if (screen === "invitation" && isInvitationToken(params.token)) query.set("return_to", pathname); window.location.assign(`${API_BASE}/auth/login?${query.toString()}`); };
  const logout = async () => { try { const { redirect_url } = await api<{ redirect_url: string }>("/auth/logout", { method: "POST" }); setUser(null); setCompanies([]); window.location.replace(redirect_url); } catch (caught) { setError(messageFor(caught)); } };
  if (loading && screen === "home" && pathname === "/") return <LandingPage onLogin={() => router.push("/login")} onSignUp={() => beginLogin("sign-up")} />;
  if (loading) return <Loading />;
  if (!user) return <>{screen === "home" && pathname === "/" ? <LandingPage onLogin={() => router.push("/login")} onSignUp={() => beginLogin("sign-up")} /> : <SignIn onLogin={() => beginLogin("sign-in")} onSignUp={() => beginLogin("sign-up")} />}{error && <div role="alert" className="session-error"><CircleAlert size={20} /><div><p>{error}</p><button onClick={() => { void loadSession(); }}>Tentar novamente</button></div></div>}</>;
  if (screen === "invitation") return <InvitationAcceptance token={params.token} onAccepted={(organizationId) => router.replace(companyPath(organizationId))} />;
  if (screen === "home" && companies.length > 0) return <Loading />;
  if (screen === "home") return <Onboarding user={user} onCreated={(created) => { setCompanies((items) => [...items, created]); router.push(companyPath(created.id)); }} />;
  if (screen === "staff") return <StaffCenter user={user} onBack={() => router.push(companies[0] ? companyPath(companies[0].id) : "/")} />;
  if (!isUuid(params.companyId) || !company) return <InvalidCompany companies={companies} onChoose={goCompany} />;
  return <Shell user={user} company={company} companies={companies} alertMessage={alertMessage} alertTone={error || oauthFailure ? "error" : "notice"} fillViewport={screen === "company" || screen === "library"} pageSurface={screen === "team" || screen === "integrations"} onDismiss={dismissAlert} onCompanyChange={goCompany} onNavigate={(path) => router.push(path)} onLogout={() => { void logout(); }}>
    {screen === "company" && <CompanyDashboard company={company} onConnect={() => router.push(companyPath(company.id, "/integrations"))} setError={setError} setNotice={setNotice} />}
    {screen === "library" && <LibraryScreen key={company.id} company={company} onConnect={() => router.push(companyPath(company.id, "/integrations"))} setError={setError} setNotice={setNotice} />}
    {screen === "team" && <TeamScreen key={company.id} company={company} setError={setError} setNotice={setNotice} />}
    {screen === "integrations" && (company.role === "member" ? <section role="alert" className="mx-auto max-w-lg rounded-lg border border-line bg-white p-8 text-center"><ShieldCheck className="mx-auto text-primary" size={28} /><h1 className="mt-4 text-xl font-semibold text-ink">Acesso restrito</h1><p className="mt-2 text-sm text-muted-foreground">Somente responsáveis e administradores podem gerenciar integrações.</p><button onClick={() => router.push(companyPath(company.id))} className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white">Voltar à conversa</button></section> : <div><IntegrationScreen key={company.id} company={company} setError={setError} setNotice={setNotice} /><AccessSettings key={`access-${company.id}`} organizationId={company.id} api={api} /></div>)}
  </Shell>;
}

function LoadingIndicator({ label, className = "" }: { label: string; className?: string }) {
  return <span role="status" aria-live="polite" className={`inline-flex items-center gap-2 ${className}`}><RefreshCw size={16} className="shrink-0 motion-safe:animate-spin" aria-hidden="true" /><span>{label}</span></span>;
}
function Loading() { return <main className="auth-page"><div className="text-center"><Brand /><LoadingIndicator label="Preparando seu espaço de conhecimento…" className="mt-3 justify-center text-sm text-muted-foreground" /></div></main>; }
function SignIn({ onLogin, onSignUp }: { onLogin: () => void; onSignUp: () => void }) {
  return <main className="auth-page"><section className="auth-card"><Link href="/" className="auth-brand"><Brand /></Link><p className="mt-12 text-xs font-semibold uppercase tracking-widest text-primary">Bom ter você por aqui</p><h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink">Sua equipe sabe.<br />Encontre a resposta.</h1><p className="mt-4 leading-7 text-muted-foreground">Entre para consultar seus documentos e conferir a fonte de cada resposta.</p><div className="mt-8 space-y-3"><button onClick={onLogin} className="w-full rounded-md bg-primary px-4 py-3 font-semibold text-white hover:bg-forest-hover">Entrar na minha conta</button><button onClick={onSignUp} className="w-full rounded-md border border-line bg-white px-4 py-3 font-semibold text-ink hover:bg-paper">Criar uma conta</button></div><p className="mt-7 text-center text-xs leading-5 text-muted-foreground">Os originais permanecem nas fontes conectadas.</p></section></main>;
}
function InvitationAcceptance({ token, onAccepted }: { token: string | undefined; onAccepted: (organizationId: string) => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  if (!isInvitationToken(token)) return <main className="auth-page"><section className="max-w-md text-center"><CircleAlert className="mx-auto text-amber-300" size={34} /><h1 className="mt-4 text-2xl font-semibold">Convite indisponível</h1><p className="mt-3 text-muted-foreground">Este link não é válido. Peça um novo convite à pessoa responsável pela organização.</p></section></main>;
  async function accept() { setBusy(true); setError(null); try { const accepted = await api<{ organization_id: string }>(`/invitations/${encodeURIComponent(token ?? "")}/accept`, { method: "POST" }); onAccepted(accepted.organization_id); } catch (caught) { setError(caught instanceof ApiError && caught.status === 404 ? "Este convite expirou, já foi usado ou não pertence ao seu e-mail." : messageFor(caught)); } finally { setBusy(false); } }
  return <main className="auth-page"><section className="auth-card"><Brand /><p className="mt-6 text-sm font-semibold text-primary">Convite para uma organização</p><h1 className="mt-2 text-3xl font-semibold">Participar da equipe</h1><p className="mt-3 leading-6 text-muted-foreground">Ao aceitar, você terá acesso aos recursos compartilhados com os membros desta organização.</p>{error && <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}<button disabled={busy} onClick={() => { void accept(); }} className="mt-7 w-full rounded-md bg-primary px-4 py-3 font-semibold text-white disabled:opacity-50">{busy ? "Aceitando…" : "Aceitar convite"}</button></section></main>;
}
function Onboarding({ user, onCreated }: { user: User; onCreated: (company: Company) => void }) {
  const [name, setName] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  async function create(event: FormEvent) { event.preventDefault(); setBusy(true); setError(null); try { const created = await api<{ id: string; membership_id: string; role: Role }>("/organizations", { method: "POST", body: JSON.stringify({ name: name.trim() }) }); onCreated({ ...created, name: name.trim() }); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); } }
  return <main className="auth-page"><section className="auth-card"><Brand /><p className="mt-6 text-sm text-muted-foreground">{user.email}</p><h1 className="mt-2 text-3xl font-semibold">Crie sua primeira organização</h1><p className="mt-3 leading-6 text-muted-foreground">Reúna os documentos da sua equipe em um só lugar. Depois, conecte uma fonte de arquivos e convide as pessoas com quem você trabalha.</p><form onSubmit={create} className="mt-7"><label htmlFor="company-name" className="text-sm font-medium">Nome da organização</label><input id="company-name" required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex.: Estúdio Aurora" className="mt-2 w-full rounded-md border border-line bg-white px-4 py-3 outline-none ring-primary focus:ring-2" aria-describedby={error ? "company-name-error" : undefined} />{error && <p id="company-name-error" role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}<button disabled={busy || !name.trim()} aria-busy={busy} className="mt-5 inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 font-semibold text-white disabled:opacity-50"><Plus size={17} aria-hidden="true" />{busy ? "Criando…" : "Criar organização"}</button></form></section></main>;
}
function InvalidCompany({ companies, onChoose }: { companies: Company[]; onChoose: (id: string) => void }) { return <main className="auth-page"><section className="max-w-md text-center"><CircleAlert className="mx-auto text-amber-300" size={34} /><h1 className="mt-4 text-2xl font-semibold">Esta organização não está disponível</h1><p className="mt-3 text-muted-foreground">Você não tem acesso a este espaço ou ele não está mais disponível. Escolha uma organização da qual você participa.</p><div className="mt-6 space-y-2">{companies.map((company) => <button key={company.id} onClick={() => onChoose(company.id)} className="flex w-full items-center justify-between rounded-md border border-line bg-white px-4 py-3 text-left hover:bg-sage"><span>{company.name}</span><ChevronRight size={16} /></button>)}</div></section></main>; }

function NotificationToast({ message, tone, onDismiss }: { message: string; tone: "notice" | "error"; onDismiss: () => void }) {
  const error = tone === "error";
  return <div className="pointer-events-none fixed inset-x-4 top-20 z-50 flex justify-end sm:inset-x-6" aria-live="polite">
    <div role={error ? "alert" : "status"} className={`pointer-events-auto w-full max-w-md overflow-hidden rounded-lg border bg-white shadow-xl ${error ? "border-rose-200" : "border-emerald-200"}`}>
      <div className="flex items-start gap-3 px-4 py-3.5"><CircleAlert className={`mt-0.5 shrink-0 ${error ? "text-rose-600" : "text-emerald-600"}`} size={18} /><p className={`min-w-0 flex-1 text-sm leading-5 ${error ? "text-rose-900" : "text-emerald-900"}`}>{message}</p><button onClick={onDismiss} className="-mr-1 -mt-1 rounded-lg p-1.5 text-muted-foreground hover:bg-sage hover:text-ink" aria-label="Fechar aviso"><X size={16} /></button></div>
      {!error && <div key={message} className="h-1 origin-left animate-[toast-progress_6000ms_linear_forwards] bg-emerald-500" />}
    </div>
  </div>;
}

function Shell({ user, company, companies, children, alertMessage, alertTone, fillViewport, pageSurface, onDismiss, onCompanyChange, onNavigate, onLogout }: { user: User; company: Company; companies: Company[]; children: ReactNode; alertMessage: string | null; alertTone: "notice" | "error"; fillViewport: boolean; pageSurface: boolean; onDismiss: () => void; onCompanyChange: (id: string) => void; onNavigate: (path: string) => void; onLogout: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => { if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setMenuOpen(false); menuRef.current?.querySelector("button")?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [menuOpen]);
        const canManage = company.role !== "member";
  const go = (suffix = "") => { setMenuOpen(false); onNavigate(companyPath(company.id, suffix)); };
  return <main className={`product-app ${fillViewport ? "flex h-dvh flex-col overflow-hidden" : "min-h-screen"} bg-paper text-ink`}>
    <header className="product-header z-20 shrink-0 border-b border-line">
      <div className="product-header-inner mx-auto flex max-w-7xl items-center gap-3 px-4 py-4">
        <button onClick={() => go()} className="product-brand-button" aria-label="Arquivio, ir para consultas"><Brand compact /></button>
        <select aria-label="Organização ativa" value={company.id} onChange={(event) => onCompanyChange(event.target.value)} className="organization-select max-w-52 rounded-lg border border-line bg-white px-3 py-2 text-sm font-semibold">{companies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <span className="hidden rounded-full bg-sage px-2.5 py-1 text-xs font-semibold capitalize text-muted-foreground sm:inline">{roleLabel(company.role)}</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden text-sm text-muted-foreground md:block">{user.email}</span>
          {user.is_platform_staff && <button onClick={() => { setMenuOpen(false); onNavigate("/staff"); }} className="rounded-lg border border-violet-200 px-3 py-2 text-xs font-semibold text-violet-700"><ShieldCheck className="mr-1 inline" size={14} />Suporte</button>}
          <div ref={menuRef} className="relative">
            <button onClick={() => setMenuOpen((open) => !open)} aria-expanded={menuOpen} aria-label="Navegação principal" aria-controls="product-navigation" className="inline-flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-2 text-sm font-semibold text-ink shadow-sm hover:bg-paper"><span className="hidden sm:inline">Navegar</span><ChevronRight size={16} className={`transition-transform ${menuOpen ? "rotate-90" : ""}`} /></button>
            {menuOpen && <nav id="product-navigation" aria-label="Navegação principal" className="absolute right-0 mt-2 w-60 overflow-hidden rounded-lg border border-line bg-white p-1.5 shadow-xl">
              <button onClick={() => go()} className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><Sparkles size={16} className="text-primary" /><span><span className="block">Consultas</span><span className="block text-xs font-normal text-muted-foreground">Voltar à conversa</span></span></button>
              <button onClick={() => go("/library")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><FolderOpen size={16} className="text-primary" /><span><span className="block">Biblioteca</span><span className="block text-xs font-normal text-muted-foreground">Explore e gerencie o índice</span></span></button>
              {company.role === "owner" && <button onClick={() => go("/team")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><Users size={16} className="text-primary" /><span><span className="block">Equipe</span><span className="block text-xs font-normal text-muted-foreground">Membros e convites</span></span></button>}
              {canManage && <button onClick={() => go("/integrations")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><HardDrive size={16} className="text-primary" /><span><span className="block">Integrações</span><span className="block text-xs font-normal text-muted-foreground">Fontes e sincronizações</span></span></button>}
            </nav>}
          </div>
          <button onClick={onLogout} aria-label="Sair da conta" title="Sair" className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><LogOut size={18} /></button>
        </div>
      </div>
    </header>
    {alertMessage && <NotificationToast message={alertMessage} tone={alertTone} onDismiss={onDismiss} />}
    <div className={`product-content mx-auto w-full max-w-7xl p-4 ${fillViewport ? "min-h-0 flex-1" : ""}`}><section className={`min-w-0 ${fillViewport ? "workspace-shell h-full min-h-0" : ""} ${pageSurface ? "page-surface" : ""}`}>{children}</section></div>
  </main>;
}

function CompanyDashboard({ company, onConnect, setError, setNotice }: { company: Company; onConnect: () => void; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  return <ConversationLibraryWorkspace key={company.id} company={company} onConnect={onConnect} setError={setError} setNotice={setNotice} />;
}

function LibraryScreen({ company, onConnect, setError, setNotice }: { company: Company; onConnect: () => void; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [spacesPanelOpen, setSpacesPanelOpen] = useState(false);
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
  const [path, setPath] = useState<LibraryNode[]>([]); const [items, setItems] = useState<LibraryNode[]>([]); const [folders, setFolders] = useState<Folder[]>([]); const [foldersLoading, setFoldersLoading] = useState(true); const [loading, setLoading] = useState(true); const [busyFolderId, setBusyFolderId] = useState<string | null>(null); const [busyFolderAction, setBusyFolderAction] = useState<"sync" | "remove" | null>(null); const [busyFileId, setBusyFileId] = useState<string | null>(null); const [busyNodeId, setBusyNodeId] = useState<string | null>(null);
  const [documentFailures, setDocumentFailures] = useState<Record<string, DocumentFailure[]>>({}); const [failureLoadError, setFailureLoadError] = useState<Record<string, boolean>>({}); const [folderActionErrors, setFolderActionErrors] = useState<Record<string, string>>({}); const [folderSyncJobs, setFolderSyncJobs] = useState<Record<string, string>>({}); const [folderSyncAnnouncements, setFolderSyncAnnouncements] = useState<Record<string, string>>({});
  const canManage = company.role !== "member"; const current = path.at(-1);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<{ page: number; pages: number; total: number } | null>(null);
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const { request: requestItems } = useLatestRequest<LibraryPage>();
  const { request: requestRoots } = useLatestRequest<LibraryPage>();
  const openPath = (nodes: LibraryNode[]) => { setPath(nodes); setPage(1); setQuery(""); setSearchTerm(""); };
  const loadRoots = useCallback(() => { setRootsLoading(true); setRootsError(null); void requestRoots(`/library?organization_id=${company.id}`, (result) => setRoots(result.items), (caught) => setRootsError(messageFor(caught)), () => setRootsLoading(false)); }, [company.id, requestRoots]);
  useEffect(() => { void Promise.resolve().then(loadRoots); }, [loadRoots]);
  const refreshLibrary = () => { loadRoots(); loadItems(); };

  const loadItems = useCallback(() => {
    setLoadError(null); setItems([]); setPagination(null);
    if (!searchTerm && !current) { setLoading(false); return; }
    setLoading(true);
    const request = searchTerm ? `/library/search?organization_id=${company.id}&query=${encodeURIComponent(searchTerm)}` : `/library/nodes/${current!.id}/children?organization_id=${company.id}&page=${page}`;
    void requestItems(request, (result) => { setItems(result.items); setPagination(typeof result.page === "number" && typeof result.pages === "number" && typeof result.total === "number" ? { page: result.page, pages: result.pages, total: result.total } : null); }, (caught) => setLoadError(messageFor(caught)), () => setLoading(false));
  }, [company.id, current, page, searchTerm, requestItems]);
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
  useEffect(() => { void Promise.resolve().then(loadItems); }, [loadItems]); useEffect(() => { void Promise.resolve().then(loadFolders); }, [loadFolders]);
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
          pollingErrors.forEach(([folderId, , , error]) => { nextErrors[folderId] = `Não foi possível consultar o progresso da sincronização. Atualize os espaços para conferir o estado. ${error}`; });
          return nextErrors;
        });
        setFolderSyncJobs((currentJobs) => {
          const nextJobs = { ...currentJobs };
          pollingErrors.forEach(([folderId, jobId]) => { if (nextJobs[folderId] === jobId) delete nextJobs[folderId]; });
          return nextJobs;
        });
        setFolderSyncAnnouncements((current) => {
          const next = { ...current };
          pollingErrors.forEach(([folderId]) => { next[folderId] = "Não foi possível atualizar o progresso. Atualize os espaços para conferir o estado."; });
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
    try { const result = await api<{ run_id: string; job_ids: string[] }>(`/library/nodes/${item.id}/reprocess?organization_id=${company.id}`, { method: "POST" }); await confirmResyncHistory(result.run_id); if (!result.job_ids?.length) throw new Error("Nenhum trabalho de ressincronização foi iniciado. Selecione um espaço na integração e tente novamente."); setNotice(`Sincronização incremental de “${item.name}” agendada: só o que é novo ou mudou na origem é atualizado.`); setSpacesPanelOpen(true); loadHistory(); loadFolders(); }
    catch (caught) { const cooldown = messageFor(caught).includes("too soon"); const detail = cooldown ? `“${item.name}” foi sincronizada há instantes. Aguarde cerca de um minuto para sincronizar de novo.` : `Não foi possível confirmar a sincronização de “${item.name}”. ${messageFor(caught)}`; setError(detail); setSyncHistoryError(detail); } finally { setBusyNodeId(null); }
  }
  async function removeFolderNode(item: LibraryNode) {
    if (!window.confirm(`Remover a pasta “${item.name}” da Biblioteca? Ela, suas subpastas e seus arquivos serão removidos do índice e da Biblioteca e não voltarão nas próximas sincronizações ou ressincronizações. Os originais continuarão na fonte conectada.`)) return;
    setBusyNodeId(item.id); setError(null);
    try { const result = await api<{ documents: number }>(`/library/nodes/${item.id}/index?organization_id=${company.id}`, { method: "DELETE" }); setNotice(`“${item.name}” foi removida do índice local (${result.documents} arquivo${result.documents === 1 ? "" : "s"}).`); loadItems(); loadFolders(); }
    catch (caught) { setError(messageFor(caught)); } finally { setBusyNodeId(null); }
  }
  function goBack() { if (searchTerm) { setQuery(""); setSearchTerm(""); setPage(1); return; } if (path.length > 1) openPath(path.slice(0, -1)); }
  async function syncFolder(folder: Folder) { setBusyFolderId(folder.id); setBusyFolderAction("sync"); setError(null); setFolderActionErrors((currentErrors) => { const nextErrors = { ...currentErrors }; delete nextErrors[folder.id]; return nextErrors; }); setFolderSyncAnnouncements((current) => ({ ...current, [folder.id]: "Sincronização na fila." })); try { const result = await api<{ run_id: string; job_id: string; status: string }>(`/library/workspaces/${folder.id}/reprocess?organization_id=${company.id}`, { method: "POST" }); await confirmResyncHistory(result.run_id); if (!result.job_id) throw new Error("Nenhum trabalho de ressincronização foi confirmado."); setFolders((currentFolders) => currentFolders.map((currentFolder) => currentFolder.id === folder.id ? { ...currentFolder, status: result.status } : currentFolder)); setFolderSyncJobs((currentJobs) => ({ ...currentJobs, [folder.id]: result.job_id })); setNotice(`Sincronização incremental de “${folder.name}” iniciada em segundo plano: só o que é novo ou mudou na origem é atualizado.`); loadHistory(); } catch (caught) { const detail = messageFor(caught); setFolderActionErrors((currentErrors) => ({ ...currentErrors, [folder.id]: `Não foi possível resincronizar este espaço. ${detail}` })); } finally { setBusyFolderId(null); setBusyFolderAction(null); } }
  async function removeFolder(folder: Folder) { if (!window.confirm(`Excluir o espaço “${folder.name}” e todos os dados locais dele no Arquivio? Isso remove documentos indexados, trechos, embeddings e consultas salvas. Nenhum arquivo ou pasta será apagado da fonte original.`)) return; setBusyFolderId(folder.id); setBusyFolderAction("remove"); setError(null); setFolderActionErrors((currentErrors) => { const nextErrors = { ...currentErrors }; delete nextErrors[folder.id]; return nextErrors; }); try { await api<void>(`/workspace-folders/${folder.id}?organization_id=${company.id}`, { method: "DELETE" }); setFolders((currentFolders) => currentFolders.filter((currentFolder) => currentFolder.id !== folder.id)); setNotice(`O espaço “${folder.name}” e seus dados locais foram excluídos do Arquivio.`); loadFolders(); loadItems(); } catch (caught) { const detail = messageFor(caught); setFolderActionErrors((currentErrors) => ({ ...currentErrors, [folder.id]: `Não foi possível excluir os dados locais deste espaço. ${detail}` })); } finally { setBusyFolderId(null); setBusyFolderAction(null); } }
  async function removeFileNode(item: LibraryNode) { const refs = item.workspace_documents ?? []; if (refs.length === 0) { setError("Este arquivo não possui uma cópia indexada disponível para remover."); return; } if (!window.confirm(`Remover “${item.name}” da Biblioteca? O arquivo será removido do índice e da Biblioteca e não voltará nas próximas sincronizações ou ressincronizações. O original continuará na fonte conectada.`)) return; setBusyFileId(item.id); setError(null); try { for (const ref of refs) await api<void>(`/workspace-folders/${ref.workspace_folder_id}/documents/${ref.document_id}?organization_id=${company.id}`, { method: "DELETE" }); setNotice(`“${item.name}” foi removido do índice local.`); loadItems(); loadFolders(); } catch (caught) { setError(messageFor(caught)); } finally { setBusyFileId(null); } }
  return <><div className="workspace-frame overflow-hidden border border-line bg-white"><div className="grid library-panels min-h-[calc(100vh-14rem)]"><aside aria-label="Ferramentas integradas" className="border-b border-line bg-sage xl:border-b-0 xl:border-r"><LibrarySidebarHeader canManage={canManage} onConnect={onConnect} onRefresh={refreshLibrary} /><p className="px-4 pb-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Ferramentas integradas</p><nav className="max-h-72 space-y-0.5 overflow-y-auto px-2 pb-4 xl:max-h-[calc(100vh-18rem)]">{rootsLoading && roots.length === 0 ? <LoadingIndicator label="Carregando ferramentas…" className="p-3 text-sm text-muted-foreground" /> : rootsError ? <div role="alert" className="px-2 py-3 text-sm text-rose-700">{rootsError}<button onClick={loadRoots} className="mt-2 block font-semibold underline">Tentar novamente</button></div> : roots.length === 0 ? <div className="px-2 py-3 text-sm text-muted-foreground"><HardDrive size={18} className="mb-2 text-primary" />Nenhuma ferramenta conectada.{canManage && <button onClick={onConnect} className="mt-2 block font-semibold text-primary underline">Conectar uma fonte</button>}</div> : roots.map((item) => { const active = path[0]?.id === item.id; return <div key={item.id} className="flex items-center gap-1"><button onClick={() => openPath([item])} aria-current={active ? "true" : undefined} className={`flex min-h-11 min-w-0 flex-1 items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm transition-colors ${active ? "bg-white font-semibold text-ink shadow-sm ring-1 ring-line" : "text-ink hover:bg-white/70"}`}><span className="grid size-7 shrink-0 place-items-center rounded-lg bg-sage-selected text-primary"><LibraryNodeIcon item={item} size={14} /></span><span className="min-w-0 flex-1 truncate">{item.name}</span>{active && <ChevronRight size={14} className="text-muted-foreground" aria-hidden="true" />}</button>{<button disabled={busyNodeId !== null} onClick={() => { void reprocessFolderNode(item); }} aria-label={`Sincronizar alterações de toda a integração ${item.name}`} title="Sincronizar só o que mudou (incremental)" className="grid size-10 shrink-0 place-items-center rounded-md text-muted-foreground hover:bg-white hover:text-primary disabled:opacity-40"><RefreshCw size={14} className={busyNodeId === item.id ? "motion-safe:animate-spin" : ""} /></button>}</div>; })}</nav></aside><main className="relative min-w-0 p-4 sm:p-5" aria-busy={loading}><div className="flex items-center gap-2"><button type="button" onClick={goBack} disabled={!searchTerm && path.length <= 1} aria-label={searchTerm ? "Sair da busca" : "Voltar para a pasta anterior"} title={searchTerm ? "Sair da busca" : "Voltar para a pasta anterior"} className="grid size-9 shrink-0 place-items-center rounded-lg border border-line text-ink hover:bg-sage disabled:cursor-not-allowed disabled:opacity-40"><ArrowLeft size={16} aria-hidden="true" /></button><nav aria-label="Caminho da pasta" className="flex min-w-0 flex-1 flex-wrap items-center gap-0.5 text-sm">{searchTerm ? <span className="truncate px-1.5 font-semibold text-ink">Resultados para “{searchTerm}”</span> : path.length === 0 ? <span className="px-1.5 font-semibold text-ink">Selecione uma ferramenta</span> : path.map((node, index) => <span key={node.id} className="flex min-w-0 items-center">{index > 0 && <ChevronRight size={13} className="shrink-0 text-muted-foreground" aria-hidden="true" />}<button onClick={() => openPath(path.slice(0, index + 1))} aria-current={index === path.length - 1 ? "page" : undefined} className={`max-w-40 truncate rounded-md px-1.5 py-1 ${index === path.length - 1 ? "font-semibold text-ink" : "text-primary hover:bg-sage"}`}>{node.name}</button></span>)}</nav>{(current || searchTerm) && <span className="shrink-0 rounded-full bg-sage px-2.5 py-1 text-xs tabular-nums text-muted-foreground">{pagination?.total ?? items.length} itens</span>}<button type="button" onClick={() => { setSpacesPanelOpen(true); loadHistory(); }} aria-haspopup="dialog" className="inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg border border-line px-3 text-xs font-semibold text-ink hover:bg-sage"><RefreshCw size={15} /><span className="hidden sm:inline">Sincronizações</span></button></div><form onSubmit={(event) => { event.preventDefault(); setPage(1); setSearchTerm(query.trim()); }} className="mt-3 flex gap-2"><label htmlFor="library-search" className="sr-only">Buscar arquivos e pastas por nome</label><input id="library-search" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} placeholder="Buscar pelo nome em toda a biblioteca" className="min-w-0 flex-1 rounded-md border border-line px-3 py-2.5 text-sm" /><button aria-label="Buscar na biblioteca" className="rounded-md bg-primary px-3 text-white"><Search size={18} /></button>{searchTerm && <button type="button" onClick={() => { setQuery(""); setSearchTerm(""); setPage(1); }} aria-label="Limpar busca" className="rounded-md border border-line px-3"><X size={17} /></button>}</form>{searchTerm && <p className="mt-2 text-xs text-muted-foreground">Busca por nome em todas as fontes conectadas.</p>}
      {loading ? <div className="library-empty"><LoadingIndicator label="Carregando arquivos…" /></div> : loadError ? <div role="alert" className="library-empty"><CircleAlert size={24} /><p>{loadError}</p><button onClick={loadItems} className="text-sm font-semibold text-primary underline">Tentar novamente</button></div> : items.length === 0 ? <div className="library-empty"><FolderOpen size={32} /><h2 className="font-semibold text-ink">{searchTerm ? "Nenhum resultado encontrado" : current ? "Esta pasta está vazia" : roots.length > 0 ? "Escolha uma ferramenta" : "Sua biblioteca começa aqui"}</h2><p className="max-w-sm text-sm leading-6">{searchTerm ? "Tente uma palavra diferente ou parte do nome do arquivo." : current ? "Os arquivos aparecerão aqui depois da sincronização." : roots.length > 0 ? "Selecione uma ferramenta na barra lateral para explorar seus arquivos e pastas." : canManage ? "Conecte uma fonte e escolha as pastas que sua equipe pode consultar." : "Um administrador precisa conectar uma fonte e sincronizar as pastas da equipe."}</p>{!current && !searchTerm && canManage && roots.length === 0 && <button onClick={onConnect} className="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white">Conectar uma fonte</button>}</div> : <ul className="mt-3 divide-y divide-line overflow-hidden rounded-lg border border-line bg-white" aria-label="Arquivos e pastas">{items.map((item) => { const isFolder = item.kind !== "file"; const indexed = item.kind === "file" && (item.workspace_documents?.length ?? 0) > 0; const busy = busyNodeId === item.id; const status = isFolder ? "" : indexed ? "Indexado" : "Não indexado"; return <li key={item.id} className="group flex min-h-11 items-center gap-1 px-2 py-1 hover:bg-sage/60"><button onClick={() => openItem(item)} className="flex min-w-0 flex-1 items-center gap-3 rounded-md px-1 py-1 text-left"><span className={`grid size-8 shrink-0 place-items-center rounded-md ${isFolder ? "bg-sage-selected text-primary" : "bg-sage text-muted-foreground"}`}><LibraryNodeIcon item={item} size={16} /></span><span className="min-w-0 flex-1"><b className="block truncate text-sm font-medium text-ink">{item.name}</b></span><span className="hidden shrink-0 text-xs text-muted-foreground sm:block">{item.kind === "file" ? (item.mime_type?.split("/").pop() ?? "Arquivo") : item.kind === "source" ? "Integração" : "Pasta"}</span>{status && <span className={`hidden shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold md:block ${busy ? "bg-sage-selected text-primary" : status === "Indexado" ? "bg-emerald-100 text-emerald-800" : "bg-sage text-muted-foreground"}`}>{status}</span>}{isFolder ? <ChevronRight size={15} className="shrink-0 text-muted-foreground" aria-hidden="true" /> : item.source_url ? <ExternalLink size={14} className="shrink-0 text-muted-foreground" aria-hidden="true" /> : null}</button>{canManage && item.kind === "file" && indexed && <button disabled={busyFileId !== null} aria-busy={busyFileId === item.id} onClick={() => { void removeFileNode(item); }} title="Remover do índice" aria-label={`Remover ${item.name} do índice`} className="grid size-9 shrink-0 place-items-center rounded-lg text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40">{busyFileId === item.id ? <RefreshCw size={15} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={15} aria-hidden="true" />}</button>}{item.kind === "folder" && <><button disabled={busyNodeId !== null} onClick={() => { void reprocessFolderNode(item); }} title="Sincronizar só o que mudou (incremental)" aria-label={`Sincronizar alterações da pasta ${item.name}`} className="grid size-9 shrink-0 place-items-center rounded-lg text-muted-foreground hover:bg-white hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"><RefreshCw size={15} className={busy ? "motion-safe:animate-spin" : ""} aria-hidden="true" /></button>{canManage && <button disabled={busyNodeId !== null} onClick={() => { void removeFolderNode(item); }} title="Remover pasta" aria-label={`Remover pasta ${item.name}`} className="grid size-9 shrink-0 place-items-center rounded-lg text-rose-600 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-40"><Trash2 size={15} aria-hidden="true" /></button>}</>}</li>; })}</ul>}{pagination && pagination.pages > 1 && <Pagination value={pagination} loading={loading} onChange={setPage} />}</main></div></div><dialog ref={syncDialog} onClose={() => setSpacesPanelOpen(false)} aria-labelledby="library-sync-title" className="library-sync-dialog"><section className="p-5 sm:p-6"><div className="flex items-start justify-between gap-4"><div><h2 id="library-sync-title" className="text-xl font-semibold text-ink">Sincronizações</h2><p className="mt-1 text-sm text-muted-foreground">Acompanhe o histórico e gerencie seus espaços sincronizados.</p></div><button onClick={() => setSpacesPanelOpen(false)} className="grid size-10 shrink-0 place-items-center rounded-lg hover:bg-sage" aria-label="Fechar sincronizações"><X size={18} /></button></div><div className="mt-6 flex items-center justify-between"><h3 className="text-sm font-semibold">Histórico de sincronizações</h3><button onClick={() => { loadHistory(); loadFolders(); }} aria-label="Atualizar sincronizações" className="grid size-10 place-items-center rounded-lg hover:bg-sage"><RefreshCw size={15} /></button></div><p className="text-xs text-muted-foreground">Sincronizações e ressincronizações, incluindo subpastas. O histórico atualiza a cada 3 segundos.</p>{syncHistoryError && <p role="alert" className="mt-3 text-sm text-rose-700">{syncHistoryError}</p>}<div aria-live="polite" className="mt-3 space-y-3">{manualSyncs.length === 0 ? <p className="rounded-lg border border-dashed border-line p-4 text-sm text-muted-foreground">Nenhuma sincronização registrada.</p> : manualSyncs.map((run) => <article key={run.id} className="rounded-lg border border-line bg-white p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-[11px] uppercase tracking-wide text-muted-foreground">{run.operation === "sync" ? "Sincronização" : "Ressincronização"}{run.mode && <> · <b className="font-semibold">{run.mode === "full" ? "Completa" : "Incremental"}</b></>} · {run.scope_kind === "source" ? "Integração" : run.scope_kind === "folder" ? "Pasta e subpastas" : "Espaço sincronizado"}</p><h4 className="mt-1 font-semibold text-ink">{run.scope_name}</h4></div><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${run.status === "ready" ? "bg-emerald-100 text-emerald-800" : run.status === "failed" ? "bg-rose-100 text-rose-800" : run.status === "partial_failure" ? "bg-amber-100 text-amber-800" : "bg-sage text-primary"}`}>{{ queued: "Na fila", syncing: "Rodando", ready: "Concluído", failed: "Falhou", partial_failure: "Parcial" }[run.status] ?? run.status}</span></div><p className="mt-2 break-all text-xs text-muted-foreground">{run.triggered_by ? `Disparado por ${run.triggered_by}` : "Sincronização do espaço"} · {new Date(run.created_at).toLocaleString("pt-BR")}</p><p className="mt-1 text-xs text-muted-foreground">Início: {run.started_at ? new Date(run.started_at).toLocaleString("pt-BR") : "Aguardando"} · Fim: {run.completed_at ? new Date(run.completed_at).toLocaleString("pt-BR") : "—"}</p><p className="mt-3 text-xs font-medium text-ink">{run.total === null ? "Contagem de arquivos indisponível para esta sincronização." : <>{run.processed} de {run.total} arquivos processados · {run.failed} falhas{run.status === "syncing" && run.total === 0 ? " · Descobrindo arquivos…" : ""}</>}</p>{run.total !== null && run.total > 0 && <progress aria-label={`Progresso de ${run.scope_name}`} value={run.processed ?? 0} max={run.total} className="mt-2 h-2 w-full accent-primary" />}{run.failures.length > 0 && <details className="mt-3 text-xs text-rose-800"><summary className="cursor-pointer font-semibold">Falhas por documento ({run.failed})</summary><ul className="mt-2 space-y-2">{run.failures.map((file) => <li key={file.external_id} className="break-words">{file.name} · {documentFailureLabel(file.error_code)} ({file.error_code})</li>)}</ul></details>}{run.tasks.some((task) => task.error_code) && <ul className="mt-3 space-y-1 text-xs text-rose-700">{run.tasks.filter((task) => task.error_code).map((task, index) => <li key={index}>{task.workspace_name}: {task.error_code}</li>)}</ul>}</article>)}</div><h3 className="mt-7 text-sm font-semibold">Espaços sincronizados</h3><p className="mt-1 text-xs text-muted-foreground">Gerencie o índice local de cada espaço.</p><div className="mt-4 space-y-3">{foldersLoading && folders.length === 0 ? <LoadingIndicator label="Carregando espaços sincronizados…" className="rounded-md border border-dashed p-4 text-sm text-muted-foreground" /> : folders.length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">Nenhum espaço sincronizado.</p> : folders.map((folder) => <article key={folder.id} className="rounded-lg border border-line bg-white p-4"><div className="flex items-start justify-between gap-2"><b className="min-w-0 truncate text-sm text-ink">{folder.name}</b><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${folderSyncActive(folder.id) ? "bg-sage-selected text-primary" : folder.status === "ready" ? "bg-emerald-100 text-emerald-800" : folder.status === "partial_failure" ? "bg-amber-100 text-amber-800" : "bg-sage-selected text-primary"}`}>{(folderSyncActive(folder.id) || folder.status === "queued" || folder.status === "syncing") && <RefreshCw size={11} className="mr-1 inline motion-safe:animate-spin" aria-hidden="true" />}{folderSyncActive(folder.id) ? "Sincronizando" : statusLabel(folder.status)}</span></div><p className="mt-2 text-xs text-muted-foreground">{folder.last_synced_at ? `Última sincronização: ${new Date(folder.last_synced_at).toLocaleString("pt-BR")}` : "Ainda não sincronizado"}</p><p role="status" aria-live="polite" className="mt-2 text-xs font-medium text-primary">{folderSyncActive(folder.id) ? `${folderSyncAnnouncements[folder.id] ?? "Sincronização em andamento."} A exclusão dos dados locais ficará disponível quando a operação terminar.` : folderSyncAnnouncements[folder.id] ?? ""}</p>{canManage && folder.status === "partial_failure" && <section className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3" aria-label={`Falhas da pasta ${folder.name}`}><p className="text-xs font-semibold text-amber-900">Arquivos com falha</p>{failureLoadError[folder.id] ? <p className="mt-2 text-xs text-amber-900">Não foi possível carregar os detalhes. Atualize os espaços e tente novamente.</p> : documentFailures[folder.id] ? documentFailures[folder.id].length === 0 ? <p className="mt-2 text-xs text-amber-900">Nenhuma falha de arquivo encontrada.</p> : <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto">{documentFailures[folder.id].map((file) => <li key={file.id} className="border-t border-amber-200 pt-2"><p className="break-words text-xs font-medium text-ink">{file.name}</p><p className="mt-0.5 text-[11px] text-amber-900">{documentFailureLabel(file.error_code)} <code>({file.error_code ?? "sem código"})</code></p></li>)}</ul> : <p role="status" className="mt-2 text-xs text-amber-900">Carregando detalhes…</p>}</section>}{folderActionErrors[folder.id] && <div role="alert" className="library-space-error mt-3"><CircleAlert size={15} aria-hidden="true" /><p>{folderActionErrors[folder.id]}</p></div>}{canManage && <div className="library-space-actions mt-4"><button disabled={busyFolderId !== null || Boolean(folderSyncActive(folder.id)) || folder.status === "queued" || folder.status === "syncing"} aria-busy={busyFolderId === folder.id && busyFolderAction === "sync"} onClick={() => { void syncFolder(folder); }} className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg border border-line px-3 py-2 text-xs font-semibold text-ink hover:bg-paper disabled:cursor-not-allowed disabled:opacity-50"><RefreshCw size={14} className={busyFolderId === folder.id && busyFolderAction === "sync" ? "motion-safe:animate-spin" : ""} aria-hidden="true" />{busyFolderId === folder.id && busyFolderAction === "sync" ? "Iniciando…" : folderSyncActive(folder.id) || folder.status === "queued" || folder.status === "syncing" ? "Sincronizando…" : "Ressincronizar"}</button><button disabled={busyFolderId !== null || Boolean(folderSyncActive(folder.id)) || folder.status === "queued" || folder.status === "syncing"} onClick={() => { void removeFolder(folder); }} className="inline-flex min-h-10 flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-200 px-3 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50" title={folderSyncActive(folder.id) || folder.status === "queued" || folder.status === "syncing" ? "Aguarde o fim da sincronização para excluir os dados locais" : "Excluir espaço e dados locais"} aria-busy={busyFolderId === folder.id && busyFolderAction === "remove"}>{busyFolderId === folder.id && busyFolderAction === "remove" ? <RefreshCw size={14} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={14} aria-hidden="true" />}{busyFolderId === folder.id && busyFolderAction === "remove" ? "Excluindo…" : "Excluir dados locais"}</button></div>}</article>)}</div></section></dialog></>;
}

function Pagination({ value, loading, onChange }: { value: { page: number; pages: number; total: number }; loading: boolean; onChange: (page: number) => void }) {
  return <nav aria-label="Paginação da biblioteca" className="mt-4 flex items-center justify-between gap-3 border-t border-line px-2 py-3 text-xs text-muted-foreground"><span>Página {value.page} de {value.pages} · {value.total} itens</span><div className="flex gap-1"><button disabled={loading || value.page <= 1} onClick={() => onChange(value.page - 1)} aria-label="Página anterior" className="rounded-lg border border-line bg-white px-2.5 py-2 disabled:opacity-40">←</button><button disabled={loading || value.page >= value.pages} onClick={() => onChange(value.page + 1)} aria-label="Próxima página" className="rounded-lg border border-line bg-white px-2.5 py-2 disabled:opacity-40">→</button></div></nav>;
}

function LibrarySidebarHeader({ canManage, onConnect, onRefresh }: { canManage: boolean; onConnect: () => void; onRefresh: () => void }) {
  return <div className="flex items-center justify-between px-4 pb-3 pt-4"><div><p className="text-sm font-semibold text-ink">Biblioteca</p><p className="mt-0.5 text-xs text-muted-foreground">Arquivos e pastas sincronizados</p></div><div className="flex items-center gap-1">{canManage && <button onClick={onConnect} className="rounded-lg p-2 text-primary hover:bg-sage-selected" aria-label="Adicionar fonte" title="Adicionar fonte"><Plus size={17} /></button>}<button onClick={onRefresh} className="rounded-lg p-2 text-muted-foreground hover:bg-sage-selected" aria-label="Atualizar biblioteca" title="Atualizar biblioteca"><RefreshCw size={15} /></button></div></div>;
}

function LibraryBreadcrumbs({ path, onOpenPath }: { path: LibraryNode[]; onOpenPath: (nodes: LibraryNode[]) => void }) {
  return <nav className="flex flex-wrap items-center gap-1 px-3 pb-3 text-xs" aria-label="Caminho das fontes"><button onClick={() => onOpenPath([])} className={`rounded-md px-2 py-1.5 ${path.length === 0 ? "bg-white font-semibold text-ink shadow-sm" : "text-primary hover:bg-sage"}`}>Biblioteca</button>{path.map((node, index) => <span key={node.id} className="flex items-center"><ChevronRight size={13} className="text-muted-foreground" /><button onClick={() => onOpenPath(path.slice(0, index + 1))} className={`max-w-24 truncate rounded-md px-1.5 py-1.5 ${index === path.length - 1 ? "bg-white font-semibold text-ink shadow-sm" : "text-primary hover:bg-sage"}`}>{node.name}</button></span>)}</nav>;
}

function ConversationLibraryWorkspace({ company, onConnect, setError, setNotice }: { company: Company; onConnect: () => void; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [path, setPath] = useState<LibraryNode[]>([]);
  const [items, setItems] = useState<LibraryNode[]>([]);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<{ page: number; pages: number; total: number } | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [contexts, setContexts] = useState<LibraryContext[]>([]);
  const [syncs, setSyncs] = useState<LibrarySync[]>([]);
  const { request: requestLibrary } = useLatestRequest<LibraryPage>();
  const { request: requestSearch, cancel: cancelSearch } = useLatestRequest<{ items: LibraryNode[] }>();
  const { request: requestContexts } = useLatestRequest<{ items: LibraryContext[] }>();
  const { request: requestSyncs } = useLatestRequest<{ items: LibrarySync[] }>();
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchedQuery, setSearchedQuery] = useState("");
  const [contextLoading, setContextLoading] = useState(true);
  const [contextError, setContextError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const syncWasActive = useRef(false);
  const previousSyncStatuses = useRef(new Map<string, string>());
  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<LibraryNode[]>([]);
  const contextId = "";
  const [allTools, setAllTools] = useState(true);
  const [queryProviders, setQueryProviders] = useState<string[]>([]);
  const [mentions, setMentions] = useState<MentionCandidate[]>([]);
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [restoringConversation, setRestoringConversation] = useState(true);
  const [asking, setAsking] = useState(false);
  const conversationEpoch = useRef(0);
  const [filesPanelOpen, setFilesPanelOpen] = useState(true);
  const [managedFile, setManagedFile] = useState<LibraryNode | null>(null);
  const [managedDocument, setManagedDocument] = useState<LibraryDocumentRef | null>(null);
  const [managingFile, setManagingFile] = useState(false); const [managingFileAction, setManagingFileAction] = useState<"remove" | "reprocess" | null>(null);
  const current = path.at(-1);
  const canManage = company.role !== "member";
  const mentionsOutsideSelection = mentions.filter((item) => !allTools && !queryProviders.includes(providerKey(item.source_provider)));
  const canAsk = !restoringConversation && !contextLoading && !contextError && mentionsOutsideSelection.length === 0 && (allTools || queryProviders.length > 0) && contexts.some((item) => contextReady(item) && (allTools || queryProviders.includes(providerKey(item.source_provider))));

  const loadLibrary = useCallback(() => {
    setLibraryLoading(true); setLibraryError(null);
    const request = current ? `/library/nodes/${current.id}/children?organization_id=${company.id}&page=${page}` : `/library?organization_id=${company.id}`;
    void requestLibrary(request, (result) => {
      setItems(result.items);
      setPagination(typeof result.page === "number" && typeof result.pages === "number" && typeof result.total === "number" ? { page: result.page, pages: result.pages, total: result.total } : null);
    }, (caught) => setLibraryError(messageFor(caught)), () => setLibraryLoading(false));
  }, [company.id, current, page, requestLibrary]);
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
        setMessages(conversation.messages.map((message) => {
          const providers = message.context?.providers ?? [];
          const contextName = providers.length > 0 ? providers.map(toolLabel).join(", ") : "Todas as ferramentas";
          return message.role === "assistant"
            ? { id: message.id, role: "assistant", content: message.content, contextName, answer: message.response ? { ...message.response, citations: compactCitations(message.response.citations ?? []) } : undefined }
            : { id: message.id, role: "user", content: message.content, contextName, providers, mentions: message.context?.mentions, allTools: providers.length === 0 };
        }));
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
  function startNewConversation() {
    if (asking) return;
    conversationEpoch.current += 1;
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
  useEffect(() => { const transcript = transcriptRef.current; if (transcript) transcript.scrollTop = transcript.scrollHeight; }, [messages]);
  async function saveQuestion(message: ConversationMessage) {
    if (!message.contextId || saving) return;
    setSaving(true);
    try { await api<SavedQuery>(`/workspace-folders/${message.contextId}/saved-queries?organization_id=${company.id}`, { method: "POST", body: JSON.stringify({ name: message.content.slice(0, 160), query: message.content, filters: {} }) }); setNotice("Pergunta salva nesta pasta."); }
    catch (caught) { setError(messageFor(caught)); } finally { setSaving(false); }
  }
  function openItem(item: LibraryNode) {
    if (item.kind === "file") {
      if (item.source_url) window.open(item.source_url, "_blank", "noopener,noreferrer");
      return;
    }
    setPage(1);
    setPath((nodes) => [...nodes, item]);
  }
  function openPath(nodes: LibraryNode[]) { setPage(1); setPath(nodes); }
  function manageFile(item: LibraryNode) {
    const references = item.workspace_documents ?? [];
    const preferred = references.find((reference) => reference.workspace_folder_id === contextId) ?? references[0] ?? null;
    if (!preferred) { setError("Este arquivo não possui uma cópia indexada disponível para gerenciar."); return; }
    setManagedFile(item); setManagedDocument(preferred);
  }
  async function reprocessManagedFile() {
    if (!managedFile || !managedDocument) return;
    setManagingFile(true); setManagingFileAction("reprocess"); setError(null);
    try {
      await api<{ job_id: string; status: string }>(`/workspace-folders/${managedDocument.workspace_folder_id}/documents/${managedDocument.document_id}/reprocess?organization_id=${company.id}`, { method: "POST" });
      setManagedFile(null); setManagedDocument(null); loadOperations();
      setNotice(`Reprocessamento de “${managedFile.name}” agendado. O conteúdo será preparado novamente em segundo plano.`);
    } catch (caught) { setError(messageFor(caught)); } finally { setManagingFile(false); setManagingFileAction(null); }
  }
  async function removeManagedFile() {
    if (!managedFile || !managedDocument) return;
    if (!window.confirm(`Remover “${managedFile.name}” somente desta base de conhecimento? O arquivo original continuará no Google Drive. Uma nova sincronização deste escopo poderá indexá-lo novamente.`)) return;
    setManagingFile(true); setManagingFileAction("remove"); setError(null);
    try {
      await api<void>(`/workspace-folders/${managedDocument.workspace_folder_id}/documents/${managedDocument.document_id}?organization_id=${company.id}`, { method: "DELETE" });
      setManagedFile(null); setManagedDocument(null); await Promise.all([Promise.resolve(loadLibrary()), Promise.resolve(loadOperations())]);
      setNotice(`“${managedFile.name}” foi removido apenas do índice local.`);
    } catch (caught) { setError(messageFor(caught)); } finally { setManagingFile(false); setManagingFileAction(null); }
  }
  async function searchLibrary(event: FormEvent) {
    event.preventDefault();
    const submitted = query.trim();
    if (!submitted) { cancelSearch(); setSearching(false); setResults([]); setSearchedQuery(""); return; }
    setSearching(true); setSearchedQuery(""); setResults([]);
    await requestSearch(`/library/search?organization_id=${company.id}&query=${encodeURIComponent(submitted)}`, (found) => { setResults(found.items); setSearchedQuery(submitted); }, (caught) => setError(messageFor(caught)), () => setSearching(false));
  }
  async function ask(event: FormEvent) {
    event.preventDefault();
    const submittedQuestion = question.trim();
    if (asking || !canAsk || !submittedQuestion) return;
    const requestId = crypto.randomUUID();
    const requestEpoch = conversationEpoch.current;
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
      setMessages((items) => items.map((item) => item.id === pendingId ? { ...item, pending: false, answer } : item));
    } catch (caught) {
      if (conversationEpoch.current !== requestEpoch) return;
      const error = messageFor(caught);
      setMessages((items) => items.map((item) => item.id === pendingId ? { ...item, pending: false, error } : item));
      setError(error);
    }
    finally { setAsking(false); }
  }
  const managedReferences = managedFile?.workspace_documents ?? [];
  const managedContext = managedDocument ? contexts.find((item) => item.id === managedDocument.workspace_folder_id) : null;
  return <><div className="workspace-frame chat-workspace overflow-hidden border border-line bg-white">
    <div className={`grid workspace-panels${filesPanelOpen ? "" : " files-panel-collapsed"}`}>
      <aside id="library-sources" className="sources-panel border-b border-line bg-sage xl:border-b-0 xl:border-r">
        <LibrarySidebarHeader canManage={canManage} onConnect={onConnect} onRefresh={loadLibrary} /><LibraryBreadcrumbs path={path} onOpenPath={openPath} />
        <div className="max-h-72 overflow-y-auto px-2 pb-4 xl:max-h-[calc(100vh-20rem)]">{libraryLoading ? <LoadingIndicator label="Abrindo biblioteca…" className="px-2 py-5 text-sm text-muted-foreground" /> : libraryError ? <div role="alert" className="px-3 py-5 text-sm text-rose-700">{libraryError}<button onClick={loadLibrary} className="mt-2 block font-semibold underline">Tentar novamente</button></div> : items.length === 0 ? <div className="px-2 py-5 text-sm text-muted-foreground"><HardDrive size={18} className="mb-2 text-primary" />{current ? "Esta pasta ainda não possui itens." : "Nenhuma fonte sincronizada."}</div> : items.map((item) => <div key={item.id} className="group flex items-center rounded-md hover:bg-white"><button onClick={() => openItem(item)} className="flex min-w-0 flex-1 items-center gap-2 px-2.5 py-2 text-left text-sm"><span className={`grid size-7 shrink-0 place-items-center rounded-lg ${item.kind === "file" ? "bg-sage-selected text-muted-foreground" : "bg-sage-selected text-primary"}`}><LibraryNodeIcon item={item} size={14} /></span><span className="min-w-0 flex-1 truncate font-medium text-ink">{item.name}</span>{item.kind !== "file" && <ChevronRight size={14} className="text-muted-foreground" />}</button>{canManage && item.kind === "file" && (item.workspace_documents?.length ?? 0) > 0 && <button onClick={() => manageFile(item)} className="mr-1 rounded-lg p-2 text-muted-foreground hover:bg-sage hover:text-ink" aria-label={`Gerenciar ${item.name}`} title="Gerenciar arquivo"><Settings2 size={15} /></button>}</div>)}</div>
        {pagination && pagination.pages > 1 && <Pagination value={pagination} loading={libraryLoading} onChange={setPage} />}
        <p className="sources-scope flex gap-2 px-4 py-5 text-xs leading-5 text-muted-foreground"><ShieldCheck size={16} className="shrink-0 text-primary" />A conversa usa somente as ferramentas e menções selecionadas na mensagem.</p>
      </aside>
      <main id="consultas" className="conversation-panel relative flex min-h-[560px] min-w-0 flex-col bg-white">
        <div className="flex shrink-0 items-center justify-end gap-1 border-b border-line-soft bg-white px-3 py-1.5 sm:px-5"><button type="button" onClick={startNewConversation} disabled={asking} className="inline-flex min-h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-xs font-medium text-ink hover:bg-sage disabled:opacity-40"><Plus size={15} aria-hidden="true" />Nova conversa</button><button type="button" onClick={() => setFilesPanelOpen((open) => !open)} aria-controls="chat-library" aria-expanded={filesPanelOpen} aria-label={filesPanelOpen ? "Ocultar consulta de arquivos" : "Mostrar consulta de arquivos"} title={filesPanelOpen ? "Ocultar consulta de arquivos" : "Mostrar consulta de arquivos"} className="rounded-lg p-2 text-muted-foreground hover:bg-sage hover:text-ink">{filesPanelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}</button></div>
        <div ref={transcriptRef} role="log" aria-label="Conversa com seus documentos" aria-live="polite" className="flex-1 overflow-y-auto px-5 py-6 sm:px-7">{messages.length > 0 ? <div className="mx-auto max-w-3xl space-y-5">{messages.map((message) => message.role === "user" ? <div key={message.id} className="ml-auto max-w-[85%]"><p className="mb-1 text-right text-xs font-medium text-muted-foreground">{message.contextName}</p><div className="conversation-question px-4 py-3 text-sm leading-6">{message.content}{Boolean(message.mentions?.length) && <span className="mt-2 block text-xs">{mentionSummary(message.mentions ?? [])}</span>}</div>{message.contextId && <button disabled={saving} onClick={() => { void saveQuestion(message); }} className="mt-1.5 block ml-auto text-xs text-muted-foreground underline-offset-4 hover:underline disabled:opacity-40">Salvar pergunta</button>}</div> : <article key={message.id} className="conversation-answer"><div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-sage-selected text-primary"><Sparkles size={15} /></span><div><p className="text-sm font-semibold text-ink">Arquivio</p><p className="text-xs text-muted-foreground">{message.contextName}</p></div></div>{message.pending ? <div className="mt-4 rounded-md bg-paper px-3 py-2.5"><LoadingIndicator label="A IA está analisando as evidências e preparando a resposta…" className="text-sm text-muted-foreground" /></div> : message.error ? <div className="mt-4 text-sm leading-6 text-rose-700"><p>Não foi possível concluir esta pergunta: {message.error}</p><button type="button" className="mt-2 min-h-11 underline" onClick={() => { setQuestion(message.content); setMentions(message.mentions ?? []); setAllTools(message.allTools ?? true); setQueryProviders(message.providers ?? []); composerRef.current?.focus(); }}>Repetir com este contexto</button></div> : message.answer ? <><AssistantAnswer messageId={message.id} answer={message.answer} /></> : null}</article>)}</div> : <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center py-16 text-center"><span className="grid size-12 place-items-center rounded-lg bg-sage text-primary"><Sparkles size={22} /></span><h2 className="mt-4 text-lg font-semibold text-ink">O que você quer descobrir?</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Pergunte sobre conteúdo indexado. Se quiser restringir a pergunta, escolha ferramentas abaixo ou mencione arquivos e pastas com @ ou /.</p>{canAsk && <div className="mt-6 flex flex-wrap justify-center gap-2">{["Quais são os principais prazos?", "O que foi definido sobre as entregas?", "Quais são as responsabilidades da equipe?"].map((prompt) => <button key={prompt} onClick={() => { setQuestion(prompt); setMentions([]); composerRef.current?.focus(); }} className="rounded-md border border-line px-3 py-2 text-xs text-muted-foreground hover:border-primary hover:bg-sage">{prompt}</button>)}</div>}</div>}</div>
        <form onSubmit={(event) => { void ask(event); }} className="conversation-composer shrink-0 bg-white p-4 sm:px-7 sm:py-5">
          <div className="rounded-lg border border-line bg-white p-2 shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-sage-selected">
            <MentionComposer organizationId={company.id} value={question} onChange={setQuestion} mentions={mentions} onMentionsChange={setMentions} all={allTools} providers={queryProviders} disabled={asking || restoringConversation} textareaRef={composerRef} onSubmit={() => composerRef.current?.form?.requestSubmit()} />
            <div className="composer-toolbar flex items-center justify-between gap-2 border-t border-line-soft px-2 pt-2">
              <QuestionScopePicker all={allTools} providers={queryProviders} contexts={contexts} loading={contextLoading} disabled={asking} error={contextError} onRetry={loadOperations} onChange={(all, providers) => { setAllTools(all); setQueryProviders(providers); }} />
              <div className="flex shrink-0 items-center gap-2"><span className="text-xs text-muted-foreground">{question.length}/1000</span><button disabled={!canAsk || !question.trim() || asking} className="inline-flex min-h-11 items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-forest-hover disabled:cursor-not-allowed disabled:opacity-40">{asking ? <RefreshCw size={15} className="motion-safe:animate-spin" aria-hidden="true" /> : <Send size={15} />}{asking ? "Consultando…" : "Enviar"}</button></div>
            </div>
          </div>
          {mentionsOutsideSelection.length > 0 && <p role="alert" className="mt-2 text-xs text-amber-800">Marque {mentionsOutsideSelection.map((item) => toolLabel(item.source_provider)).join(", ")} ou remova a menção antes de enviar.</p>}
          <p className="mt-2 text-xs text-muted-foreground">Somente conteúdo já indexado. @ menciona arquivos e pastas; / abre comandos. Menções restringem a seleção de ferramentas.</p>
        </form>
      </main>
      <aside id="chat-library" hidden={!filesPanelOpen} className="context-panel border-t border-line bg-white xl:border-l xl:border-t-0">
        <section className="p-4"><p className="text-sm font-semibold text-ink">Buscar arquivos</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Encontre arquivos e pastas pelo nome em todas as fontes conectadas.</p><form onSubmit={(event) => { void searchLibrary(event); }} className="mt-3 flex gap-2"><input aria-label="Buscar nome de arquivo ou pasta" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} placeholder="Nome de arquivo ou pasta" className="min-w-0 flex-1 rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-primary" /><button className="rounded-md border border-line bg-white px-3 text-muted-foreground hover:bg-sage" aria-label="Buscar arquivos"><Search size={16} /></button></form>{!searching && searchedQuery && results.length === 0 && <p className="mt-3 text-xs text-muted-foreground">Nenhum nome encontrado.</p>}{searching && <LoadingIndicator label="Buscando…" className="mt-3 text-xs text-muted-foreground" />}{searchedQuery && <p className="mt-2 text-xs text-muted-foreground">Resultados para “{searchedQuery}”</p>}{results.length > 0 && <div className="mt-3 max-h-40 space-y-1 overflow-auto">{results.map((item) => <button key={item.id} onClick={() => { if (item.kind === "file") openItem(item); else openPath([item]); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-white"><span className="text-primary"><LibraryNodeIcon item={item} size={14} /></span><span className="min-w-0 flex-1 truncate">{item.name}</span></button>)}</div>}<p className="mt-2 text-xs leading-5 text-muted-foreground">A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.</p></section>
      </aside>
    </div>
  </div>{managedFile && managedDocument && <div className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4" role="dialog" aria-modal="true" aria-labelledby="manage-file-title"><section className="w-full max-w-md rounded-lg bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-primary">Índice local</p><h2 id="manage-file-title" className="mt-1 text-xl font-semibold text-ink">Gerenciar arquivo</h2></div><button disabled={managingFile} onClick={() => { setManagedFile(null); setManagedDocument(null); }} className="rounded-lg p-2 text-muted-foreground hover:bg-sage" aria-label="Fechar"><X size={18} /></button></div><div className="mt-5 rounded-md bg-paper p-4"><p className="font-medium text-ink">{managedFile.name}</p><p className="mt-1 text-sm leading-6 text-muted-foreground">As ações abaixo afetam somente a cópia indexada. O original não será apagado do Google Drive.</p></div>{managedReferences.length > 1 && <label className="mt-5 block text-sm font-medium text-ink">Espaço de conhecimento<select value={managedDocument.document_id} disabled={managingFile} onChange={(event) => setManagedDocument(managedReferences.find((item) => item.document_id === event.target.value) ?? null)} className="mt-2 w-full rounded-md border border-line bg-white px-3 py-2.5 text-sm"><option value="">Selecione um espaço</option>{managedReferences.map((reference) => <option key={reference.document_id} value={reference.document_id}>{contexts.find((item) => item.id === reference.workspace_folder_id)?.name ?? "Espaço sincronizado"}</option>)}</select></label>}<p className="mt-4 text-xs text-muted-foreground">{managedContext ? `Espaço selecionado: ${managedContext.name}` : "Espaço selecionado para esta cópia."}</p><div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><button disabled={managingFile} aria-busy={managingFile} onClick={() => { void removeManagedFile(); }} className="inline-flex items-center justify-center gap-2 rounded-md border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">{managingFileAction === "remove" ? <RefreshCw size={16} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={16} />}{managingFileAction === "remove" ? "Removendo…" : "Remover do índice"}</button><button disabled={managingFile} aria-busy={managingFile} onClick={() => { void reprocessManagedFile(); }} className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-forest-hover disabled:opacity-50"><RefreshCw size={16} className={managingFileAction === "reprocess" ? "motion-safe:animate-spin" : ""} aria-hidden="true" />{managingFileAction === "reprocess" ? "Reprocessando…" : "Reprocessar"}</button></div></section></div>}</>;
}

function AssistantAnswer({ messageId, answer }: { messageId: string; answer: Answer }) {
  const [expanded, setExpanded] = useState(false);
  const sourceId = (number: number) => `source-${messageId}-${number}`;
  const openSource = (number: number) => {
    setExpanded((open) => open || number > 3);
    // Wait for the expanded list to render before moving focus to the cited row.
    window.requestAnimationFrame(() => {
      const row = document.getElementById(sourceId(number));
      if (!row) return;
      row.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
      row.focus({ preventScroll: true });
    });
  };
  return <>
    <AnswerMarkdown text={answerText(answer)} fileNames={answer.citations.map((citation) => citation.document_name)} onCite={answer.citations.length > 0 ? openSource : undefined} />
    {Boolean(answer.coverage?.pending_folders) && <p className="mt-2 text-xs text-amber-800">Cobertura parcial: {answer.coverage?.eligible_folders} de {answer.coverage?.total_folders} pastas disponíveis nesta consulta.</p>}
    {answer.citations.length > 0 && <SourceDocuments items={answer.citations} expanded={expanded} setExpanded={setExpanded} rowId={sourceId} />}
  </>;
}

function SourceDocumentRow({ item, number, id }: { item: Evidence; number: number; id: string }) {
  return <li id={id} tabIndex={-1} className="source-row flex min-w-0 items-center gap-2 border-t border-line-soft py-2.5 first:border-t-0">
    <span className="w-5 shrink-0 text-right text-xs font-semibold text-primary">{number}.</span>
    <FileText size={15} className="shrink-0 text-primary" aria-hidden="true" />
    <span className="min-w-0 flex-1 break-words text-xs font-medium leading-5 text-ink">{item.document_name}</span>
    {item.source_provider && <span className="citation-tool mb-0 shrink-0">{toolLabel(item.source_provider)}</span>}
    {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer" aria-label={`Abrir ${item.document_name} no original`} title="Abrir original" className="shrink-0 rounded-md p-1.5 text-primary hover:bg-sage focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"><ExternalLink size={14} aria-hidden="true" /></a>}
  </li>;
}

function SourceDocuments({ items, expanded, setExpanded, rowId }: { items: Evidence[]; expanded: boolean; setExpanded: (update: (open: boolean) => boolean) => void; rowId: (number: number) => string }) {
  const remainingCount = Math.max(items.length - 3, 0);
  return <section className="mt-5 border-t border-line pt-4" aria-label="Documentos utilizados como fonte">
    <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Fontes</h3>
    <ol>{items.slice(0, expanded ? undefined : 3).map((item, index) => <SourceDocumentRow key={citationSourceKey(item)} item={item} number={index + 1} id={rowId(index + 1)} />)}</ol>
    {remainingCount > 0 && <button type="button" onClick={() => setExpanded((open) => !open)} aria-expanded={expanded} className="flex items-center gap-1 border-t border-line-soft py-2 text-xs font-semibold text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
      {expanded ? "Mostrar menos" : `Ver mais ${remainingCount} ${remainingCount === 1 ? "documento" : "documentos"}`}
      <ChevronRight size={14} className={`transition-transform ${expanded ? "-rotate-90" : "rotate-90"}`} aria-hidden="true" />
    </button>}
  </section>;
}

function TeamScreen({ company, setError, setNotice }: { company: Company; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [members, setMembers] = useState<Member[]>([]); const [email, setEmail] = useState(""); const [role, setRole] = useState<"admin" | "member">("member"); const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true); const [loadError, setLoadError] = useState<string | null>(null); const [updatingMemberId, setUpdatingMemberId] = useState<string | null>(null);
  const load = useCallback(() => { if (company.role !== "owner") return; setLoading(true); setLoadError(null); void api<Member[]>(`/organizations/${company.id}/members`).then(setMembers).catch((caught) => setLoadError(messageFor(caught))).finally(() => setLoading(false)); }, [company.id, company.role]);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  if (company.role !== "owner") return <Restricted title="Apenas o responsável gerencia a equipe" description="Administradores e membros podem usar pastas compartilhadas, mas não veem nem alteram membros ou convites." />;
  async function invite(event: FormEvent) { event.preventDefault(); setBusy(true); try { await api<{ status: string }>(`/organizations/${company.id}/members/invitations`, { method: "POST", body: JSON.stringify({ email, role }) }); setEmail(""); setNotice("Convite enviado."); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); } }
  async function change(member: Member, next: "admin" | "member") { setUpdatingMemberId(member.id); try { const updated = await api<Member>(`/organizations/${company.id}/members/${member.id}`, { method: "PATCH", body: JSON.stringify({ role: next }) }); setMembers((items) => items.map((item) => item.id === member.id ? updated : item)); setNotice(`Acesso de ${member.email} atualizado.`); } catch (caught) { setError(messageFor(caught)); } finally { setUpdatingMemberId(null); } }
  async function remove(member: Member) { if (!window.confirm(`Remover ${member.email} da organização?`)) return; setUpdatingMemberId(member.id); try { await api<void>(`/organizations/${company.id}/members/${member.id}`, { method: "DELETE" }); setMembers((items) => items.filter((item) => item.id !== member.id)); setNotice(`${member.email} foi removido da organização.`); } catch (caught) { setError(messageFor(caught)); } finally { setUpdatingMemberId(null); } }
  return <div className="grid gap-5 lg:grid-cols-[1fr_330px]"><section className="rounded-lg border border-line-soft bg-white p-6" aria-busy={loading}><p className="text-sm font-semibold text-primary">Acesso da organização</p><h1 className="mt-1 text-2xl font-semibold">Equipe</h1><div className="mt-5 space-y-3">{loading ? <LoadingIndicator label="Carregando equipe…" className="state-panel text-sm text-muted-foreground" /> : loadError ? <div role="alert" className="state-panel state-panel-error"><CircleAlert size={22} /><p>{loadError}</p><button onClick={load} className="font-semibold underline">Tentar novamente</button></div> : members.length === 0 ? <div className="state-panel"><Users size={24} /><p>Nenhuma pessoa encontrada nesta organização.</p></div> : members.map((member) => <div key={member.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-line-soft bg-paper/40 p-4"><div className="min-w-0"><b className="block truncate text-sm">{member.email}</b><p className="mt-1 text-xs text-muted-foreground">{roleLabel(member.role)}</p></div>{member.role !== "owner" && <div className="flex items-center gap-2"><label className="sr-only" htmlFor={`member-role-${member.id}`}>Papel de {member.email}</label><select id={`member-role-${member.id}`} value={member.role} disabled={updatingMemberId === member.id} onChange={(event) => { void change(member, event.target.value as "admin" | "member"); }} className="rounded-lg border border-line bg-white px-2 py-1.5 text-sm"><option value="admin">Administrador</option><option value="member">Membro</option></select><button disabled={updatingMemberId === member.id} onClick={() => { void remove(member); }} className="rounded-lg p-2 text-rose-600 hover:bg-rose-50 disabled:opacity-50" aria-label={`Remover ${member.email}`}>{updatingMemberId === member.id ? <RefreshCw size={16} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={16} />}</button></div>}</div>)}</div></section><form onSubmit={invite} className="h-fit rounded-lg border border-line-soft bg-white p-6"><h2 className="font-semibold">Convidar pessoa</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Responsáveis controlam o acesso. Administradores organizam fontes; membros pesquisam e perguntam.</p><label htmlFor="invite-email" className="mt-5 block text-sm font-medium">E-mail</label><input id="invite-email" required value={email} onChange={(event) => setEmail(event.target.value)} type="email" autoComplete="email" placeholder="pessoa@empresa.com" className="mt-2 w-full rounded-md border border-line px-3 py-2.5" /><label htmlFor="invite-role" className="mt-4 block text-sm font-medium">Papel</label><select id="invite-role" value={role} onChange={(event) => setRole(event.target.value as "admin" | "member")} className="mt-2 w-full rounded-md border border-line px-3 py-2.5"><option value="member">Membro</option><option value="admin">Administrador</option></select><button disabled={busy} aria-busy={busy} className="mt-4 w-full rounded-md bg-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Enviando…" : "Enviar convite"}</button></form></div>;
}
function Restricted({ title, description }: { title: string; description: string }) { return <section className="max-w-xl rounded-lg border border-line-soft bg-white p-7"><ShieldCheck className="text-ink" /><h1 className="mt-4 text-2xl font-semibold">{title}</h1><p className="mt-3 leading-6 text-muted-foreground">{description}</p></section>; }

async function requireSyncHistoryEntry(companyId: string, entryId: string | undefined, label: "sincronização" | "ressincronização") {
  if (!entryId) throw new Error(`O serviço não confirmou o registro da ${label}. Atualize a Biblioteca para conferir antes de tentar novamente.`);
  const history = await api<{ items: ManualSync[] }>(`/library/sync-history?organization_id=${companyId}`, { cache: "no-store" });
  if (!history.items.some((run) => run.id === entryId)) throw new Error(`A ${label} foi solicitada, mas seu registro não apareceu no histórico. Atualize a Biblioteca para conferir antes de tentar novamente.`);
}

function IntegrationScreen({ company, setError, setNotice }: { company: Company; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [sources, setSources] = useState<Source[]>([]); const [sourcesLoading, setSourcesLoading] = useState(true); const [sourcesError, setSourcesError] = useState<string | null>(null); const [source, setSource] = useState<Source | null>(null); const [catalog, setCatalog] = useState<ScopeCatalog | null>(null); const [catalogError, setCatalogError] = useState<string | null>(null); const [workspaceFolders, setWorkspaceFolders] = useState<Folder[]>([]); const [foldersLoading, setFoldersLoading] = useState(true); const [selectedIds, setSelectedIds] = useState<string[]>([]); const [includeRoot, setIncludeRoot] = useState(false); const [mode, setMode] = useState<"selected" | "all_accessible">("selected"); const [uniform, setUniform] = useState(false); const [busy, setBusy] = useState(false); const [toolModalOpen, setToolModalOpen] = useState(false); const [disconnectingSourceId, setDisconnectingSourceId] = useState<string | null>(null);
  const canManage = company.role !== "member";
  const toolName = providerLabel(source?.provider);
  const hasSelectedScope = mode === "all_accessible" || selectedIds.length > 0 || includeRoot;
  const loadSources = useCallback(() => { if (!canManage) return; setSourcesLoading(true); setSourcesError(null); void api<Source[]>(`/data-sources?organization_id=${company.id}`).then((items) => setSources(latestSourcePerProvider(items))).catch((caught) => setSourcesError(messageFor(caught))).finally(() => setSourcesLoading(false)); }, [canManage, company.id]);
  const loadWorkspaceFolders = useCallback(() => { if (!canManage) return; setFoldersLoading(true); void api<Folder[]>(`/workspace-folders?organization_id=${company.id}`).then(setWorkspaceFolders).catch((caught) => setError(messageFor(caught))).finally(() => setFoldersLoading(false)); }, [canManage, company.id, setError]);
  useEffect(() => { void Promise.resolve().then(loadSources); }, [loadSources]);
  useEffect(() => { void Promise.resolve().then(loadWorkspaceFolders); }, [loadWorkspaceFolders]);
  useEffect(() => {
    if (!workspaceFolders.some((folder) => folder.status === "queued" || folder.status === "syncing")) return;
    const timer = window.setInterval(loadWorkspaceFolders, 5000);
    return () => window.clearInterval(timer);
  }, [workspaceFolders, loadWorkspaceFolders]);
  useEffect(() => { if (new URLSearchParams(window.location.search).get("connected") === "google_drive") void Promise.resolve().then(() => setToolModalOpen(true)); }, []);
  function connect(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/google/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  function connectNotion(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/notion/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  function connectSharePoint(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/sharepoint/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  function connectOneDrive(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/onedrive/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  const loadCatalog = useCallback(async (selected: Source) => { if (selected.status === "reauth_required") return; const selectedName = providerLabel(selected.provider); setSource(selected); setCatalog(null); setCatalogError(null); setSelectedIds([]); setIncludeRoot(false); setMode("selected"); setUniform(false); setToolModalOpen(true); try { setCatalog(await api<ScopeCatalog>(`/data-sources/${selected.id}/scope-catalog?organization_id=${company.id}`)); loadWorkspaceFolders(); } catch (caught) { setCatalogError(messageFor(caught)); if (caught instanceof ApiError && (caught.status === 409 || caught.status === 403)) { setSources((items) => items.map((item) => item.id === selected.id ? { ...item, status: "reauth_required" } : item)); setSource({ ...selected, status: "reauth_required" }); setError(`${selectedName} precisa ser reconectado para consultar as pastas disponíveis.`); } else setError(messageFor(caught)); } }, [company.id, loadWorkspaceFolders, setError]);
  useEffect(() => {
    const connectedProvider = new URLSearchParams(window.location.search).get("connected");
    if (connectedProvider !== "notion" && connectedProvider !== "onedrive" && connectedProvider !== "sharepoint") return;
    void Promise.resolve().then(() => {
      setSourcesLoading(true);
      return api<Source[]>(`/data-sources?organization_id=${company.id}`).then((items) => {
        setSources(latestSourcePerProvider(items));
        const connectedSource = items.find((item) => item.provider === connectedProvider && item.status === "connected");
        if (connectedSource) void loadCatalog(connectedSource);
      }).catch((caught) => setError(messageFor(caught))).finally(() => setSourcesLoading(false));
    });
  }, [company.id, loadCatalog, setError]);
  if (!canManage) return <Restricted title="Responsáveis e administradores conectam fontes" description="Membros podem consultar espaços já compartilhados, mas não conectam Drive nem iniciam sincronizações." />;
  function toggleFolder(id: string) { setMode("selected"); setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]); }
  async function selectAndSync() { if (!source || !uniform || !hasSelectedScope) return; setBusy(true); try { const folder = await api<{ id: string }>(`/workspace-folders/selections?organization_id=${company.id}`, { method: "POST", body: JSON.stringify({ source_id: source.id, mode, folder_ids: mode === "selected" ? selectedIds : [], include_root_files: mode === "selected" && includeRoot, uniform_access_confirmed: true }) }); if (syncedForSource.some((space) => space.id === folder.id)) { if (!window.confirm(`${FULL_RESYNC_CONFIRM} Este espaço já está sincronizado.`)) return; const full = await api<{ run_id: string; job_id: string }>(`/library/workspaces/${folder.id}/reprocess?organization_id=${company.id}&reprocess_all=true`, { method: "POST" }); await Promise.resolve(loadWorkspaceFolders()); await requireSyncHistoryEntry(company.id, full.run_id, "ressincronização"); setNotice("Ressincronização completa iniciada: todos os arquivos serão relidos e reconstruídos. Acompanhe em Sincronizações na Biblioteca."); return; } const result = await api<{ job_id: string; status: string }>(`/workspace-folders/${folder.id}/sync?organization_id=${company.id}`, { method: "POST" }); await Promise.resolve(loadWorkspaceFolders()); await requireSyncHistoryEntry(company.id, result.job_id, "sincronização"); setNotice("Sincronização iniciada. O conteúdo será indexado somente dentro deste espaço de conhecimento. Acompanhe o progresso em Sincronizações na Biblioteca."); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); } }
  async function resyncFolder(folder: Folder) { if (!window.confirm(`${FULL_RESYNC_CONFIRM} Espaço: “${folder.name}”.`)) return; setBusy(true); setError(null); try { const result = await api<{ run_id: string; job_id: string; status: string }>(`/library/workspaces/${folder.id}/reprocess?organization_id=${company.id}&reprocess_all=true`, { method: "POST" }); if (!result.job_id) throw new Error("Nenhum trabalho de ressincronização foi confirmado."); await requireSyncHistoryEntry(company.id, result.run_id, "ressincronização"); setNotice(`Ressincronização completa de “${folder.name}” iniciada. Acompanhe o histórico em Sincronizações na Biblioteca.`); loadWorkspaceFolders(); } catch (caught) { setCatalogError(messageFor(caught)); setError(messageFor(caught)); } finally { setBusy(false); } }
  async function disconnect(selected: Source) { const selectedName = providerLabel(selected.provider); if (!window.confirm(`Desconectar ${selectedName}? Os espaços já indexados continuarão disponíveis, mas novas sincronizações serão bloqueadas.`)) return; setDisconnectingSourceId(selected.id); try { await api<void>(`/data-sources/${selected.id}?organization_id=${company.id}`, { method: "DELETE" }); setSource(null); setCatalog(null); setToolModalOpen(false); await Promise.resolve(loadSources()); setNotice(`${selectedName} desconectado. Você pode autorizar novamente quando quiser.`); } catch (caught) { setError(messageFor(caught)); } finally { setDisconnectingSourceId(null); } }
  const syncedForSource = workspaceFolders.filter((folder) => folder.source_id === source?.id);
  const { folders: availableFolders, allAccessibleTaken } = newSpaceOptions(catalog?.folders ?? [], syncedForSource);
  const closeTool = () => { setToolModalOpen(false); setSource(null); setCatalog(null); setCatalogError(null); };
  return <><IntegrationCatalog sources={sources} sourcesLoading={sourcesLoading} sourcesError={sourcesError} onRetry={loadSources} modalOpen={toolModalOpen && !source} onOpen={() => setToolModalOpen(true)} onClose={() => setToolModalOpen(false)} onConnect={connect} onConnectNotion={connectNotion} onConnectOneDrive={connectOneDrive} onConnectSharePoint={connectSharePoint} onManage={(selected) => { void loadCatalog(selected); }} onDisconnect={disconnect} disconnectingSourceId={disconnectingSourceId} />
    {source && toolModalOpen && <div role="dialog" aria-modal="true" aria-labelledby="sync-tool-title" className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4"><section className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg bg-white p-6 shadow-2xl"><div className="flex items-start gap-4"><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-primary">Integração ativa</p><h2 id="sync-tool-title" className="mt-1 text-2xl font-semibold text-ink">{toolName}</h2><p className="mt-1 text-sm text-muted-foreground">Confira a conexão, veja o que já está sincronizado e adicione novos espaços.</p></div><button onClick={closeTool} aria-label="Fechar" className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><X size={18} /></button></div>
      <div className={`mt-5 rounded-lg border p-4 ${source.status === "connected" ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Estado da conexão</p><p className="mt-1 font-semibold text-ink">{source.status === "connected" ? "Conexão ativa" : "Reconexão necessária"}</p>{source.account_email && <p className="mt-1 text-sm text-muted-foreground">{source.account_email}</p>}</div>{source.status !== "connected" && <button onClick={() => (source.provider === "notion" ? connectNotion : source.provider === "onedrive" ? connectOneDrive : source.provider === "sharepoint" ? connectSharePoint : connect)(source.id)} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white">Reconectar {providerLabel(source.provider)}</button>}</div></div>
      {catalog && <><section className="mt-6"><div className="flex items-end justify-between gap-3"><div><h3 className="font-semibold text-ink">Já sincronizado</h3><p className="mt-1 text-sm text-muted-foreground">Esses espaços já fazem parte da base. “Re-sync” faz uma ressincronização completa: relê todos os arquivos e reconstrói trechos, embeddings e OCR. Para só buscar o que mudou, use o ícone de sincronizar na Biblioteca.</p></div><span className="rounded-full bg-sage px-2.5 py-1 text-xs font-semibold text-muted-foreground">{syncedForSource.length} {syncedForSource.length === 1 ? "espaço" : "espaços"}</span></div>{foldersLoading && workspaceFolders.length === 0 ? <LoadingIndicator label="Carregando espaços sincronizados…" className="mt-3 rounded-md border border-dashed border-line p-4 text-sm text-muted-foreground" /> : syncedForSource.length === 0 ? <p className="mt-3 rounded-md border border-dashed border-line p-4 text-sm text-muted-foreground">Nenhuma pasta foi sincronizada ainda.</p> : <div className="mt-3 space-y-2">{syncedForSource.map((folder) => <div key={folder.id} className="flex flex-wrap items-center gap-3 rounded-md border border-emerald-200 bg-emerald-50/50 p-3"><span className="grid size-8 place-items-center rounded-md bg-white text-emerald-700"><FolderOpen size={16} /></span><div className="min-w-0 flex-1"><b className="block truncate text-sm text-ink">{folder.name}</b><p className="mt-0.5 text-xs text-muted-foreground">{folder.last_synced_at ? `Última sincronização: ${new Date(folder.last_synced_at).toLocaleString("pt-BR")}` : "Ainda não sincronizado"} · {(folder.status === "queued" || folder.status === "syncing") && <RefreshCw size={11} className="inline motion-safe:animate-spin" aria-hidden="true" />} {statusLabel(folder.status)}</p></div><button disabled={busy} onClick={() => { void resyncFolder(folder); }} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-2 text-xs font-semibold text-ink disabled:opacity-50"><RefreshCw size={14} />Re-sync</button></div>)}</div>}</section>
      <section className="mt-7 border-t border-line pt-5"><h3 className="font-semibold text-ink">Sincronizar novo espaço</h3><p className="mt-1 text-sm text-muted-foreground">Selecione uma ou mais pastas ou escolha todo o conteúdo acessível. Pastas novas fazem uma primeira sincronização; espaços já sincronizados são ressincronizados por completo.</p>{availableFolders.length === 0 && mode === "selected" ? <p className="mt-3 rounded-md border border-dashed border-line p-4 text-sm text-muted-foreground">Todas as pastas disponíveis já estão sincronizadas.</p> : <div className="mt-3 grid gap-2 sm:grid-cols-2">{availableFolders.map((item) => item.selectable === false ? <p key={item.id} className="col-span-full mt-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{item.name}</p> : <label key={item.id} className={`cursor-pointer rounded-md border border-line p-3 text-left ${mode === "selected" && selectedIds.includes(item.id) ? "border-primary bg-sage" : ""}`}><input type="checkbox" checked={mode === "selected" && selectedIds.includes(item.id)} onChange={() => toggleFolder(item.id)} className="mr-2" /><FolderOpen size={16} className="mr-2 inline text-primary" />{item.name}{item.existingSpace && <span className="mt-1 block text-xs text-amber-900">Já sincronizada. Selecionar faz uma ressincronização completa.</span>}{item.coveredBy && <span className="mt-1 block text-xs text-amber-900">Já incluída no espaço “{item.coveredBy}”. Sincronizar aqui indexa os mesmos arquivos de novo.</span>}</label>)}</div>}{catalog.root_files.available && <label className={`mt-3 flex cursor-pointer gap-3 rounded-md border border-line p-3 text-sm ${mode === "selected" && includeRoot ? "border-primary bg-sage" : ""}`}><input type="checkbox" checked={mode === "selected" && includeRoot} onChange={(event) => { setMode("selected"); setIncludeRoot(event.target.checked); }} className="mt-1" /><span><b>{catalog.root_files.label}</b><span className="mt-1 block text-muted-foreground">Inclui arquivos soltos na raiz.</span></span></label>}{catalog.all_accessible.available && <label className={`mt-3 flex cursor-pointer gap-3 rounded-md border border-amber-200 p-3 text-sm ${mode === "all_accessible" ? "bg-amber-50" : ""}`}><input type="radio" name="integration-scope" checked={mode === "all_accessible"} onChange={() => { setMode("all_accessible"); setSelectedIds([]); setIncludeRoot(false); }} className="mt-1" /><span><b>{catalog.all_accessible.label}</b><span className="mt-1 block text-amber-900">Inclui tudo que esta conexão permite ler.{allAccessibleTaken && " Já sincronizado: selecionar faz uma ressincronização completa."}</span></span></label>}{hasSelectedScope && <label className="mt-4 flex gap-3 rounded-md bg-amber-50 p-3 text-sm leading-6 text-amber-950"><input type="checkbox" checked={uniform} onChange={(event) => setUniform(event.target.checked)} className="mt-1" />{source.provider === "sharepoint" ? "Todos os membros da organização poderão consultar o conteúdo desta biblioteca, mesmo que no SharePoint ele tenha permissões diferentes." : "Confirmo que todos os membros desta organização podem consultar este conteúdo."}</label>}{hasSelectedScope && ((mode === "all_accessible" && allAccessibleTaken) || (mode === "selected" && availableFolders.some((item) => item.existingSpace && selectedIds.includes(item.id)))) && <p role="note" className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950">Inclui um espaço já sincronizado. Se a seleção for exatamente a de um espaço existente, ele passa por uma ressincronização completa: todos os arquivos são relidos e reconstruídos, o que pode levar tempo e consumir cota.</p>}<button disabled={!hasSelectedScope || !uniform || busy} onClick={() => { void selectAndSync(); }} className="mt-4 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{busy && <RefreshCw size={15} className="mr-2 inline motion-safe:animate-spin" aria-hidden="true" />}{busy ? "Sincronizando…" : "Sincronizar selecionados"}</button></section></>}
      {!catalog && (catalogError ? <div role="alert" className="mt-6 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{catalogError}<button onClick={() => { if (source) void loadCatalog(source); }} className="ml-2 font-semibold underline">Tentar novamente</button></div> : <LoadingIndicator label="Validando a conexão e carregando as pastas disponíveis…" className="mt-6 text-sm text-muted-foreground" />)}
    </section></div>}
  </>;
}

type ToolsCatalogProps = { sources: Source[]; sourcesLoading: boolean; sourcesError: string | null; onRetry: () => void; modalOpen: boolean; onOpen: () => void; onClose: () => void; onConnect: (sourceId?: string) => void; onConnectNotion: (sourceId?: string) => void; onConnectOneDrive: (sourceId?: string) => void; onConnectSharePoint: (sourceId?: string) => void; onManage: (source: Source) => void; onDisconnect: (source: Source) => void; disconnectingSourceId: string | null };

function IntegrationCatalog(props: ToolsCatalogProps) {
  if (props.sourcesLoading) return <div className="integration-catalog"><div className="integration-catalog-heading"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Fontes de conhecimento</h1><LoadingIndicator label="Carregando fontes conectadas…" className="mt-4 text-sm text-muted-foreground" /></div></div>;
  if (props.sourcesError) return <div className="integration-catalog"><div className="integration-catalog-heading"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Fontes de conhecimento</h1><div role="alert" className="state-panel state-panel-error mt-5"><CircleAlert size={22} /><p>{props.sourcesError}</p><button onClick={props.onRetry} className="font-semibold underline">Tentar novamente</button></div></div></div>;
  const comingSoon = (name: string, description: string) => <div className="integration-tool-card flex h-full flex-col rounded-lg border border-dashed border-line bg-white p-4"><div className="flex items-center gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><Table2 size={20} className="text-primary" aria-hidden="true" /></span><b className="text-sm">{name}</b></div><span className="mt-3 block text-xs leading-5 text-muted-foreground">{description}</span><span className="mt-auto inline-flex w-fit rounded-full bg-paper px-2.5 py-1 text-xs font-semibold text-muted-foreground">Em breve</span></div>;
  const notion = props.sources.find((source) => source.provider === "notion");
  const oneDrive = props.sources.find((source) => source.provider === "onedrive");
  const notionConnected = notion?.status === "connected";
  const notionStatus = notion ? statusLabel(notion.status) : "Disponível";
  const notionAccount = notion?.account_email ?? notion?.connected_by_email;
  const manageNotion = () => { if (notion?.status === "connected") props.onManage(notion); else props.onConnectNotion(notion?.id); };
  const notionAction = notionConnected ? "Gerenciar" : notion?.status === "reauth_required" ? "Reconectar" : "Conectar Notion";
  const notionCard = <section className="integration-tool-card h-full rounded-lg border border-line-soft bg-white p-4 shadow-sm"><button onClick={manageNotion} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><ProviderMark provider="notion" /></span><span className="min-w-0 flex-1"><b className="block text-sm">Notion</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Confira a conexão, sincronize páginas e faça re-sync dos espaços existentes.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line-soft pt-3 text-xs"><span className={`size-2 rounded-full ${notionConnected ? "bg-emerald-500" : notion?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} aria-hidden="true" /><span className="font-medium text-muted-foreground">{notionStatus}</span>{notionAccount && <span className="truncate text-muted-foreground">· {notionAccount}</span>}<span className="ml-auto flex items-center gap-2">{notion && notion.status !== "disconnected" && <button onClick={() => props.onDisconnect(notion)} disabled={props.disconnectingSourceId !== null} className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-2.5 py-2 text-xs font-semibold text-rose-700 transition-colors hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-500 disabled:opacity-50"><Unplug size={14} aria-hidden="true" />{props.disconnectingSourceId === notion.id ? "Desconectando…" : "Desconectar"}</button>}<button onClick={manageNotion} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">{notionAction}</button></span></div></section>;
  const oneDriveAccount = oneDrive?.account_email ?? oneDrive?.connected_by_email;
  const oneDriveManage = () => { if (oneDrive?.status === "connected") props.onManage(oneDrive); else props.onConnectOneDrive(oneDrive?.id); };
  const oneDriveAction = oneDrive?.status === "connected" ? "Gerenciar" : oneDrive?.status === "reauth_required" ? "Reconectar" : oneDrive?.status === "disconnected" ? "Reconectar" : "Conectar OneDrive";
  const oneDriveCard = <section className="integration-tool-card h-full rounded-lg border border-line-soft bg-white p-4 shadow-sm"><button onClick={oneDriveManage} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><ProviderMark provider="onedrive" /></span><span className="min-w-0 flex-1"><b className="block text-sm">OneDrive</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Conecte uma conta Microsoft pessoal, corporativa ou escolar, escolha pastas e sincronize os arquivos.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line-soft pt-3 text-xs"><span className={`size-2 rounded-full ${oneDrive?.status === "connected" ? "bg-emerald-500" : oneDrive?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} aria-hidden="true" /><span className="font-medium text-muted-foreground">{oneDrive ? statusLabel(oneDrive.status) : "Disponível"}</span>{oneDriveAccount && <span className="truncate text-muted-foreground">· {oneDriveAccount}</span>}<span className="ml-auto flex items-center gap-2">{oneDrive && oneDrive.status !== "disconnected" && <button onClick={() => props.onDisconnect(oneDrive)} disabled={props.disconnectingSourceId !== null} className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-2.5 py-2 text-xs font-semibold text-rose-700 transition-colors hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-500 disabled:opacity-50"><Unplug size={14} aria-hidden="true" />{props.disconnectingSourceId === oneDrive.id ? "Desconectando…" : "Desconectar"}</button>}<button onClick={oneDriveManage} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">{oneDriveAction}</button></span></div></section>;
  const sharePoint = props.sources.find((source) => source.provider === "sharepoint");
  const sharePointAccount = sharePoint?.account_email ?? sharePoint?.connected_by_email;
  const sharePointManage = () => { if (sharePoint?.status === "connected") props.onManage(sharePoint); else props.onConnectSharePoint(sharePoint?.id); };
  const sharePointAction = sharePoint?.status === "connected" ? "Gerenciar" : sharePoint?.status === "reauth_required" || sharePoint?.status === "disconnected" ? "Reconectar" : "Conectar SharePoint";
  const sharePointCard = <section className="integration-tool-card h-full rounded-lg border border-line-soft bg-white p-4 shadow-sm"><button onClick={sharePointManage} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><ProviderMark provider="sharepoint" /></span><span className="min-w-0 flex-1"><b className="block text-sm">SharePoint</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Conecte bibliotecas de documentos de sites SharePoint e Teams da sua organização Microsoft 365. Requer uma conta corporativa/escolar; o administrador do Microsoft 365 pode precisar aprovar o acesso.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line-soft pt-3 text-xs"><span className={`size-2 rounded-full ${sharePoint?.status === "connected" ? "bg-emerald-500" : sharePoint?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} aria-hidden="true" /><span className="font-medium text-muted-foreground">{sharePoint ? statusLabel(sharePoint.status) : "Disponível"}</span>{sharePointAccount && <span className="truncate text-muted-foreground">· {sharePointAccount}</span>}<span className="ml-auto flex items-center gap-2">{sharePoint && sharePoint.status !== "disconnected" && <button onClick={() => props.onDisconnect(sharePoint)} disabled={props.disconnectingSourceId !== null} className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-2.5 py-2 text-xs font-semibold text-rose-700 transition-colors hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-500 disabled:opacity-50"><Unplug size={14} aria-hidden="true" />{props.disconnectingSourceId === sharePoint.id ? "Desconectando…" : "Desconectar"}</button>}<button onClick={sharePointManage} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">{sharePointAction}</button></span></div></section>;
  const category = (name: ToolCategory, description: string, children: ReactNode) => <section className="mt-5"><h2 className="text-lg font-semibold text-ink">{name}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p><div className="integration-tool-grid mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{children}</div></section>;
  return <div className="integration-catalog"><div className="integration-catalog-heading"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Fontes de conhecimento</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">Conecte ferramentas que alimentam a base de conhecimento da sua organização.</p></div>{category("Arquivos", "Sincronize documentos e pastas da equipe.", <><ToolsCatalog {...props} />{oneDriveCard}{sharePointCard}</>)}{category("Documentação", "Reúna páginas e planejamento da equipe.", <>{notionCard}{comingSoon("Airtable", "Planejamento de campanhas, briefings e calendários de conteúdo.")}</>)}</div>;
}

function ToolsCatalog({ sources, modalOpen, onOpen, onClose, onConnect, onManage, onDisconnect, disconnectingSourceId }: ToolsCatalogProps) {
  const googleSources = sources.filter((source) => source.provider === "google_drive");
  const primary = googleSources.find((source) => source.status === "connected" || source.status === "reauth_required") ?? googleSources[0] ?? null;
  const connected = primary?.status === "connected";
  const statusLabel = primary?.status === "reauth_required" ? "Reconexão necessária" : primary?.status === "disconnected" ? "Desconectado" : connected ? "Conectado" : "Disponível";
  return <div className="max-w-4xl"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Integrações</h1><p className="mt-2 max-w-2xl leading-6 text-muted-foreground">Conecte ferramentas e mantenha os espaços sincronizados em um único fluxo.</p><section className="integration-tool-card mt-7 h-full max-w-xl rounded-lg border border-line-soft bg-white p-4 shadow-sm"><button onClick={onOpen} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 place-items-center rounded-lg bg-sage"><ProviderLogo provider="google" size={26} /></span><span className="min-w-0 flex-1"><b className="block text-sm">Google Drive</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Confira a conexão, adicione pastas e faça re-sync dos espaços existentes.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line-soft pt-3 text-xs"><span className={`size-2 rounded-full ${connected ? "bg-emerald-500" : primary?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} /><span className="font-medium text-muted-foreground">{statusLabel}</span>{primary?.account_email && <span className="truncate text-muted-foreground">· {primary.account_email}</span>}<span className="ml-auto flex items-center gap-2">{primary && primary.status !== "disconnected" && <button onClick={() => onDisconnect(primary)} disabled={disconnectingSourceId !== null} className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-2.5 py-2 text-xs font-semibold text-rose-700 transition-colors hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-rose-500 disabled:opacity-50"><Unplug size={14} aria-hidden="true" />{disconnectingSourceId === primary.id ? "Desconectando…" : "Desconectar"}</button>}{connected ? <button onClick={() => primary && onManage(primary)} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Gerenciar</button> : primary?.status === "reauth_required" ? <button onClick={() => onConnect(primary.id)} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Reconectar</button> : <button onClick={() => onConnect()} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Conectar</button>}</span></div></section>{modalOpen && <div role="dialog" aria-modal="true" aria-labelledby="google-drive-modal-title" className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4"><section className="w-full max-w-lg rounded-md bg-white p-6 shadow-2xl"><div className="flex items-start gap-4"><span className="grid size-11 place-items-center rounded-lg bg-sage"><ProviderLogo provider="google" size={28} /></span><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-primary">Integração</p><h2 id="google-drive-modal-title" className="mt-1 text-xl font-semibold">Google Drive</h2></div><button onClick={onClose} aria-label="Fechar" className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><X size={18} /></button></div>{primary ? <div className="mt-6 rounded-lg border border-line-soft bg-paper p-4"><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Conta autorizada</p><p className="mt-2 break-all font-medium text-ink">{primary.account_email ?? "Conta Google sem identificação disponível"}</p><p className="mt-1 text-sm text-muted-foreground">{statusLabel}. {primary.status === "reauth_required" ? "Autorize novamente para retomar sincronizações." : primary.status === "disconnected" ? "Autorize uma conta para retomar sincronizações." : "Esta conexão tem acesso somente leitura."}</p></div> : <div className="mt-6 rounded-lg border border-line-soft bg-paper p-4"><p className="font-medium">Nenhuma conta conectada</p><p className="mt-1 text-sm text-muted-foreground">Autorize uma conta Google para escolher pastas e sincronizar documentos.</p></div>}<div className="mt-6 flex flex-wrap justify-end gap-3">{primary?.status === "connected" && <button onClick={() => onManage(primary)} className="rounded-md border border-line px-4 py-2.5 text-sm font-semibold text-ink hover:bg-paper">Gerenciar</button>}<button onClick={() => onConnect(primary?.id)} className="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-forest-hover">{primary ? "Reconectar" : "Conectar Google Drive"}</button>{primary && primary.status !== "disconnected" && <button disabled={disconnectingSourceId !== null} onClick={() => onDisconnect(primary)} className="inline-flex items-center gap-2 rounded-md px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"><Unplug size={16} />{disconnectingSourceId === primary.id ? "Desconectando…" : "Desconectar"}</button>}</div><p className="mt-5 text-xs leading-5 text-muted-foreground">Desconectar remove a autorização salva neste produto e bloqueia novas sincronizações. Os dados já indexados não são apagados.</p></section></div>}</div>;
}

function StaffCenter({ user, onBack }: { user: User; onBack: () => void }) {
  const [companies, setCompanies] = useState<StaffCompany[]>([]); const [overview, setOverview] = useState<StaffOverview | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true);
  useEffect(() => { if (!user.is_platform_staff) return; void api<StaffCompany[]>("/platform/companies").then(setCompanies).catch((caught) => setError(messageFor(caught))).finally(() => setLoading(false)); }, [user.is_platform_staff]);
  async function open(company: StaffCompany) { try { setOverview(await api<StaffOverview>(`/platform/companies/${company.organization_id}/overview`)); } catch (caught) { setError(messageFor(caught)); } }
  if (!user.is_platform_staff) return <main className="auth-page"><section className="max-w-md text-center"><ShieldCheck className="mx-auto text-muted-foreground" /><h1 className="mt-4 text-2xl font-semibold">Área de suporte indisponível</h1><p className="mt-3 text-muted-foreground">Seu usuário não tem papel global de staff.</p><button onClick={onBack} className="mt-5 rounded-md bg-white px-4 py-2 text-sm font-semibold text-ink">Voltar</button></section></main>;
  return <main className="staff-app min-h-screen bg-violet-50 text-ink"><header className="border-b border-violet-200 bg-white"><div className="mx-auto flex max-w-6xl items-center gap-3 px-5 py-4"><ShieldCheck className="text-violet-700" /><div><b>Modo suporte</b><p className="text-xs text-muted-foreground">Metadados somente; conteúdo de cliente permanece inacessível.</p></div><button onClick={onBack} className="ml-auto rounded-lg border border-line px-3 py-2 text-sm">Voltar ao produto</button></div></header><div className="mx-auto grid max-w-6xl gap-5 p-5 lg:grid-cols-[330px_1fr]"><aside className="rounded-lg border border-violet-100 bg-white p-4"><h1 className="font-semibold">Organizações</h1>{loading && <p className="mt-4 text-sm text-muted-foreground">Carregando organizações…</p>}{error && <p className="mt-4 text-sm text-rose-700">{error}</p>}{companies.length > 0 && <select aria-label="Organização em suporte" defaultValue="" onChange={(event) => { const company = companies.find((item) => item.organization_id === event.target.value); if (company) void open(company); }} className="mt-4 w-full rounded-md border border-violet-200 bg-white px-3 py-2 text-sm font-semibold"><option value="">Selecione uma organização</option>{companies.map((company) => <option key={company.organization_id} value={company.organization_id}>{company.name}</option>)}</select>}</aside><section>{overview ? <StaffOverviewCard overview={overview} /> : <div className="rounded-lg border border-dashed border-violet-200 bg-white p-8 text-muted-foreground">Selecione uma organização para consultar o estado operacional. Esta área não oferece busca, documentos, links de fonte, perguntas, consultas salvas ou ações de Drive.</div>}</section></div></main>;
}
function StaffOverviewCard({ overview }: { overview: StaffOverview }) { return <section><div className="rounded-lg border border-violet-300 bg-violet-100 p-5 text-violet-950"><b>Acesso global de suporte</b><p className="mt-1 text-sm">Metadados operacionais somente; conteúdo de cliente permanece inacessível.</p></div><div className="mt-5 rounded-lg border border-line-soft bg-white p-6"><h1 className="text-xl font-semibold">Visão operacional</h1><p className="mt-2 text-sm text-muted-foreground">Somente estado de pastas e resumo agregado de códigos seguros de falha.</p><div className="mt-5 space-y-3">{overview.folders.map((folder) => <div key={folder.id} className="rounded-md border border-line-soft p-4"><b>{folder.name}</b><span className="ml-2 text-xs capitalize text-muted-foreground">{folder.status.replaceAll("_", " ")}</span>{folder.failure_summary.map((failure) => <p key={failure.error_code} className="mt-2 text-xs text-rose-700">{failure.count} falha(s): {failure.error_code}</p>)}</div>)}</div></div></section>; }
