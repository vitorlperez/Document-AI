"use client";

import { ChevronRight, CircleAlert, ExternalLink, FileText, FolderOpen, HardDrive, LogOut, PanelRightClose, PanelRightOpen, Plus, RefreshCw, Search, Send, Settings2, ShieldCheck, Sparkles, Trash2, Unplug, Users, X } from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { LandingPage } from "./landing-page";
import { cleanAnswerForDisplay } from "./answer-display";
import "./chat-workspace.css";
import "./product-layout.css";
import { Brand } from "./brand";
import { QuestionScopePicker, contextReady, toolLabel, providerKey, type QuestionScope, type QuestionContext } from "./question-scope";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

type Role = "owner" | "admin" | "member";
type Screen = "home" | "company" | "library" | "team" | "integrations" | "staff" | "invitation";
type Company = { id: string; name: string; membership_id: string; role: Role };
type User = { id: string; email: string; is_platform_staff?: boolean };
type Folder = { id: string; name: string; status: string; last_synced_at: string | null; source_id?: string; external_folder_id?: string; selection_kind?: string; selection_folder_ids?: string[] };
type DocumentFailure = { id: string; name: string; status: "failed"; error_code: string | null; source_url: string };
type LibraryDocumentRef = { workspace_folder_id: string; document_id: string };
type LibraryNode = { id: string; parent_id: string | null; source_id: string; source_provider?: string | null; kind: "source" | "folder" | "file"; name: string; mime_type: string | null; source_url: string | null; workspace_documents?: LibraryDocumentRef[] };
type LibraryPage = { items: LibraryNode[]; page?: number; pages?: number; total?: number };
type LibraryContext = QuestionContext;
type LibrarySync = { id: string; source_id: string; workspace_folder_id: string; workspace_name: string; status: string; created_at: string; started_at: string | null; completed_at: string | null; error_code: string | null };
type Member = { id: string; email: string; role: Role };
type Source = { id: string; provider: string; status: string; account_email: string | null; connected_by_email?: string | null };
const latestSourcePerProvider = (items: Source[]) => [...new Map(items.map((item) => [item.provider, item])).values()];
type ToolCategory = "Conectadas" | "Arquivos" | "Documentação" | "Comunicação";
type RemoteFolder = { id: string; name: string };
type ScopeCatalog = { folders: RemoteFolder[]; root_files: { available: boolean; label: string }; all_accessible: { available: boolean; label: string } };
type SavedQuery = { id: string; workspace_folder_id: string; name: string; query: string };
type Evidence = { document_id: string; document_name: string; excerpt: string; page_number: number | null; source_url: string | null; source_provider?: string | null };
type Answer = { answer: string | null; confidence: string; citations: Evidence[]; retrieval_status: string; coverage?: { total_folders: number; eligible_folders: number; pending_folders: number } };
type ConversationMessage = { id: string; role: "user" | "assistant"; content: string; contextName: string; contextId?: string; answer?: Answer; pending?: boolean; error?: string };
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
  source_file_unavailable: "O Google Drive não permitiu ler este arquivo.",
  text_extraction_failed: "Não foi possível extrair texto; o arquivo pode estar danificado ou usar uma estrutura não suportada.",
  empty_extracted_text: "Nenhum texto foi extraído. PDFs escaneados precisam de OCR, que ainda não está disponível.",
} as Record<string, string>)[code ?? ""] ?? "Não há uma explicação disponível para este código.";
const providerIcon = (provider: string | null | undefined) => ({
  google_drive: "https://api.iconify.design/logos:google-drive.svg",
  onedrive: "https://api.iconify.design/logos:microsoft-onedrive.svg",
  notion: "https://api.iconify.design/logos:notion-icon.svg",
} as Record<string, string>)[provider ?? ""];
const providerIconFromName = (name: string) => ({
  "google drive": providerIcon("google_drive"),
  notion: providerIcon("notion"),
} as Record<string, string | undefined>)[name.trim().toLowerCase()];
function LibraryNodeIcon({ item, size = 16 }: { item: LibraryNode; size?: number }) {
  const isRoot = item.kind === "source" || item.parent_id === null;
  const icon = isRoot ? providerIcon(item.source_provider) ?? providerIconFromName(item.name) : undefined;
  if (icon) return <img src={icon} alt="" aria-hidden="true" className="object-contain" style={{ width: size, height: size }} />;
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
    try { const value = await api<T>(path, { signal: next.signal }); if (!next.signal.aborted) onSuccess(value); }
    catch (error) { if (!next.signal.aborted) onError(error); }
    finally { if (!next.signal.aborted) onSettled?.(); }
  }, []);
  return { request, cancel };
}
const companyPath = (companyId: string, suffix = "") => `/companies/${companyId}${suffix}`;
const retrievalMessage = (status: string) => status === "no_indexed_content" ? "Ainda não há conteúdo consultável neste escopo. Aguarde a sincronização ou escolha outra pasta." : status === "no_compatible_embeddings" ? "O conteúdo foi encontrado, mas a indexação de IA ainda não terminou. Tente novamente em alguns instantes." : status === "invalid_generation_output" ? "Encontrei trechos relevantes, mas não foi possível produzir uma resposta verificável. Tente novamente." : "Não encontrei evidência suficiente neste escopo para responder com segurança.";
const answerText = (answer: Answer) => cleanAnswerForDisplay(answer.answer) || (answer.answer === null ? retrievalMessage(answer.retrieval_status) : "Confira os documentos utilizados abaixo.");
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
    try { const [current, memberships] = await Promise.all([api<User>("/me"), api<Company[]>("/organizations")]); setUser(current); setCompanies(memberships); if (screen === "home" && memberships[0]) router.replace(companyPath(memberships[0].id)); }
    catch (caught) { if (!(caught instanceof ApiError && caught.status === 401)) setError(messageFor(caught)); }
    finally { setLoading(false); }
  }, [router, screen]);
  useEffect(() => { void Promise.resolve().then(loadSession); }, [loadSession]);
  const oauthProvider = screen === "integrations" ? searchParams.get("connected") : null;
  const oauthError = screen === "integrations" ? searchParams.get("error") : null;
  const oauthFailure = oauthError === "onedrive_account_mismatch"
    ? "Esta fonte já pertence a outra conta OneDrive. Reconecte com a mesma conta para preservar as pastas indexadas."
    : oauthError === "onedrive"
      ? "Não foi possível conectar o OneDrive. Tente novamente."
      : null;
  const oauthNotice = oauthProvider === "google_drive" ? "Google Drive conectado. Abra a ferramenta para definir o escopo e iniciar uma sincronização." : oauthProvider === "onedrive" ? "OneDrive conectado. Escolha as pastas que sua equipe pode consultar e inicie a sincronização." : null;
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
    {screen === "integrations" && (company.role === "member" ? <section role="alert" className="mx-auto max-w-lg rounded-lg border border-line bg-white p-8 text-center"><ShieldCheck className="mx-auto text-primary" size={28} /><h1 className="mt-4 text-xl font-semibold text-ink">Acesso restrito</h1><p className="mt-2 text-sm text-muted-foreground">Somente responsáveis e administradores podem gerenciar integrações.</p><button onClick={() => router.push(companyPath(company.id))} className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white">Voltar à conversa</button></section> : <IntegrationScreen key={company.id} company={company} setError={setError} setNotice={setNotice} />)}
  </Shell>;
}

function LoadingIndicator({ label, className = "" }: { label: string; className?: string }) {
  return <span role="status" aria-live="polite" className={`inline-flex items-center gap-2 ${className}`}><RefreshCw size={16} className="shrink-0 motion-safe:animate-spin" aria-hidden="true" /><span>{label}</span></span>;
}
function Loading() { return <main className="auth-page"><div className="text-center"><Brand /><LoadingIndicator label="Preparando seu espaço de conhecimento…" className="mt-3 justify-center text-sm text-muted-foreground" /></div></main>; }
function SignIn({ onLogin, onSignUp }: { onLogin: () => void; onSignUp: () => void }) {
  return <main className="auth-page"><section className="auth-card"><Link href="/" className="auth-brand"><Brand /></Link><p className="mt-12 text-xs font-semibold uppercase tracking-widest text-primary">Bom ter você por aqui</p><h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink">Sua equipe sabe.<br />Encontre a resposta.</h1><p className="mt-4 leading-7 text-muted-foreground">Entre para consultar seus documentos e conferir a fonte de cada resposta.</p><div className="mt-8 space-y-3"><button onClick={onLogin} className="w-full rounded-md bg-primary px-4 py-3 font-semibold text-white hover:bg-forest-hover">Entrar na minha conta</button><button onClick={onSignUp} className="w-full rounded-md border border-line bg-white px-4 py-3 font-semibold text-ink hover:bg-paper">Criar uma conta</button></div><p className="mt-7 text-center text-xs leading-5 text-muted-foreground">Seus documentos continuam no Google Drive.</p></section></main>;
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
  return <main className="auth-page"><section className="auth-card"><Brand /><p className="mt-6 text-sm text-muted-foreground">{user.email}</p><h1 className="mt-2 text-3xl font-semibold">Crie sua primeira organização</h1><p className="mt-3 leading-6 text-muted-foreground">Reúna os documentos da sua equipe em um só lugar. Depois, conecte o Google Drive e convide as pessoas com quem você trabalha.</p><form onSubmit={create} className="mt-7"><label htmlFor="company-name" className="text-sm font-medium">Nome da organização</label><input id="company-name" required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder="Ex.: Estúdio Aurora" className="mt-2 w-full rounded-md border border-line bg-white px-4 py-3 outline-none ring-primary focus:ring-2" />{error && <p className="mt-3 text-sm text-rose-700">{error}</p>}<button disabled={busy || !name.trim()} className="mt-5 inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 font-semibold text-white disabled:opacity-50"><Plus size={17} />{busy ? "Criando…" : "Criar organização"}</button></form></section></main>;
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
  const [spacesPanelOpen, setSpacesPanelOpen] = useState(true);
  const [path, setPath] = useState<LibraryNode[]>([]); const [items, setItems] = useState<LibraryNode[]>([]); const [folders, setFolders] = useState<Folder[]>([]); const [foldersLoading, setFoldersLoading] = useState(true); const [loading, setLoading] = useState(true); const [busyFolderId, setBusyFolderId] = useState<string | null>(null); const [busyFolderAction, setBusyFolderAction] = useState<"sync" | "remove" | null>(null); const [managedFile, setManagedFile] = useState<LibraryNode | null>(null); const [managedDocument, setManagedDocument] = useState<LibraryDocumentRef | null>(null); const [managingFile, setManagingFile] = useState(false); const [managingFileAction, setManagingFileAction] = useState<"remove" | "reprocess" | null>(null);
  const [documentFailures, setDocumentFailures] = useState<Record<string, DocumentFailure[]>>({}); const [failureLoadError, setFailureLoadError] = useState<Record<string, boolean>>({});
  const canManage = company.role !== "member"; const current = path.at(-1);
  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<{ page: number; pages: number; total: number } | null>(null);
  const [query, setQuery] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const { request: requestItems } = useLatestRequest<LibraryPage>();
  const openPath = (nodes: LibraryNode[]) => { setPath(nodes); setPage(1); setQuery(""); setSearchTerm(""); };

  const loadItems = useCallback(() => {
    setLoading(true); setLoadError(null); setItems([]); setPagination(null);
    const request = searchTerm ? `/library/search?organization_id=${company.id}&query=${encodeURIComponent(searchTerm)}` : current ? `/library/nodes/${current.id}/children?organization_id=${company.id}&page=${page}` : `/library?organization_id=${company.id}`;
    void requestItems(request, (result) => { setItems(result.items); setPagination(typeof result.page === "number" && typeof result.pages === "number" && typeof result.total === "number" ? { page: result.page, pages: result.pages, total: result.total } : null); }, (caught) => setLoadError(messageFor(caught)), () => setLoading(false));
  }, [company.id, current, page, searchTerm, requestItems]);
  const loadFolders = useCallback(() => { setFoldersLoading(true); void api<Folder[]>(`/workspace-folders?organization_id=${company.id}`).then(setFolders).catch((caught) => setError(messageFor(caught))).finally(() => setFoldersLoading(false)); }, [company.id, setError]);
  useEffect(() => { void Promise.resolve().then(loadItems); }, [loadItems]); useEffect(() => { void Promise.resolve().then(loadFolders); }, [loadFolders]);
  useEffect(() => {
    if (!folders.some((folder) => folder.status === "queued" || folder.status === "syncing")) return;
    const timer = window.setInterval(loadFolders, 5000);
    return () => window.clearInterval(timer);
  }, [folders, loadFolders]);
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
      setFailureLoadError(Object.fromEntries(results.map(([id, _rows, failed]) => [id, failed])));
    });
    return () => { active = false; };
    }, [canManage, company.id, folders]);
  function openItem(item: LibraryNode) { if (item.kind === "file") { if (item.source_url) window.open(item.source_url, "_blank", "noopener,noreferrer"); return; } openPath(searchTerm ? [item] : [...path, item]); }
  function manageFile(item: LibraryNode) { const reference = item.workspace_documents?.[0] ?? null; if (!reference) { setError("Este arquivo não possui uma cópia indexada disponível para gerenciar."); return; } setManagedFile(item); setManagedDocument(reference); }
  async function syncFolder(folder: Folder) { setBusyFolderId(folder.id); setBusyFolderAction("sync"); setError(null); try { await api<{ job_id: string; status: string }>(`/workspace-folders/${folder.id}/sync?organization_id=${company.id}`, { method: "POST" }); setNotice(`Sincronização de “${folder.name}” iniciada em segundo plano.`); loadFolders(); } catch (caught) { setError(messageFor(caught)); } finally { setBusyFolderId(null); setBusyFolderAction(null); } }
  async function removeFolder(folder: Folder) { if (!window.confirm(`Remover “${folder.name}” desta base? Isso remove os documentos e as consultas salvas deste espaço no Arquivio. Nenhum arquivo ou pasta será apagado do Google Drive.`)) return; setBusyFolderId(folder.id); setBusyFolderAction("remove"); setError(null); try { await api<void>(`/workspace-folders/${folder.id}?organization_id=${company.id}`, { method: "DELETE" }); setNotice(`O escopo “${folder.name}” foi removido do índice local.`); if (managedDocument?.workspace_folder_id === folder.id) { setManagedFile(null); setManagedDocument(null); } loadFolders(); loadItems(); } catch (caught) { setError(messageFor(caught)); } finally { setBusyFolderId(null); setBusyFolderAction(null); } }
  async function reprocessFile() { if (!managedFile || !managedDocument) return; setManagingFile(true); setManagingFileAction("reprocess"); try { await api<{ job_id: string; status: string }>(`/workspace-folders/${managedDocument.workspace_folder_id}/documents/${managedDocument.document_id}/reprocess?organization_id=${company.id}`, { method: "POST" }); setNotice(`Reprocessamento de “${managedFile.name}” agendado.`); setManagedFile(null); setManagedDocument(null); loadFolders(); } catch (caught) { setError(messageFor(caught)); } finally { setManagingFile(false); setManagingFileAction(null); } }
  async function removeFile() { if (!managedFile || !managedDocument) return; if (!window.confirm(`Remover “${managedFile.name}” somente deste índice local? O original continuará no Google Drive.`)) return; setManagingFile(true); setManagingFileAction("remove"); try { await api<void>(`/workspace-folders/${managedDocument.workspace_folder_id}/documents/${managedDocument.document_id}?organization_id=${company.id}`, { method: "DELETE" }); setNotice(`“${managedFile.name}” foi removido do índice local.`); setManagedFile(null); setManagedDocument(null); loadItems(); loadFolders(); } catch (caught) { setError(messageFor(caught)); } finally { setManagingFile(false); setManagingFileAction(null); } }
  const references = managedFile?.workspace_documents ?? []; const selectedScope = managedDocument ? folders.find((folder) => folder.id === managedDocument.workspace_folder_id) : null;
  return <><div className="workspace-frame overflow-hidden border border-line bg-white"><div className={`grid library-panels min-h-[calc(100vh-14rem)]${spacesPanelOpen ? "" : " spaces-panel-collapsed"}`}><aside className="border-b border-line bg-sage xl:border-b-0 xl:border-r"><LibrarySidebarHeader canManage={canManage} onConnect={onConnect} onRefresh={loadItems} /><LibraryBreadcrumbs path={path} onOpenPath={openPath} /><div className="space-y-1">{loading ? <LoadingIndicator label="Abrindo estrutura…" className="p-3 text-sm text-muted-foreground" /> : items.length === 0 ? <p className="p-3 text-sm text-muted-foreground">Nenhum item neste nível.</p> : items.map((item) => <button key={item.id} onClick={() => openItem(item)} className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-white"><span className={`grid size-7 place-items-center rounded-lg ${item.kind === "file" ? "bg-sage-selected text-muted-foreground" : "bg-sage-selected text-primary"}`}><LibraryNodeIcon item={item} size={14} /></span><span className="min-w-0 flex-1 truncate">{item.name}</span>{item.kind !== "file" && <ChevronRight size={15} className="text-muted-foreground" />}</button>)}</div></aside><main className="relative min-w-0 p-5 sm:p-7" aria-busy={loading}><div className="flex items-center justify-between"><div><p className="text-sm font-semibold text-ink">{searchTerm ? `Resultados para “${searchTerm}”` : current?.name ?? "Todas as fontes"}</p><p className="mt-1 text-sm text-muted-foreground">Clique em uma pasta para navegar. Clique em um arquivo para abrir a origem.</p></div><span className="rounded-full bg-sage px-2.5 py-1 text-xs text-muted-foreground">{pagination?.total ?? items.length} itens</span><button type="button" onClick={() => setSpacesPanelOpen((open) => !open)} aria-controls="library-spaces" aria-expanded={spacesPanelOpen} aria-label={spacesPanelOpen ? "Ocultar espaços sincronizados" : "Mostrar espaços sincronizados"} title={spacesPanelOpen ? "Ocultar espaços sincronizados" : "Mostrar espaços sincronizados"} className="shrink-0 rounded-lg p-2 text-muted-foreground hover:bg-sage hover:text-ink">{spacesPanelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}</button></div><form onSubmit={(event) => { event.preventDefault(); setPage(1); setSearchTerm(query.trim()); }} className="mt-5 flex gap-2"><label htmlFor="library-search" className="sr-only">Buscar arquivos e pastas por nome</label><input id="library-search" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} placeholder="Buscar pelo nome em toda a biblioteca" className="min-w-0 flex-1 rounded-md border border-line px-3 py-2.5 text-sm" /><button aria-label="Buscar na biblioteca" className="rounded-md bg-primary px-3 text-white"><Search size={18} /></button>{searchTerm && <button type="button" onClick={() => { setQuery(""); setSearchTerm(""); setPage(1); }} aria-label="Limpar busca" className="rounded-md border px-3"><X size={17} /></button>}</form>{searchTerm && <p className="mt-2 text-xs text-muted-foreground">Busca por nome em todas as fontes conectadas.</p>}
      {loading ? <div className="library-empty"><LoadingIndicator label="Carregando arquivos…" /></div> : loadError ? <div role="alert" className="library-empty"><CircleAlert size={24} /><p>{loadError}</p><button onClick={loadItems} className="text-sm font-semibold text-primary underline">Tentar novamente</button></div> : items.length === 0 ? <div className="library-empty"><FolderOpen size={32} /><h2 className="font-semibold text-ink">{searchTerm ? "Nenhum resultado encontrado" : current ? "Esta pasta está vazia" : "Sua biblioteca começa aqui"}</h2><p className="max-w-sm text-sm leading-6">{searchTerm ? "Tente uma palavra diferente ou parte do nome do arquivo." : current ? "Os arquivos aparecerão aqui depois da sincronização." : canManage ? "Conecte o Google Drive e escolha as pastas que sua equipe pode consultar." : "Um administrador precisa conectar o Google Drive e sincronizar as pastas da equipe."}</p>{!current && !searchTerm && canManage && <button onClick={onConnect} className="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white">Conectar Google Drive</button>}</div> : <div className="mt-6 grid gap-2 sm:grid-cols-2">{items.map((item) => <div key={item.id} className="flex min-w-0 items-center rounded-lg border border-line bg-white p-3 hover:border-sage-selected"><button onClick={() => openItem(item)} className="flex min-w-0 flex-1 items-center gap-3 text-left"><span className={`grid size-10 place-items-center rounded-md ${item.kind === "file" ? "bg-sage text-muted-foreground" : "bg-sage-selected text-primary"}`}><LibraryNodeIcon item={item} size={18} /></span><span className="min-w-0"><b className="block truncate text-sm text-ink">{item.name}</b><span className="mt-0.5 block text-xs text-muted-foreground">{item.kind === "file" ? "Arquivo indexado" : item.kind === "source" ? "Integração" : "Pasta"}</span></span></button>{canManage && item.kind === "file" && (item.workspace_documents?.length ?? 0) > 0 && <button onClick={() => manageFile(item)} title="Gerenciar arquivo" aria-label={`Gerenciar ${item.name}`} className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><Settings2 size={16} /></button>}</div>)}</div>}{pagination && pagination.pages > 1 && <Pagination value={pagination} loading={loading} onChange={setPage} />}</main><aside id="library-spaces" hidden={!spacesPanelOpen} className="border-t border-line bg-paper/50 p-4 xl:border-l xl:border-t-0"><div className="flex items-center justify-between"><div><p className="text-sm font-semibold">Espaços sincronizados</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Ações aplicam-se ao índice local do escopo.</p></div><button onClick={loadFolders} className="rounded-lg p-2 text-muted-foreground hover:bg-white" aria-label="Atualizar espaços"><RefreshCw size={15} /></button></div><div className="mt-4 space-y-3">{foldersLoading && folders.length === 0 ? <LoadingIndicator label="Carregando espaços sincronizados…" className="rounded-md border border-dashed p-4 text-sm text-muted-foreground" /> : folders.length === 0 ? <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">Nenhum espaço sincronizado.</p> : folders.map((folder) => <article key={folder.id} className="rounded-lg border border-line bg-white p-4"><div className="flex items-start justify-between gap-2"><b className="min-w-0 truncate text-sm text-ink">{folder.name}</b><span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${folder.status === "ready" ? "bg-emerald-100 text-emerald-800" : folder.status === "partial_failure" ? "bg-amber-100 text-amber-800" : "bg-sage-selected text-primary"}`}>{(folder.status === "queued" || folder.status === "syncing") && <RefreshCw size={11} className="mr-1 inline motion-safe:animate-spin" aria-hidden="true" />}{statusLabel(folder.status)}</span></div><p className="mt-2 text-xs text-muted-foreground">{folder.last_synced_at ? `Última sincronização: ${new Date(folder.last_synced_at).toLocaleString("pt-BR")}` : "Ainda não sincronizado"}</p>{canManage && folder.status === "partial_failure" && <section className="mt-3 rounded-md border border-amber-200 bg-amber-50 p-3" aria-label={`Falhas da pasta ${folder.name}`}><p className="text-xs font-semibold text-amber-900">Arquivos com falha</p>{failureLoadError[folder.id] ? <p className="mt-2 text-xs text-amber-900">Não foi possível carregar os detalhes. Atualize os espaços e tente novamente.</p> : documentFailures[folder.id] ? documentFailures[folder.id].length === 0 ? <p className="mt-2 text-xs text-amber-900">Nenhuma falha de arquivo encontrada.</p> : <ul className="mt-2 max-h-48 space-y-2 overflow-y-auto">{documentFailures[folder.id].map((file) => <li key={file.id} className="border-t border-amber-200 pt-2"><p className="break-words text-xs font-medium text-ink">{file.name}</p><p className="mt-0.5 text-[11px] text-amber-900">{documentFailureLabel(file.error_code)} <code>({file.error_code ?? "sem código"})</code></p></li>)}</ul> : <p role="status" className="mt-2 text-xs text-amber-900">Carregando detalhes…</p>}</section>}{canManage && <div className="mt-4 flex gap-2"><button disabled={busyFolderId !== null} onClick={() => { void syncFolder(folder); }} className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-line px-2 py-2 text-xs font-semibold text-ink hover:bg-paper disabled:opacity-50">{busyFolderId === folder.id && busyFolderAction === "sync" ? <RefreshCw size={14} className="motion-safe:animate-spin" aria-hidden="true" /> : <RefreshCw size={14} />}{busyFolderId === folder.id && busyFolderAction === "sync" ? "Sincronizando…" : "Ressincronizar"}</button><button disabled={busyFolderId !== null} onClick={() => { void removeFolder(folder); }} className="inline-flex items-center justify-center rounded-lg border border-rose-200 px-2.5 text-rose-700 hover:bg-rose-50 disabled:opacity-50" title={busyFolderId === folder.id && busyFolderAction === "remove" ? "Removendo espaço…" : "Remover escopo do índice"} aria-busy={busyFolderId === folder.id && busyFolderAction === "remove"} aria-label={busyFolderId === folder.id && busyFolderAction === "remove" ? `Removendo ${folder.name}` : `Remover ${folder.name} do Arquivio`}>{busyFolderId === folder.id && busyFolderAction === "remove" ? <RefreshCw size={15} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={15} />}</button></div>}</article>)}</div></aside></div></div>{managedFile && managedDocument && <div className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4" role="dialog" aria-modal="true" aria-labelledby="library-file-management"><section className="w-full max-w-md rounded-lg bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-primary">Índice local</p><h2 id="library-file-management" className="mt-1 text-xl font-semibold">Gerenciar arquivo</h2></div><button disabled={managingFile} onClick={() => { setManagedFile(null); setManagedDocument(null); }} className="rounded-lg p-2 text-muted-foreground hover:bg-sage" aria-label="Fechar"><X size={18} /></button></div><div className="mt-5 rounded-md bg-paper p-4"><b className="block text-ink">{managedFile.name}</b><p className="mt-1 text-sm leading-6 text-muted-foreground">O arquivo original no Google Drive não será alterado.</p></div>{references.length > 1 && <label className="mt-5 block text-sm font-medium">Espaço de conhecimento<select value={managedDocument.document_id} disabled={managingFile} onChange={(event) => setManagedDocument(references.find((reference) => reference.document_id === event.target.value) ?? null)} className="mt-2 w-full rounded-md border border-line px-3 py-2.5 text-sm">{references.map((reference) => <option key={reference.document_id} value={reference.document_id}>{folders.find((folder) => folder.id === reference.workspace_folder_id)?.name ?? "Espaço sincronizado"}</option>)}</select></label>}<p className="mt-4 text-xs text-muted-foreground">{selectedScope ? `Espaço selecionado: ${selectedScope.name}` : "Espaço selecionado para esta cópia."}</p><div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><button disabled={managingFile} aria-busy={managingFile} onClick={() => { void removeFile(); }} className="inline-flex items-center justify-center gap-2 rounded-md border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">{managingFileAction === "remove" ? <RefreshCw size={16} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={16} />}{managingFileAction === "remove" ? "Removendo…" : "Remover do índice"}</button><button disabled={managingFile} aria-busy={managingFile} onClick={() => { void reprocessFile(); }} className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50"><RefreshCw size={16} className={managingFileAction === "reprocess" ? "motion-safe:animate-spin" : ""} aria-hidden="true" />{managingFileAction === "reprocess" ? "Reprocessando…" : "Reprocessar"}</button></div></section></div>}</>;
}

