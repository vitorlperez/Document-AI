"use client";

import { Clock3, FolderOpen, HardDrive, ShieldCheck, Sparkles } from "lucide-react";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Toast, ToastViewport } from "../ui";
import { Brand } from "../brand";
import { ThemeToggle } from "../theme-toggle";
import { NotificationBell } from "./notification-bell";
import { AccountMenu } from "./account-menu";
import { MobileShellHeader, useIsMobileShell, useVisualViewportHeight } from "../mobile-nav";
import { type Company, type User, roleLabel, companyPath } from "./types-and-api";
import "./shell-motion.css";

export type ToastAction = { label: string; href: string };

type ToastContent = { message: string; tone: "notice" | "error"; action: ToastAction | null };

/**
 * Toast da casca (migrado para os primitives de motion). Aceita `message: null` para animar a saída:
 * guardamos o último conteúdo até a animação terminar. Erros não fecham sozinhos; avisos somem em 6 s.
 * O aviso entre telas segue vindo de `PENDING_NOTICE_KEY` (product-app) — nada aqui mexe nele.
 */
export function NotificationToast({ message, tone, onDismiss, action, onNavigate }: { message: string | null; tone: "notice" | "error"; onDismiss: () => void; action?: ToastAction | null; onNavigate?: (path: string) => void }) {
  const [last, setLast] = useState<ToastContent | null>(null);
  const current: ToastContent | null = message ? { message, tone, action: action ?? null } : null;
  if (current && (last?.message !== current.message || last.tone !== current.tone || last.action?.href !== current.action?.href)) setLast(current);
  const shown = current ?? last;
  const error = shown?.tone === "error";
  const link = shown?.action;
  return <ToastViewport>
    {shown && <Toast key={shown.message} open={Boolean(message)} tone={error ? "error" : "success"} title={shown.message} duration={error ? null : 6000} onDismiss={onDismiss} dismissLabel="Fechar aviso"
      action={link ? <a href={link.href} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return; onDismiss(); if (onNavigate) { event.preventDefault(); onNavigate(link.href); } }} className="shell-toast-action mo-focus">{link.label}</a> : undefined} />}
  </ToastViewport>;
}

/** Barra deslizante sob a aba ativa: só `transform` (translateX + scaleX), medida do <a> ativo. Lembra a aba anterior para deslizar entre rotas (o ProductApp remonta a cada navegação). */
const TAB_MEMORY_KEY = "arquivio:shell-tab";
function useTabIndicator(activeKey: string | null) {
  const nav = useRef<HTMLElement>(null);
  const indicator = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    const navEl = nav.current;
    const bar = indicator.current;
    if (!navEl || !bar) return;
    const place = (key: string | null, animate: boolean) => {
      const tab = key ? navEl.querySelector<HTMLElement>(`[data-tab="${key}"]`) : null;
      if (!tab) { bar.dataset.ready = "false"; return false; }
      bar.dataset.animate = animate ? "true" : "false";
      bar.style.setProperty("--tab-x", `${tab.offsetLeft}px`);
      bar.style.setProperty("--tab-w", String(tab.offsetWidth));
      bar.dataset.ready = "true";
      return true;
    };
    let previous: string | null = null;
    try { previous = window.sessionStorage.getItem(TAB_MEMORY_KEY); window.sessionStorage.removeItem(TAB_MEMORY_KEY); } catch { /* storage unavailable */ }
    const frame = { id: 0 };
    if (previous && previous !== activeKey && place(previous, false)) {
      void bar.offsetWidth;
      frame.id = window.requestAnimationFrame(() => place(activeKey, true));
    } else place(activeKey, false);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => place(activeKey, false));
    observer?.observe(navEl);
    return () => { window.cancelAnimationFrame(frame.id); observer?.disconnect(); if (activeKey) { try { window.sessionStorage.setItem(TAB_MEMORY_KEY, activeKey); } catch { /* storage unavailable */ } } };
  }, [activeKey]);
  return { nav, indicator };
}

