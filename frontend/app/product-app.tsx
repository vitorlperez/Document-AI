"use client";

import { CircleAlert, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { OrganizationOnboarding, type OnboardingState } from "./organization-onboarding";
import { DeveloperScreen } from "./product/developer-screen";
import { LandingPage } from "./landing-page";
import { Brand } from "./brand";
import { hostedLoginQuery, safeInvitationReturnTo } from "./product/auth-navigation.mjs";
import { oauthErrorMessage } from "./provider-labels";
import { API_BASE, SESSION_PATH, type Screen, type Company, type User, ApiError, api, isUuid, isInvitationToken, messageFor, companyPath } from "./product/types-and-api";
import { OrganizationPicker } from "./product/org-picker";
import { writeActiveOrganizationId } from "./product/active-organization";
import { Loading, SignIn, InvitationAcceptance, Onboarding, InvalidCompany } from "./product/auth-screens";
import { NotificationToast, Shell, type ToastAction } from "./product/shell";
import { CompanyDashboard } from "./product/chat-workspace";
import { LibraryScreen } from "./product/library-screen";
import { IntegrationScreen } from "./product/integrations-screen";
import { TeamScreen, StaffCenter } from "./product/team-staff";
import "./chat-workspace.css";
import "./product-layout.css";
import "./integration-cards.css";

const PENDING_NOTICE_KEY = "arquivio:pending-notice";

export function ProductApp({ screen }: { screen: Screen }) {
  const router = useRouter(); const pathname = usePathname(); const searchParams = useSearchParams(); const params = useParams<{ companyId?: string; token?: string }>();
  const [resetToken] = useState(() => pathname === "/login" ? searchParams.get("token") ?? undefined : undefined);
  const loginReturnTo = safeInvitationReturnTo(screen === "invitation" && isInvitationToken(params.token) ? pathname : searchParams.get("return_to"));
  useEffect(() => {
    if (!resetToken) return;
    const url = new URL(window.location.href);
    url.searchParams.delete("token");
    window.history.replaceState(window.history.state, "", url.pathname + url.search);
  }, [resetToken]);
  const [onboarding, setOnboarding] = useState<(OnboardingState & { organizationId: string }) | null>(null);
  const [user, setUser] = useState<User | null>(null); const [companies, setCompanies] = useState<Company[]>([]); const [loading, setLoading] = useState(true); const [notice, setNotice] = useState<string | null>(null); const [noticeAction, setNoticeAction] = useState<ToastAction | null>(null); const [error, setError] = useState<string | null>(null);
  const sessionRequest = useRef<AbortController | null>(null);
  const loadSession = useCallback(async (background = false) => {
    sessionRequest.current?.abort();
    const controller = new AbortController();
    sessionRequest.current = controller;
    const options = { signal: controller.signal, cache: "no-store" as const };
    if (!background) { setLoading(true); setError(null); setOnboarding(null); }
    try {
      const current = await api<User | null>(SESSION_PATH, options);
      if (controller.signal.aborted) return;
      setUser(current);
      if (!current) { setCompanies([]); return; }
      const memberships = await api<Company[]>("/organizations", options);
      if (controller.signal.aborted) return;
      setCompanies(memberships);
      if (params.companyId && memberships.some((item) => item.id === params.companyId)) {
        const progress = await api<OnboardingState>(`/organizations/${params.companyId}/onboarding`, options);
        if (controller.signal.aborted) return;
        setOnboarding({ ...progress, organizationId: params.companyId });
      }
      if (screen === "home" && memberships.length === 1 && !resetToken) router.replace(companyPath(memberships[0].id));
    } catch (caught) {
      if (!controller.signal.aborted && !(caught instanceof ApiError && caught.status === 401) && !background) setError(messageFor(caught));
    } finally { if (!controller.signal.aborted && !background) setLoading(false); }
  }, [router, screen, params.companyId, resetToken]);
  useEffect(() => {
    let mounted = true;
    void Promise.resolve().then(() => { if (mounted) void loadSession(); });
    return () => { mounted = false; sessionRequest.current?.abort(); };
  }, [loadSession]);
  useEffect(() => {
    if (!onboarding?.required) return;
    const refresh = () => { void loadSession(true); };
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [loadSession, onboarding?.required]);
  const oauthProvider = screen === "integrations" ? searchParams.get("connected") : null;
  const oauthError = screen === "integrations" ? searchParams.get("error") : null;
  const oauthFailure = oauthErrorMessage(oauthError);
  const oauthNotice = oauthProvider === "google_drive" ? "Google Drive conectado. Abra a ferramenta para definir o escopo e iniciar uma sincronização." : oauthProvider === "onedrive" ? "OneDrive conectado. Escolha as pastas que sua equipe pode consultar e inicie a sincronização." : oauthProvider === "sharepoint" ? "SharePoint conectado. Escolha as bibliotecas que sua equipe pode consultar e inicie a sincronização." : null;
  // A notice handed over by the previous screen (the route change remounts this component, so state alone would be lost).
  useEffect(() => {
    try {
      const raw = window.sessionStorage.getItem(PENDING_NOTICE_KEY);
      if (!raw) return;
      window.sessionStorage.removeItem(PENDING_NOTICE_KEY);
      const pending = JSON.parse(raw) as { message?: string; action?: ToastAction };
      if (pending.message) queueMicrotask(() => { setNotice(pending.message!); setNoticeAction(pending.action ?? null); });
    } catch { /* ignore malformed or unavailable storage */ }
  }, []);
  const dismissAlert = useCallback(() => { setNotice(null); setNoticeAction(null); setError(null); if (oauthNotice || oauthFailure) router.replace(pathname); }, [oauthFailure, oauthNotice, pathname, router]);
  const alertMessage = error ?? notice ?? oauthFailure ?? oauthNotice;
  useEffect(() => {
    if (!alertMessage || error) return;
    const timeout = window.setTimeout(dismissAlert, 6000);
    return () => window.clearTimeout(timeout);
  }, [alertMessage, dismissAlert, error]);
  const company = useMemo(() => companies.find((item) => item.id === params.companyId) ?? null, [companies, params.companyId]);
  const goCompany = (id: string) => { writeActiveOrganizationId(id); const suffix = pathname.endsWith("/team") ? "/team" : pathname.endsWith("/integrations") ? "/integrations" : pathname.endsWith("/library") ? "/library" : pathname.endsWith("/developer") ? "/developer" : ""; router.push(companyPath(id, suffix)); };
  const beginLogin = (screenHint: "sign-in" | "sign-up") => { window.location.assign(`${API_BASE}/auth/login?${hostedLoginQuery(screenHint, loginReturnTo)}`); };
  const logout = async () => { try { const { redirect_url } = await api<{ redirect_url: string }>("/auth/logout", { method: "POST" }); setUser(null); setCompanies([]); window.location.replace(redirect_url); } catch (caught) { setError(messageFor(caught)); } };
  // Persist the active organization whenever one is resolved (deep link, picker or switcher).
  useEffect(() => { if (company) writeActiveOrganizationId(company.id); }, [company]);
  if (loading && screen === "home" && pathname === "/") return <LandingPage onLogin={() => router.push("/login")} onSignUp={() => router.push("/login?mode=sign-up")} />;
  if (loading) return <Loading />;
  if (!user || (pathname === "/login" && Boolean(resetToken))) return <>{screen === "home" && pathname === "/" ? <LandingPage onLogin={() => router.push("/login")} onSignUp={() => router.push("/login?mode=sign-up")} /> : <SignIn onLogin={() => beginLogin("sign-in")} passwordReset={searchParams.get("password_reset") === "1"} initialMode={searchParams.get("mode") === "sign-up" ? "sign-up" : "sign-in"} resetToken={resetToken} returnTo={loginReturnTo} />}{error && <div role="alert" className="session-error"><CircleAlert size={20} /><div><p>{error}</p><button onClick={() => { void loadSession(); }}>Tentar novamente</button></div></div>}</>;
  if (screen === "invitation") return <InvitationAcceptance token={params.token} onAccepted={(organizationId) => router.replace(companyPath(organizationId))} />;
  if (screen === "home" && companies.length === 1) return <Loading />;
  if (screen === "home" && companies.length > 1) return <OrganizationPicker user={user} companies={companies} onChoose={goCompany} onLogout={() => { void logout(); }} />;
  if (screen === "home") return <Onboarding user={user} onCreated={(created) => { setCompanies((items) => [...items, created]); router.push(companyPath(created.id)); }} />;
  if (screen === "staff") return <StaffCenter user={user} onBack={() => router.push(companies[0] ? companyPath(companies[0].id) : "/")} />;
  if (!isUuid(params.companyId) || !company) return <InvalidCompany companies={companies} onChoose={goCompany} />;
  if (!onboarding || onboarding.organizationId !== company.id) return <main className="auth-page"><section className="auth-card"><Brand /><p role="alert" className="mt-6">{error ?? "Preparando sua organização…"}</p><button onClick={() => { void loadSession(); }} className="onboarding-primary mt-4">Tentar novamente</button><button onClick={() => { void logout(); }} className="onboarding-text-button mt-4">Sair</button></section></main>;
  const advanceOnboarding = async (step: OnboardingState["step"]) => {
    try {
      const activeRequest = sessionRequest.current;
      const memberships = await api<Company[]>("/organizations", { cache: "no-store", signal: activeRequest?.signal });
      if (activeRequest?.signal.aborted) return;
      setCompanies(memberships);
      const currentMembership = memberships.find((item) => item.id === company.id);
      if (!currentMembership || currentMembership.role !== "owner") {
        await loadSession();
        throw new Error("Você não tem permissão para esta ação.");
      }
      const progress = await api<OnboardingState>(`/organizations/${company.id}/onboarding`, { method: "PATCH", body: JSON.stringify({ step }) });
      if (activeRequest?.signal.aborted) return;
      if (!progress.required) { setNotice(null); setError(null); }
      setOnboarding({ ...progress, organizationId: company.id });
      if (!progress.required) router.replace(companyPath(company.id));
    } catch (caught) { throw new Error(messageFor(caught)); }
  };
  if (onboarding.required && company.role === "owner") return <OrganizationOnboarding key={company.id} organizationId={company.id} name={company.name} state={onboarding} onLogout={() => { void logout(); }} alert={alertMessage ? <NotificationToast message={alertMessage} tone={error || oauthFailure ? "error" : "notice"} onDismiss={dismissAlert} /> : null} onAdvance={advanceOnboarding}><IntegrationScreen key={company.id} company={company} setError={setError} setNotice={setNotice} onboarding={{ onSyncStarted: () => advanceOnboarding("sync") }} /></OrganizationOnboarding>;
  return <Shell user={user} company={company} companies={companies} alertMessage={alertMessage} alertAction={notice && alertMessage === notice ? noticeAction : null} alertTone={error || oauthFailure ? "error" : "notice"} fillViewport={screen === "company" || screen === "library"} pageSurface={screen === "team" || screen === "integrations" || screen === "developer"} onDismiss={dismissAlert} onCompanyChange={goCompany} onNavigate={(path) => router.push(path)} onLogout={() => { void logout(); }}>
    {screen === "company" && <CompanyDashboard key={company.id} company={company} onboarding={onboarding} onOnboardingChange={(progress) => setOnboarding((current) => current?.organizationId === company.id ? { ...progress, organizationId: company.id } : current)} onConnect={() => router.push(companyPath(company.id, "/integrations"))} setError={setError} setNotice={setNotice} />}
    {screen === "library" && <LibraryScreen key={company.id} company={company} onConnect={() => router.push(companyPath(company.id, "/integrations"))} setError={setError} setNotice={setNotice} />}
    {screen === "team" && <TeamScreen key={company.id} company={company} setError={setError} setNotice={setNotice} />}
    {screen === "integrations" && (company.role === "member" ? <section role="alert" className="mx-auto max-w-lg rounded-lg border border-line bg-panel p-8 text-center"><ShieldCheck className="mx-auto text-primary" size={28} /><h1 className="mt-4 text-xl font-semibold text-ink">Acesso restrito</h1><p className="mt-2 text-sm text-muted-foreground">Somente responsáveis e administradores podem gerenciar integrações.</p><button onClick={() => router.push(companyPath(company.id))} className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">Voltar à conversa</button></section> : <div><IntegrationScreen key={company.id} company={company} setError={setError} setNotice={setNotice} onManualSyncStarted={(toolName) => { try { window.sessionStorage.setItem(PENDING_NOTICE_KEY, JSON.stringify({ message: `Sincronização do ${toolName} iniciada — ${window.matchMedia("(max-width: 767px)").matches ? "acompanhe pelo menu" : "acompanhe pelo ícone na barra lateral"}; detalhes na Biblioteca.`, action: { label: "Abrir Biblioteca", href: companyPath(company.id, "/library") } })); } catch { /* storage unavailable */ } router.push(companyPath(company.id)); }} /></div>)}
    {screen === "developer" && (company.role === "member" ? <section role="alert" className="mx-auto max-w-lg rounded-lg border border-line bg-panel p-8 text-center"><ShieldCheck className="mx-auto text-primary" size={28} /><h1 className="mt-4 text-xl font-semibold text-ink">Acesso restrito</h1><p className="mt-2 text-sm text-muted-foreground">Somente responsáveis e administradores podem gerenciar o acesso de desenvolvedor.</p><button onClick={() => router.push(companyPath(company.id))} className="mt-5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground">Voltar à conversa</button></section> : <DeveloperScreen key={company.id} company={company} />)}
  </Shell>;
}