function Pagination({ value, loading, onChange }: { value: { page: number; pages: number; total: number }; loading: boolean; onChange: (page: number) => void }) {
  return <nav aria-label="Paginação da biblioteca" className="mt-4 flex items-center justify-between gap-3 border-t border-line px-2 py-3 text-xs text-muted-foreground"><span>Página {value.page} de {value.pages} · {value.total} itens</span><div className="flex gap-1"><button disabled={loading || value.page <= 1} onClick={() => onChange(value.page - 1)} aria-label="Página anterior" className="rounded-lg border bg-white px-2.5 py-2 disabled:opacity-40">←</button><button disabled={loading || value.page >= value.pages} onClick={() => onChange(value.page + 1)} aria-label="Próxima página" className="rounded-lg border bg-white px-2.5 py-2 disabled:opacity-40">→</button></div></nav>;
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
  const [contextId, setContextId] = useState("");
  const [queryScope, setQueryScope] = useState<QuestionScope>("organization");
  const [queryProvider, setQueryProvider] = useState("");
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [asking, setAsking] = useState(false);
  const [filesPanelOpen, setFilesPanelOpen] = useState(true);
  const [managedFile, setManagedFile] = useState<LibraryNode | null>(null);
  const [managedDocument, setManagedDocument] = useState<LibraryDocumentRef | null>(null);
  const [managingFile, setManagingFile] = useState(false); const [managingFileAction, setManagingFileAction] = useState<"remove" | "reprocess" | null>(null);
  const current = path.at(-1);
  const canManage = company.role !== "member";
  const activeContext = contexts.find((item) => item.id === contextId) ?? null;
  const canAsk = !contextLoading && !contextError && contexts.some((item) => contextReady(item) && (queryScope === "organization" || (queryScope === "provider" ? providerKey(item.source_provider) === queryProvider : item.id === contextId)));

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
    const pendingId = `${requestId}:assistant`;
    setMessages((items) => [
      ...items,
      { id: requestId, role: "user", content: submittedQuestion, contextName: queryScope === "folder" ? activeContext?.name ?? "Pasta selecionada" : queryScope === "provider" ? toolLabel(queryProvider) : "Todas as ferramentas", contextId: queryScope === "folder" ? activeContext?.id : undefined },
      { id: pendingId, role: "assistant", content: "", contextName: queryScope === "folder" ? activeContext?.name ?? "Pasta selecionada" : queryScope === "provider" ? toolLabel(queryProvider) : "Todas as ferramentas", pending: true },
    ]);
    setQuestion("");
    setAsking(true);
    try {
      const result = queryScope === "folder"
        ? await api<Answer>(`/workspace-folders/${activeContext?.id}/questions?organization_id=${company.id}`, { method: "POST", body: JSON.stringify({ question: submittedQuestion }) })
        : await api<Answer>(`/organizations/${company.id}/questions`, { method: "POST", body: JSON.stringify({ question: submittedQuestion, scope: queryScope, provider: queryScope === "provider" ? queryProvider : undefined }) });
      const answer = { ...result, citations: compactCitations(result.citations.map((citation) => ({ ...citation, source_provider: citation.source_provider ?? (queryScope === "folder" ? activeContext?.source_provider : undefined) }))) };
      setMessages((items) => items.map((item) => item.id === pendingId ? { ...item, pending: false, answer } : item));
    } catch (caught) {
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
        <p className="sources-scope flex gap-2 px-4 py-5 text-xs leading-5 text-muted-foreground"><ShieldCheck size={16} className="shrink-0 text-primary" />A conversa usa somente o contexto escolhido em “Consultar em”.</p>
      </aside>
      <main id="consultas" className="conversation-panel relative flex min-h-[560px] min-w-0 flex-col bg-white">
        <button type="button" onClick={() => setFilesPanelOpen((open) => !open)} aria-controls="chat-library" aria-expanded={filesPanelOpen} aria-label={filesPanelOpen ? "Ocultar consulta de arquivos" : "Mostrar consulta de arquivos"} title={filesPanelOpen ? "Ocultar consulta de arquivos" : "Mostrar consulta de arquivos"} className="absolute right-3 top-2 z-10 rounded-lg p-2 text-muted-foreground hover:bg-sage hover:text-ink">{filesPanelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}</button>
        <QuestionScopePicker scope={queryScope} provider={queryProvider} contextId={contextId} contexts={contexts} loading={contextLoading} disabled={asking} error={contextError} onRetry={loadOperations} onChange={(scope, value) => { setQueryScope(scope); setContextId(scope === "folder" ? value : ""); setQueryProvider(scope === "provider" ? value : ""); }} />
        <div ref={transcriptRef} role="log" aria-label="Conversa com seus documentos" aria-live="polite" className="flex-1 overflow-y-auto px-5 py-6 sm:px-7">{messages.length > 0 ? <div className="mx-auto max-w-3xl space-y-5">{messages.map((message) => message.role === "user" ? <div key={message.id} className="ml-auto max-w-[85%]"><p className="mb-1 text-right text-xs font-medium text-muted-foreground">{message.contextName}</p><div className="conversation-question px-4 py-3 text-sm leading-6">{message.content}</div>{message.contextId && <button disabled={saving} onClick={() => { void saveQuestion(message); }} className="mt-1.5 block ml-auto text-xs text-muted-foreground underline-offset-4 hover:underline disabled:opacity-40">Salvar pergunta</button>}</div> : <article key={message.id} className="conversation-answer"><div className="flex items-center gap-2"><span className="grid size-7 place-items-center rounded-lg bg-sage-selected text-primary"><Sparkles size={15} /></span><div><p className="text-sm font-semibold text-ink">Arquivio</p><p className="text-xs text-muted-foreground">{message.contextName}</p></div></div>{message.pending ? <div className="mt-4 rounded-md bg-paper px-3 py-2.5"><LoadingIndicator label="A IA está analisando as evidências e preparando a resposta…" className="text-sm text-muted-foreground" /></div> : message.error ? <p className="mt-4 text-sm leading-6 text-rose-700">Não foi possível concluir esta pergunta: {message.error}</p> : message.answer ? <><p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-ink">{answerText(message.answer)}</p>{Boolean(message.answer.coverage?.pending_folders) && <p className="mt-2 text-xs text-amber-800">Cobertura parcial: {message.answer.coverage?.eligible_folders} de {message.answer.coverage?.total_folders} pastas disponíveis nesta consulta.</p>}{message.answer.citations.length > 0 && <SourceDocuments items={message.answer.citations} />}</> : null}</article>)}</div> : <div className="mx-auto flex h-full max-w-md flex-col items-center justify-center py-16 text-center"><span className="grid size-12 place-items-center rounded-lg bg-sage text-primary"><Sparkles size={22} /></span><h2 className="mt-4 text-lg font-semibold text-ink">O que você quer descobrir?</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Pergunte sobre suas ferramentas conectadas ou escolha um contexto acima. Cada resposta identifica os arquivos e as ferramentas usados como evidência.</p>{canAsk && <div className="mt-6 flex flex-wrap justify-center gap-2">{["Quais são os principais prazos?", "O que foi definido sobre as entregas?", "Quais são as responsabilidades da equipe?"].map((prompt) => <button key={prompt} onClick={() => { setQuestion(prompt); composerRef.current?.focus(); }} className="rounded-md border border-line px-3 py-2 text-xs text-muted-foreground hover:border-primary hover:bg-sage">{prompt}</button>)}</div>}</div>}</div>
        <form onSubmit={(event) => { void ask(event); }} className="conversation-composer shrink-0 bg-white p-4 sm:px-7 sm:py-5"><div className="rounded-lg border border-line bg-white p-2 shadow-sm focus-within:border-primary focus-within:ring-2 focus-within:ring-sage-selected"><textarea ref={composerRef} aria-label="Sua pergunta" onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={1000} rows={2} placeholder={canAsk ? "O que você gostaria de saber?" : "Aguarde conteúdo indexado ou escolha outro contexto"} className="w-full resize-none border-0 bg-transparent px-2 py-1 text-sm outline-none placeholder:text-muted-foreground" /><div className="flex items-center justify-between border-t border-line-soft px-2 pt-2"><span className="text-xs text-muted-foreground">{question.length}/1000</span><button disabled={!canAsk || !question.trim() || asking} className="inline-flex items-center gap-2 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-forest-hover disabled:cursor-not-allowed disabled:opacity-40">{asking ? <RefreshCw size={15} className="motion-safe:animate-spin" aria-hidden="true" /> : <Send size={15} />}{asking ? "Consultando…" : "Enviar"}</button></div></div><p className="mt-2 text-xs text-muted-foreground">A IA usa somente o escopo selecionado e não responde sem evidência suficiente.</p></form>
      </main>
      <aside id="chat-library" hidden={!filesPanelOpen} className="context-panel border-t border-line bg-white xl:border-l xl:border-t-0">
        <section className="p-4"><p className="text-sm font-semibold text-ink">Buscar arquivos</p><p className="mt-1 text-xs leading-5 text-muted-foreground">Encontre arquivos e pastas pelo nome em todas as fontes conectadas.</p><form onSubmit={(event) => { void searchLibrary(event); }} className="mt-3 flex gap-2"><input aria-label="Buscar nome de arquivo ou pasta" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} placeholder="Nome de arquivo ou pasta" className="min-w-0 flex-1 rounded-md border border-line bg-white px-3 py-2 text-sm outline-none focus:border-primary" /><button className="rounded-md border border-line bg-white px-3 text-muted-foreground hover:bg-sage" aria-label="Buscar arquivos"><Search size={16} /></button></form>{!searching && searchedQuery && results.length === 0 && <p className="mt-3 text-xs text-muted-foreground">Nenhum nome encontrado.</p>}{searching && <LoadingIndicator label="Buscando…" className="mt-3 text-xs text-muted-foreground" />}{searchedQuery && <p className="mt-2 text-xs text-muted-foreground">Resultados para “{searchedQuery}”</p>}{results.length > 0 && <div className="mt-3 max-h-40 space-y-1 overflow-auto">{results.map((item) => <button key={item.id} onClick={() => { if (item.kind === "file") openItem(item); else openPath([item]); }} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-white"><span className="text-primary"><LibraryNodeIcon item={item} size={14} /></span><span className="min-w-0 flex-1 truncate">{item.name}</span></button>)}</div>}<p className="mt-2 text-xs leading-5 text-muted-foreground">A busca consulta somente nomes; o conteúdo permanece no escopo da conversa.</p></section>
      </aside>
    </div>
  </div>{managedFile && managedDocument && <div className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4" role="dialog" aria-modal="true" aria-labelledby="manage-file-title"><section className="w-full max-w-md rounded-lg bg-white p-6 shadow-2xl"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-wide text-primary">Índice local</p><h2 id="manage-file-title" className="mt-1 text-xl font-semibold text-ink">Gerenciar arquivo</h2></div><button disabled={managingFile} onClick={() => { setManagedFile(null); setManagedDocument(null); }} className="rounded-lg p-2 text-muted-foreground hover:bg-sage" aria-label="Fechar"><X size={18} /></button></div><div className="mt-5 rounded-md bg-paper p-4"><p className="font-medium text-ink">{managedFile.name}</p><p className="mt-1 text-sm leading-6 text-muted-foreground">As ações abaixo afetam somente a cópia indexada. O original não será apagado do Google Drive.</p></div>{managedReferences.length > 1 && <label className="mt-5 block text-sm font-medium text-ink">Espaço de conhecimento<select value={managedDocument.document_id} disabled={managingFile} onChange={(event) => setManagedDocument(managedReferences.find((item) => item.document_id === event.target.value) ?? null)} className="mt-2 w-full rounded-md border border-line bg-white px-3 py-2.5 text-sm"><option value="">Selecione um espaço</option>{managedReferences.map((reference) => <option key={reference.document_id} value={reference.document_id}>{contexts.find((item) => item.id === reference.workspace_folder_id)?.name ?? "Espaço sincronizado"}</option>)}</select></label>}<p className="mt-4 text-xs text-muted-foreground">{managedContext ? `Espaço selecionado: ${managedContext.name}` : "Espaço selecionado para esta cópia."}</p><div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end"><button disabled={managingFile} aria-busy={managingFile} onClick={() => { void removeManagedFile(); }} className="inline-flex items-center justify-center gap-2 rounded-md border border-rose-200 px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">{managingFileAction === "remove" ? <RefreshCw size={16} className="motion-safe:animate-spin" aria-hidden="true" /> : <Trash2 size={16} />}{managingFileAction === "remove" ? "Removendo…" : "Remover do índice"}</button><button disabled={managingFile} aria-busy={managingFile} onClick={() => { void reprocessManagedFile(); }} className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-forest-hover disabled:opacity-50"><RefreshCw size={16} className={managingFileAction === "reprocess" ? "motion-safe:animate-spin" : ""} aria-hidden="true" />{managingFileAction === "reprocess" ? "Reprocessando…" : "Reprocessar"}</button></div></section></div>}</>;
}

function SourceDocumentRow({ item, number }: { item: Evidence; number: number }) {
  return <li className="flex min-w-0 items-center gap-2 border-t border-line-soft py-2.5 first:border-t-0">
    <span className="w-5 shrink-0 text-right text-xs font-semibold text-primary">{number}.</span>
    <FileText size={15} className="shrink-0 text-primary" aria-hidden="true" />
    <span className="min-w-0 flex-1 break-words text-xs font-medium leading-5 text-ink">{item.document_name}</span>
    {item.source_provider && <span className="citation-tool mb-0 shrink-0">{toolLabel(item.source_provider)}</span>}
    {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer" aria-label={`Abrir ${item.document_name} no original`} title="Abrir original" className="shrink-0 rounded-md p-1.5 text-primary hover:bg-sage focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"><ExternalLink size={14} aria-hidden="true" /></a>}
  </li>;
}

function SourceDocuments({ items }: { items: Evidence[] }) {
  const [expanded, setExpanded] = useState(false);
  const remainingCount = Math.max(items.length - 3, 0);
  return <section className="mt-5 border-t border-line pt-4" aria-label="Documentos utilizados como fonte">
    <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">Documentos utilizados</h3>
    <ol>{items.slice(0, expanded ? undefined : 3).map((item, index) => <SourceDocumentRow key={citationSourceKey(item)} item={item} number={index + 1} />)}</ol>
    {remainingCount > 0 && <button type="button" onClick={() => setExpanded((open) => !open)} aria-expanded={expanded} className="flex items-center gap-1 border-t border-line-soft py-2 text-xs font-semibold text-primary hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">
      {expanded ? "Mostrar menos" : `Ver mais ${remainingCount} ${remainingCount === 1 ? "documento" : "documentos"}`}
      <ChevronRight size={14} className={`transition-transform ${expanded ? "-rotate-90" : "rotate-90"}`} aria-hidden="true" />
    </button>}
  </section>;
}

function TeamScreen({ company, setError, setNotice }: { company: Company; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [members, setMembers] = useState<Member[]>([]); const [email, setEmail] = useState(""); const [role, setRole] = useState<"admin" | "member">("member"); const [busy, setBusy] = useState(false);
  const load = useCallback(() => { if (company.role !== "owner") return; void api<Member[]>(`/organizations/${company.id}/members`).then(setMembers).catch((caught) => setError(messageFor(caught))); }, [company.id, company.role, setError]);
  useEffect(() => { load(); }, [load]);
  if (company.role !== "owner") return <Restricted title="Apenas o responsável gerencia a equipe" description="Administradores e membros podem usar pastas compartilhadas, mas não veem nem alteram membros ou convites." />;
  async function invite(event: FormEvent) { event.preventDefault(); setBusy(true); try { await api<{ status: string }>(`/organizations/${company.id}/members/invitations`, { method: "POST", body: JSON.stringify({ email, role }) }); setEmail(""); setNotice("Convite enviado."); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); } }
  async function change(member: Member, next: "admin" | "member") { try { await api<Member>(`/organizations/${company.id}/members/${member.id}`, { method: "PATCH", body: JSON.stringify({ role: next }) }); load(); } catch (caught) { setError(messageFor(caught)); } }
  async function remove(member: Member) { if (!window.confirm(`Remover ${member.email} da organização?`)) return; try { await api<void>(`/organizations/${company.id}/members/${member.id}`, { method: "DELETE" }); setMembers((items) => items.filter((item) => item.id !== member.id)); } catch (caught) { setError(messageFor(caught)); } }
  return <div className="grid gap-5 lg:grid-cols-[1fr_330px]"><section className="rounded-lg border bg-white p-6"><p className="text-sm font-semibold text-primary">Acesso da organização</p><h1 className="mt-1 text-2xl font-semibold">Equipe</h1><div className="mt-5 space-y-3">{members.map((member) => <div key={member.id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-4"><div><b className="text-sm">{member.email}</b><p className="mt-1 text-xs capitalize text-muted-foreground">{roleLabel(member.role)}</p></div>{member.role !== "owner" && <div className="flex items-center gap-2"><select value={member.role} onChange={(event) => { void change(member, event.target.value as "admin" | "member"); }} className="rounded-lg border px-2 py-1.5 text-sm"><option value="admin">Administrador</option><option value="member">Membro</option></select><button onClick={() => { void remove(member); }} className="rounded-lg p-2 text-rose-600 hover:bg-rose-50" aria-label={`Remover ${member.email}`}><Trash2 size={16} /></button></div>}</div>)}</div></section><form onSubmit={invite} className="h-fit rounded-lg border bg-white p-6"><h2 className="font-semibold">Convidar pessoa</h2><p className="mt-2 text-sm leading-6 text-muted-foreground">Responsáveis controlam o acesso. Administradores organizam fontes; membros pesquisam e perguntam.</p><input required value={email} onChange={(event) => setEmail(event.target.value)} type="email" placeholder="pessoa@empresa.com" className="mt-5 w-full rounded-md border px-3 py-2.5" /><select value={role} onChange={(event) => setRole(event.target.value as "admin" | "member")} className="mt-3 w-full rounded-md border px-3 py-2.5"><option value="member">Membro</option><option value="admin">Administrador</option></select><button disabled={busy} className="mt-4 w-full rounded-md bg-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">{busy ? "Enviando…" : "Enviar convite"}</button></form></div>;
}
function Restricted({ title, description }: { title: string; description: string }) { return <section className="max-w-xl rounded-lg border bg-white p-7"><ShieldCheck className="text-ink" /><h1 className="mt-4 text-2xl font-semibold">{title}</h1><p className="mt-3 leading-6 text-muted-foreground">{description}</p></section>; }

function IntegrationScreen({ company, setError, setNotice }: { company: Company; setError: (value: string | null) => void; setNotice: (value: string | null) => void }) {
  const [sources, setSources] = useState<Source[]>([]); const [sourcesLoading, setSourcesLoading] = useState(true); const [source, setSource] = useState<Source | null>(null); const [catalog, setCatalog] = useState<ScopeCatalog | null>(null); const [catalogError, setCatalogError] = useState<string | null>(null); const [workspaceFolders, setWorkspaceFolders] = useState<Folder[]>([]); const [foldersLoading, setFoldersLoading] = useState(true); const [selectedIds, setSelectedIds] = useState<string[]>([]); const [includeRoot, setIncludeRoot] = useState(false); const [mode, setMode] = useState<"selected" | "all_accessible">("selected"); const [uniform, setUniform] = useState(false); const [busy, setBusy] = useState(false); const [toolModalOpen, setToolModalOpen] = useState(false); const [disconnecting, setDisconnecting] = useState(false);
  const canManage = company.role !== "member";
  const toolName = source?.provider === "notion" ? "Notion" : source?.provider === "onedrive" ? "OneDrive" : "Google Drive";
  const hasSelectedScope = mode === "all_accessible" || selectedIds.length > 0 || includeRoot;
  const loadSources = useCallback(() => { if (!canManage) return; setSourcesLoading(true); void api<Source[]>(`/data-sources?organization_id=${company.id}`).then((items) => setSources(latestSourcePerProvider(items))).catch((caught) => setError(messageFor(caught))).finally(() => setSourcesLoading(false)); }, [canManage, company.id, setError]);
  const loadWorkspaceFolders = useCallback(() => { if (!canManage) return; setFoldersLoading(true); void api<Folder[]>(`/workspace-folders?organization_id=${company.id}`).then(setWorkspaceFolders).catch((caught) => setError(messageFor(caught))).finally(() => setFoldersLoading(false)); }, [canManage, company.id, setError]);
  useEffect(() => { void Promise.resolve().then(loadSources); }, [loadSources]);
  useEffect(() => { void Promise.resolve().then(loadWorkspaceFolders); }, [loadWorkspaceFolders]);
  useEffect(() => {
    if (!workspaceFolders.some((folder) => folder.status === "queued" || folder.status === "syncing")) return;
    const timer = window.setInterval(loadWorkspaceFolders, 5000);
    return () => window.clearInterval(timer);
  }, [workspaceFolders, loadWorkspaceFolders]);
  useEffect(() => {
    const connectedProvider = new URLSearchParams(window.location.search).get("connected");
    if (connectedProvider !== "notion" && connectedProvider !== "onedrive") return;
    void Promise.resolve().then(() => {
      setSourcesLoading(true);
      return api<Source[]>(`/data-sources?organization_id=${company.id}`).then((items) => {
        setSources(latestSourcePerProvider(items));
        const connectedSource = items.find((item) => item.provider === connectedProvider && item.status === "connected");
        if (connectedSource) void loadCatalog(connectedSource);
      }).catch((caught) => setError(messageFor(caught))).finally(() => setSourcesLoading(false));
    });
  }, [company.id, setError]);
  useEffect(() => { if (new URLSearchParams(window.location.search).get("connected") === "google_drive") void Promise.resolve().then(() => setToolModalOpen(true)); }, []);
  if (!canManage) return <Restricted title="Responsáveis e administradores conectam fontes" description="Membros podem consultar espaços já compartilhados, mas não conectam Drive nem iniciam sincronizações." />;
  function connect(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/google/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  function connectNotion(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/notion/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  function connectOneDrive(sourceId?: string) { const reauth = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ""; window.location.assign(`${API_BASE}/data-sources/onedrive/oauth/start?organization_id=${encodeURIComponent(company.id)}${reauth}`); }
  async function loadCatalog(selected: Source) { if (selected.status === "reauth_required") return; const selectedName = selected.provider === "notion" ? "Notion" : selected.provider === "onedrive" ? "OneDrive" : "Google Drive"; setSource(selected); setCatalog(null); setCatalogError(null); setSelectedIds([]); setIncludeRoot(false); setMode("selected"); setUniform(false); setToolModalOpen(true); try { setCatalog(await api<ScopeCatalog>(`/data-sources/${selected.id}/scope-catalog?organization_id=${company.id}`)); loadWorkspaceFolders(); } catch (caught) { setCatalogError(messageFor(caught)); if (caught instanceof ApiError && (caught.status === 409 || caught.status === 403)) { setSources((items) => items.map((item) => item.id === selected.id ? { ...item, status: "reauth_required" } : item)); setSource({ ...selected, status: "reauth_required" }); setError(`${selectedName} precisa ser reconectado para consultar as pastas disponíveis.`); } else setError(messageFor(caught)); } }
  function toggleFolder(id: string) { setMode("selected"); setSelectedIds((ids) => ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id]); }
  async function selectAndSync() { if (!source || !uniform || !hasSelectedScope) return; setBusy(true); try { const folder = await api<{ id: string }>(`/workspace-folders/selections?organization_id=${company.id}`, { method: "POST", body: JSON.stringify({ source_id: source.id, mode, folder_ids: mode === "selected" ? selectedIds : [], include_root_files: mode === "selected" && includeRoot, uniform_access_confirmed: true }) }); await api<{ job_id: string; status: string }>(`/workspace-folders/${folder.id}/sync?organization_id=${company.id}`, { method: "POST" }); await Promise.resolve(loadWorkspaceFolders()); setNotice("Sincronização iniciada. O conteúdo será indexado somente dentro deste espaço de conhecimento."); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); } }
  async function resyncFolder(folder: Folder) { setBusy(true); setError(null); try { await api<{ job_id: string; status: string }>(`/workspace-folders/${folder.id}/sync?organization_id=${company.id}`, { method: "POST" }); setNotice(`Re-sync de “${folder.name}” iniciado.`); loadWorkspaceFolders(); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(false); } }
  async function disconnect(selected: Source) { const selectedName = selected.provider === "notion" ? "Notion" : selected.provider === "onedrive" ? "OneDrive" : "Google Drive"; if (!window.confirm(`Desconectar ${selectedName}? Os espaços já indexados continuarão disponíveis, mas novas sincronizações serão bloqueadas.`)) return; setDisconnecting(true); try { await api<void>(`/data-sources/${selected.id}?organization_id=${company.id}`, { method: "DELETE" }); setSource(null); setCatalog(null); setToolModalOpen(false); await Promise.resolve(loadSources()); setNotice(`${selectedName} desconectado. Você pode autorizar novamente quando quiser.`); } catch (caught) { setError(messageFor(caught)); } finally { setDisconnecting(false); } }
  const syncedForSource = workspaceFolders.filter((folder) => folder.source_id === source?.id);
  const syncedFolderIds = new Set(syncedForSource.flatMap((folder) => folder.selection_folder_ids ?? []));
  const availableFolders = catalog?.folders.filter((folder) => !syncedFolderIds.has(folder.id)) ?? [];
  const closeTool = () => { setToolModalOpen(false); setSource(null); setCatalog(null); setCatalogError(null); };
  return <><IntegrationCatalog sources={sources} sourcesLoading={sourcesLoading} modalOpen={toolModalOpen && !source} onOpen={() => setToolModalOpen(true)} onClose={() => setToolModalOpen(false)} onConnect={connect} onConnectNotion={connectNotion} onConnectOneDrive={connectOneDrive} onManage={(selected) => { void loadCatalog(selected); }} onDisconnect={disconnect} disconnecting={disconnecting} />
    {source && toolModalOpen && <div role="dialog" aria-modal="true" aria-labelledby="sync-tool-title" className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4"><section className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-lg bg-white p-6 shadow-2xl"><div className="flex items-start gap-4"><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-primary">Integração ativa</p><h2 id="sync-tool-title" className="mt-1 text-2xl font-semibold text-ink">{toolName}</h2><p className="mt-1 text-sm text-muted-foreground">Confira a conexão, veja o que já está sincronizado e adicione novos espaços.</p></div><button onClick={closeTool} aria-label="Fechar" className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><X size={18} /></button></div>
      <div className={`mt-5 rounded-lg border p-4 ${source.status === "connected" ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Estado da conexão</p><p className="mt-1 font-semibold text-ink">{source.status === "connected" ? "Conexão ativa" : "Reconexão necessária"}</p>{source.account_email && <p className="mt-1 text-sm text-muted-foreground">{source.account_email}</p>}</div>{source.status !== "connected" && <button onClick={() => (source.provider === "notion" ? connectNotion : source.provider === "onedrive" ? connectOneDrive : connect)(source.id)} className="rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white">Reconectar {source.provider === "onedrive" ? "OneDrive" : source.provider === "notion" ? "Notion" : "Google Drive"}</button>}</div></div>
      {catalog && <><section className="mt-6"><div className="flex items-end justify-between gap-3"><div><h3 className="font-semibold text-ink">Já sincronizado</h3><p className="mt-1 text-sm text-muted-foreground">Esses espaços já fazem parte da base e podem ser atualizados.</p></div><span className="rounded-full bg-sage px-2.5 py-1 text-xs font-semibold text-muted-foreground">{syncedForSource.length} {syncedForSource.length === 1 ? "espaço" : "espaços"}</span></div>{foldersLoading && workspaceFolders.length === 0 ? <LoadingIndicator label="Carregando espaços sincronizados…" className="mt-3 rounded-md border border-dashed border-line p-4 text-sm text-muted-foreground" /> : syncedForSource.length === 0 ? <p className="mt-3 rounded-md border border-dashed border-line p-4 text-sm text-muted-foreground">Nenhuma pasta foi sincronizada ainda.</p> : <div className="mt-3 space-y-2">{syncedForSource.map((folder) => <div key={folder.id} className="flex flex-wrap items-center gap-3 rounded-md border border-emerald-200 bg-emerald-50/50 p-3"><span className="grid size-8 place-items-center rounded-md bg-white text-emerald-700"><FolderOpen size={16} /></span><div className="min-w-0 flex-1"><b className="block truncate text-sm text-ink">{folder.name}</b><p className="mt-0.5 text-xs text-muted-foreground">{folder.last_synced_at ? `Última sincronização: ${new Date(folder.last_synced_at).toLocaleString("pt-BR")}` : "Ainda não sincronizado"} · {(folder.status === "queued" || folder.status === "syncing") && <RefreshCw size={11} className="inline motion-safe:animate-spin" aria-hidden="true" />} {statusLabel(folder.status)}</p></div><button disabled={busy} onClick={() => { void resyncFolder(folder); }} className="inline-flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-2 text-xs font-semibold text-ink disabled:opacity-50"><RefreshCw size={14} />Re-sync</button></div>)}</div>}</section>
      <section className="mt-7 border-t border-line pt-5"><h3 className="font-semibold text-ink">Sincronizar novo espaço</h3><p className="mt-1 text-sm text-muted-foreground">Selecione uma ou mais pastas ainda não sincronizadas ou escolha todo o conteúdo acessível.</p>{availableFolders.length === 0 && mode === "selected" ? <p className="mt-3 rounded-md border border-dashed border-line p-4 text-sm text-muted-foreground">Todas as pastas disponíveis já estão sincronizadas.</p> : <div className="mt-3 grid gap-2 sm:grid-cols-2">{availableFolders.map((item) => <label key={item.id} className={`cursor-pointer rounded-md border p-3 text-left ${mode === "selected" && selectedIds.includes(item.id) ? "border-primary bg-sage" : ""}`}><input type="checkbox" checked={mode === "selected" && selectedIds.includes(item.id)} onChange={() => toggleFolder(item.id)} className="mr-2" /><FolderOpen size={16} className="mr-2 inline text-primary" />{item.name}</label>)}</div>}{catalog.root_files.available && <label className={`mt-3 flex cursor-pointer gap-3 rounded-md border p-3 text-sm ${mode === "selected" && includeRoot ? "border-primary bg-sage" : ""}`}><input type="checkbox" checked={mode === "selected" && includeRoot} onChange={(event) => { setMode("selected"); setIncludeRoot(event.target.checked); }} className="mt-1" /><span><b>{catalog.root_files.label}</b><span className="mt-1 block text-muted-foreground">Inclui arquivos soltos na raiz.</span></span></label>}<label className={`mt-3 flex cursor-pointer gap-3 rounded-md border border-amber-200 p-3 text-sm ${mode === "all_accessible" ? "bg-amber-50" : ""}`}><input type="radio" name="integration-scope" checked={mode === "all_accessible"} onChange={() => { setMode("all_accessible"); setSelectedIds([]); setIncludeRoot(false); }} className="mt-1" /><span><b>{catalog.all_accessible.label}</b><span className="mt-1 block text-amber-900">Inclui tudo que esta conexão permite ler.</span></span></label>{hasSelectedScope && <label className="mt-4 flex gap-3 rounded-md bg-amber-50 p-3 text-sm leading-6 text-amber-950"><input type="checkbox" checked={uniform} onChange={(event) => setUniform(event.target.checked)} className="mt-1" />Confirmo que todos os membros desta organização podem consultar este conteúdo.</label>}<button disabled={!hasSelectedScope || !uniform || busy} onClick={() => { void selectAndSync(); }} className="mt-4 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40">{busy && <RefreshCw size={15} className="mr-2 inline motion-safe:animate-spin" aria-hidden="true" />}{busy ? "Sincronizando…" : "Sincronizar selecionados"}</button></section></>}
      {!catalog && (catalogError ? <div role="alert" className="mt-6 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{catalogError}<button onClick={() => { if (source) void loadCatalog(source); }} className="ml-2 font-semibold underline">Tentar novamente</button></div> : <LoadingIndicator label="Validando a conexão e carregando as pastas disponíveis…" className="mt-6 text-sm text-muted-foreground" />)}
    </section></div>}
  </>;
}

type ToolsCatalogProps = { sources: Source[]; sourcesLoading: boolean; modalOpen: boolean; onOpen: () => void; onClose: () => void; onConnect: (sourceId?: string) => void; onConnectNotion: (sourceId?: string) => void; onConnectOneDrive: (sourceId?: string) => void; onManage: (source: Source) => void; onDisconnect: (source: Source) => void; disconnecting: boolean };

function IntegrationCatalog(props: ToolsCatalogProps) {
  if (props.sourcesLoading) return <div className="integration-catalog"><div className="integration-catalog-heading"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Fontes de conhecimento</h1><LoadingIndicator label="Carregando fontes conectadas…" className="mt-4 text-sm text-muted-foreground" /></div></div>;
  const serviceIcon = (name: string) => ({ OneDrive: "https://api.iconify.design/logos:microsoft-onedrive.svg", "GitHub Markdown": "https://api.iconify.design/logos:github-icon.svg", Notion: "https://api.iconify.design/logos:notion-icon.svg", "Slack e Microsoft Teams": "https://api.iconify.design/logos:slack-icon.svg" })[name];
  const comingSoon = (name: string, description: string, onConnect?: () => void) => <div className="integration-tool-card flex h-full flex-col rounded-lg border border-dashed border-line bg-white p-4"><div className="flex items-center gap-3"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><img src={serviceIcon(name)} alt="" className="size-6" /></span><b className="text-sm">{name}</b></div><span className="mt-3 block text-xs leading-5 text-muted-foreground">{description}</span>{onConnect ? <button onClick={onConnect} className="mt-auto w-fit rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Conectar Notion</button> : <span className="mt-auto inline-flex w-fit rounded-full bg-paper px-2.5 py-1 text-xs font-semibold text-muted-foreground">Em breve</span>}</div>;
  const notion = props.sources.find((source) => source.provider === "notion");
  const oneDrive = props.sources.find((source) => source.provider === "onedrive");
  const notionConnected = notion?.status === "connected";
  const notionStatus = notion ? statusLabel(notion.status) : "Disponível";
  const notionAccount = notion?.account_email ?? notion?.connected_by_email;
  const manageNotion = () => { if (notion?.status === "connected") props.onManage(notion); else props.onConnectNotion(notion?.id); };
  const notionAction = notionConnected ? "Gerenciar" : notion?.status === "reauth_required" ? "Reconectar" : "Conectar Notion";
  const notionCard = <section className="integration-tool-card h-full rounded-lg border border-primary bg-white p-4 shadow-sm"><button onClick={manageNotion} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><img src={serviceIcon("Notion")} alt="" className="size-6" /></span><span className="min-w-0 flex-1"><b className="block text-sm">Notion</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Confira a conexão, sincronize páginas e faça re-sync dos espaços existentes.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 text-xs"><span className={`size-2 rounded-full ${notionConnected ? "bg-emerald-500" : notion?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} /><span className="font-medium text-muted-foreground">{notionStatus}</span>{notionAccount && <span className="truncate text-muted-foreground">· {notionAccount}</span>}<span className="ml-auto"><button onClick={manageNotion} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">{notionAction}</button></span></div></section>;
  const googleConnected = props.sources.some((source) => source.provider === "google_drive" && (source.status === "connected" || source.status === "reauth_required"));
  const oneDriveConnected = Boolean(oneDrive && (oneDrive.status === "connected" || oneDrive.status === "reauth_required"));
  const notionIsConnected = Boolean(notion && (notion.status === "connected" || notion.status === "reauth_required"));
  const oneDriveAccount = oneDrive?.account_email ?? oneDrive?.connected_by_email;
  const oneDriveManage = () => { if (oneDrive?.status === "connected") props.onManage(oneDrive); else props.onConnectOneDrive(oneDrive?.id); };
  const oneDriveAction = oneDrive?.status === "connected" ? "Gerenciar" : oneDrive?.status === "reauth_required" ? "Reconectar" : oneDrive?.status === "disconnected" ? "Reconectar" : "Conectar OneDrive";
  const oneDriveCard = <section className="integration-tool-card h-full rounded-lg border border-primary bg-white p-4 shadow-sm"><button onClick={oneDriveManage} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 shrink-0 place-items-center rounded-lg bg-paper"><img src={serviceIcon("OneDrive")} alt="" className="size-6" /></span><span className="min-w-0 flex-1"><b className="block text-sm">OneDrive</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Conecte uma conta Microsoft pessoal, corporativa ou escolar, escolha pastas e sincronize os arquivos.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 text-xs"><span className={`size-2 rounded-full ${oneDrive?.status === "connected" ? "bg-emerald-500" : oneDrive?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} /><span className="font-medium text-muted-foreground">{oneDrive ? statusLabel(oneDrive.status) : "Disponível"}</span>{oneDriveAccount && <span className="truncate text-muted-foreground">· {oneDriveAccount}</span>}<span className="ml-auto flex items-center gap-2">{oneDrive && oneDrive.status !== "disconnected" && <button onClick={() => props.onDisconnect(oneDrive)} disabled={props.disconnecting} className="rounded-md px-2 py-2 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50">Desconectar</button>}<button onClick={oneDriveManage} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">{oneDriveAction}</button></span></div></section>;
  const category = (name: ToolCategory, description: string, children: ReactNode) => <section className="mt-5"><h2 className="text-lg font-semibold text-ink">{name}</h2><p className="mt-1 text-sm text-muted-foreground">{description}</p><div className="integration-tool-grid mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">{children}</div></section>;
  return <div className="integration-catalog"><div className="integration-catalog-heading"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Fontes de conhecimento</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">Conecte ferramentas que alimentam a base de conhecimento da sua organização.</p></div>{(googleConnected || oneDriveConnected || notionIsConnected) && category("Conectadas", "Gerencie as ferramentas que já fazem parte da base de conhecimento.", <>{googleConnected && <ToolsCatalog {...props} />}{oneDriveConnected && oneDriveCard}{notionIsConnected && notionCard}</>)}{category("Arquivos", "Armazene e sincronize documentos e pastas da equipe.", <>{!googleConnected && <ToolsCatalog {...props} />}{!oneDriveConnected && oneDriveCard}</>)}{category("Documentação", "Centralize documentação técnica e conhecimento estruturado.", <>{comingSoon("GitHub Markdown", "Indexe README, docs e arquivos Markdown versionados por repositório.")}{!notionIsConnected && notionCard}</>)}{category("Comunicação", "Pesquise decisões e conversas relevantes da equipe.", comingSoon("Slack e Microsoft Teams", "Integrações de comunicação serão adicionadas depois das fontes documentais."))}</div>;
}

function ToolsCatalog({ sources, modalOpen, onOpen, onClose, onConnect, onManage, onDisconnect, disconnecting }: ToolsCatalogProps) {
  const googleSources = sources.filter((source) => source.provider === "google_drive");
  const primary = googleSources.find((source) => source.status === "connected" || source.status === "reauth_required") ?? googleSources[0] ?? null;
  const connected = primary?.status === "connected";
  const statusLabel = primary?.status === "reauth_required" ? "Reconexão necessária" : primary?.status === "disconnected" ? "Desconectado" : connected ? "Conectado" : "Disponível";
  return <div className="max-w-4xl"><p className="text-sm font-semibold text-primary">Integrações da organização</p><h1 className="mt-1 text-3xl font-semibold tracking-tight">Integrações</h1><p className="mt-2 max-w-2xl leading-6 text-muted-foreground">Conecte ferramentas e mantenha os espaços sincronizados em um único fluxo.</p><section className="integration-tool-card mt-7 h-full max-w-xl rounded-lg border bg-white p-4 shadow-sm"><button onClick={onOpen} className="flex w-full items-center gap-3 text-left"><span className="grid size-10 place-items-center rounded-lg bg-sage text-primary"><HardDrive size={20} /></span><span className="min-w-0 flex-1"><b className="block text-sm">Google Drive</b><span className="mt-1 block text-xs leading-5 text-muted-foreground">Confira a conexão, adicione pastas e faça re-sync dos espaços existentes.</span></span><ChevronRight className="text-muted-foreground" size={18} /></button><div className="mt-3 flex flex-wrap items-center gap-2 border-t pt-3 text-xs"><span className={`size-2 rounded-full ${connected ? "bg-emerald-500" : primary?.status === "reauth_required" ? "bg-amber-500" : "bg-slate-300"}`} /><span className="font-medium text-muted-foreground">{statusLabel}</span>{primary?.account_email && <span className="truncate text-muted-foreground">· {primary.account_email}</span>}<span className="ml-auto">{connected ? <button onClick={() => primary && onManage(primary)} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Gerenciar</button> : primary?.status === "reauth_required" ? <button onClick={() => onConnect(primary.id)} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Reconectar</button> : <button onClick={() => onConnect()} className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-white">Conectar</button>}</span></div></section>{modalOpen && <div role="dialog" aria-modal="true" aria-labelledby="google-drive-modal-title" className="fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4"><section className="w-full max-w-lg rounded-md bg-white p-6 shadow-2xl"><div className="flex items-start gap-4"><span className="grid size-11 place-items-center rounded-lg bg-sage text-primary"><HardDrive size={21} /></span><div className="min-w-0 flex-1"><p className="text-sm font-semibold text-primary">Integração</p><h2 id="google-drive-modal-title" className="mt-1 text-xl font-semibold">Google Drive</h2></div><button onClick={onClose} aria-label="Fechar" className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><X size={18} /></button></div>{primary ? <div className="mt-6 rounded-lg border bg-paper p-4"><p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Conta autorizada</p><p className="mt-2 break-all font-medium text-ink">{primary.account_email ?? "Conta Google sem identificação disponível"}</p><p className="mt-1 text-sm text-muted-foreground">{statusLabel}. {primary.status === "reauth_required" ? "Autorize novamente para retomar sincronizações." : primary.status === "disconnected" ? "Autorize uma conta para retomar sincronizações." : "Esta conexão tem acesso somente leitura."}</p></div> : <div className="mt-6 rounded-lg border bg-paper p-4"><p className="font-medium">Nenhuma conta conectada</p><p className="mt-1 text-sm text-muted-foreground">Autorize uma conta Google para escolher pastas e sincronizar documentos.</p></div>}<div className="mt-6 flex flex-wrap justify-end gap-3">{primary?.status === "connected" && <button onClick={() => onManage(primary)} className="rounded-md border border-line px-4 py-2.5 text-sm font-semibold text-ink hover:bg-paper">Gerenciar</button>}<button onClick={() => onConnect(primary?.id)} className="rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-white hover:bg-forest-hover">{primary ? "Reconectar" : "Conectar Google Drive"}</button>{primary && primary.status !== "disconnected" && <button disabled={disconnecting} onClick={() => onDisconnect(primary)} className="inline-flex items-center gap-2 rounded-md px-4 py-2.5 text-sm font-semibold text-rose-700 hover:bg-rose-50 disabled:opacity-50"><Unplug size={16} />{disconnecting ? "Desconectando…" : "Desconectar"}</button>}</div><p className="mt-5 text-xs leading-5 text-muted-foreground">Desconectar remove a autorização salva neste produto e bloqueia novas sincronizações. Os dados já indexados não são apagados.</p></section></div>}</div>;
}

function StaffCenter({ user, onBack }: { user: User; onBack: () => void }) {
  const [companies, setCompanies] = useState<StaffCompany[]>([]); const [overview, setOverview] = useState<StaffOverview | null>(null); const [error, setError] = useState<string | null>(null); const [loading, setLoading] = useState(true);
  useEffect(() => { if (!user.is_platform_staff) return; void api<StaffCompany[]>("/platform/companies").then(setCompanies).catch((caught) => setError(messageFor(caught))).finally(() => setLoading(false)); }, [user.is_platform_staff]);
  async function open(company: StaffCompany) { try { setOverview(await api<StaffOverview>(`/platform/companies/${company.organization_id}/overview`)); } catch (caught) { setError(messageFor(caught)); } }
  if (!user.is_platform_staff) return <main className="auth-page"><section className="max-w-md text-center"><ShieldCheck className="mx-auto text-muted-foreground" /><h1 className="mt-4 text-2xl font-semibold">Área de suporte indisponível</h1><p className="mt-3 text-muted-foreground">Seu usuário não tem papel global de staff.</p><button onClick={onBack} className="mt-5 rounded-md bg-white px-4 py-2 text-sm font-semibold text-ink">Voltar</button></section></main>;
  return <main className="staff-app min-h-screen bg-violet-50 text-ink"><header className="border-b border-violet-200 bg-white"><div className="mx-auto flex max-w-6xl items-center gap-3 px-5 py-4"><ShieldCheck className="text-violet-700" /><div><b>Modo suporte</b><p className="text-xs text-muted-foreground">Metadados somente; conteúdo de cliente permanece inacessível.</p></div><button onClick={onBack} className="ml-auto rounded-lg border px-3 py-2 text-sm">Voltar ao produto</button></div></header><div className="mx-auto grid max-w-6xl gap-5 p-5 lg:grid-cols-[330px_1fr]"><aside className="rounded-lg border border-violet-100 bg-white p-4"><h1 className="font-semibold">Organizações</h1>{loading && <p className="mt-4 text-sm text-muted-foreground">Carregando organizações…</p>}{error && <p className="mt-4 text-sm text-rose-700">{error}</p>}{companies.length > 0 && <select aria-label="Organização em suporte" defaultValue="" onChange={(event) => { const company = companies.find((item) => item.organization_id === event.target.value); if (company) void open(company); }} className="mt-4 w-full rounded-md border border-violet-200 bg-white px-3 py-2 text-sm font-semibold"><option value="">Selecione uma organização</option>{companies.map((company) => <option key={company.organization_id} value={company.organization_id}>{company.name}</option>)}</select>}</aside><section>{overview ? <StaffOverviewCard overview={overview} /> : <div className="rounded-lg border border-dashed border-violet-200 bg-white p-8 text-muted-foreground">Selecione uma organização para consultar o estado operacional. Esta área não oferece busca, documentos, links de fonte, perguntas, consultas salvas ou ações de Drive.</div>}</section></div></main>;
}
function StaffOverviewCard({ overview }: { overview: StaffOverview }) { return <section><div className="rounded-lg border border-violet-300 bg-violet-100 p-5 text-violet-950"><b>Acesso global de suporte</b><p className="mt-1 text-sm">Metadados operacionais somente; conteúdo de cliente permanece inacessível.</p></div><div className="mt-5 rounded-lg border bg-white p-6"><h1 className="text-xl font-semibold">Visão operacional</h1><p className="mt-2 text-sm text-muted-foreground">Somente estado de pastas e resumo agregado de códigos seguros de falha.</p><div className="mt-5 space-y-3">{overview.folders.map((folder) => <div key={folder.id} className="rounded-md border p-4"><b>{folder.name}</b><span className="ml-2 text-xs capitalize text-muted-foreground">{folder.status.replaceAll("_", " ")}</span>{folder.failure_summary.map((failure) => <p key={failure.error_code} className="mt-2 text-xs text-rose-700">{failure.count} falha(s): {failure.error_code}</p>)}</div>)}</div></div></section>; }