export function Shell({ user, company, companies, children, alertMessage, alertTone, alertAction, fillViewport, pageSurface, onDismiss, onCompanyChange, onNavigate, onLogout }: { user: User; company: Company; companies: Company[]; children: ReactNode; alertMessage: string | null; alertTone: "notice" | "error"; alertAction?: ToastAction | null; fillViewport: boolean; pageSurface: boolean; onDismiss: () => void; onCompanyChange: (id: string) => void; onNavigate: (path: string) => void; onLogout: () => void }) {
  const pathname = usePathname();
  const chatScreen = !/\/(library|team|integrations|automations|developer|admin|profile)\/?$/.test(pathname ?? "");
  const mobile = useIsMobileShell();
  useVisualViewportHeight(mobile, Boolean(fillViewport));
  const canManage = company.role !== "member";
  const go = (suffix = "") => onNavigate(companyPath(company.id, suffix));
  const tabs = [
    { label: "Conversa", suffix: "", icon: Sparkles },
    { label: "Biblioteca", suffix: "/library", icon: FolderOpen },
    { label: "Automações", suffix: "/automations", icon: Clock3 },
    ...(canManage ? [{ label: "Integrações", suffix: "/integrations", icon: HardDrive }] : []),
  ];
  const activeTab = tabs.find((tab) => (tab.suffix === "" ? chatScreen : (pathname ?? "").replace(/\/$/, "").endsWith(tab.suffix)))?.suffix ?? null;
  const { nav: navRef, indicator: indicatorRef } = useTabIndicator(mobile ? null : activeTab === null ? null : activeTab || "chat");
  return <main data-mobile-shell={mobile ? "true" : undefined} className={`product-app ${fillViewport ? "flex h-dvh flex-col overflow-hidden" : "min-h-screen"} bg-paper text-ink`}>
    {mobile ? <MobileShellHeader user={user} company={company} companies={companies} screen={chatScreen ? "chat" : "other"} activePath={pathname ?? companyPath(company.id)} onCompanyChange={onCompanyChange} onNavigate={onNavigate} onLogout={onLogout} /> : <header className="product-header z-20 shrink-0 border-b border-line">
      <div className="product-header-inner mx-auto max-w-7xl px-4 py-4">
        <div className="product-header-start">
        <button onClick={() => go()} className="product-brand-button" aria-label="Arquivio, ir para a conversa"><Brand compact /></button>
        <span aria-label={`Organização ativa: ${company.name}`} title={company.name} className="organization-name max-w-36 truncate rounded-full border border-line bg-panel px-3 py-2 text-sm font-semibold min-[1100px]:max-w-52">{company.name}</span>
        <span className="hidden rounded-full bg-sage px-2.5 py-1 text-xs font-semibold capitalize text-muted-foreground min-[1440px]:inline">{roleLabel(company.role)}</span>
        </div>
        <nav ref={navRef} data-tour="navigation" aria-label="Navegação principal" className="primary-tabs">
          {tabs.map((tab) => { const Icon = tab.icon; const active = tab.suffix === "" ? chatScreen : (pathname ?? "").replace(/\/$/, "").endsWith(tab.suffix); return <a key={tab.label} href={companyPath(company.id, tab.suffix)} onClick={(event) => { if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return; event.preventDefault(); go(tab.suffix); }} aria-current={active ? "page" : undefined} aria-label={tab.label} title={tab.label} data-tab={tab.suffix || "chat"} className="primary-tab mo-interactive"><Icon size={17} aria-hidden="true" /><span className="primary-tab-label">{tab.label}</span></a>; })}
          <span ref={indicatorRef} aria-hidden="true" className="primary-tab-indicator" data-ready="false" />
        </nav>
        <div className="product-header-end">
          {user.is_platform_staff && <button onClick={() => onNavigate("/staff")} className="mo-interactive rounded-lg border border-line bg-panel px-3 py-2 text-xs font-semibold text-primary"><ShieldCheck className="mr-1 inline" size={14} />Suporte</button>}
          <NotificationBell key={company.id} company={company} /><ThemeToggle /><AccountMenu user={user} company={company} onNavigate={onNavigate} onLogout={onLogout} />
        </div>
      </div>
    </header>}
    <NotificationToast message={alertMessage} tone={alertTone} onDismiss={onDismiss} action={alertAction} onNavigate={onNavigate} />
    <div className={`product-content mx-auto w-full max-w-7xl p-4 ${fillViewport ? "min-h-0 flex-1" : ""}`}><section className={`min-w-0 ${fillViewport ? "workspace-shell h-full min-h-0" : ""} ${pageSurface ? "page-surface" : ""}`}>{children}</section></div>
  </main>;
}
