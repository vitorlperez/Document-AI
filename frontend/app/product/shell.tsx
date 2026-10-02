"use client";

import Link from "next/link";
import { ChevronRight, CircleAlert, CircleCheck, Code2, FolderOpen, HardDrive, LogOut, ShieldCheck, Sparkles, Users, X } from "lucide-react";
import { usePathname } from "next/navigation";
import { ReactNode, useEffect, useRef, useState } from "react";
import { Brand } from "../brand";
import { MobileShellHeader, useIsMobileShell, useVisualViewportHeight } from "../mobile-nav";
import { type Company, type User, roleLabel, companyPath } from "./types-and-api";

export type ToastAction = { label: string; href: string };

export function NotificationToast({ message, tone, onDismiss, action }: { message: string; tone: "notice" | "error"; onDismiss: () => void; action?: ToastAction | null }) {
  const error = tone === "error";
  return <div className="pointer-events-none fixed inset-x-4 top-20 z-[70] flex justify-end sm:inset-x-6" aria-live="polite">
    <div role={error ? "alert" : "status"} className={`pointer-events-auto w-full max-w-md overflow-hidden rounded-lg border bg-white shadow-xl ${error ? "border-rose-200" : "border-emerald-200"}`}>
      <div className="flex items-start gap-3 px-4 py-3.5">{error ? <CircleAlert className="mt-0.5 shrink-0 text-rose-600" size={18} aria-hidden="true" /> : <CircleCheck className="mt-0.5 shrink-0 text-emerald-600" size={18} aria-hidden="true" />}<p className={`min-w-0 flex-1 text-sm leading-5 ${error ? "text-rose-900" : "text-emerald-900"}`}>{message}{action && <> <Link href={action.href} onClick={onDismiss} className="font-semibold underline">{action.label}</Link></>}</p><button onClick={onDismiss} className="-mr-1 -mt-1 rounded-lg p-1.5 text-muted-foreground hover:bg-sage hover:text-ink" aria-label="Fechar aviso"><X size={16} /></button></div>
      {!error && <div key={message} className="h-1 origin-left animate-[toast-progress_6000ms_linear_forwards] bg-emerald-500" />}
    </div>
  </div>;
}

export function Shell({ user, company, companies, children, alertMessage, alertTone, alertAction, fillViewport, pageSurface, onDismiss, onCompanyChange, onNavigate, onLogout }: { user: User; company: Company; companies: Company[]; children: ReactNode; alertMessage: string | null; alertTone: "notice" | "error"; alertAction?: ToastAction | null; fillViewport: boolean; pageSurface: boolean; onDismiss: () => void; onCompanyChange: (id: string) => void; onNavigate: (path: string) => void; onLogout: () => void }) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const pathname = usePathname();
  const chatScreen = !/\/(library|team|integrations|developer)\/?$/.test(pathname ?? "");
  const mobile = useIsMobileShell();
  useVisualViewportHeight(mobile);
  useEffect(() => {
    if (!menuOpen) return;
    const close = (event: PointerEvent) => { if (!menuRef.current?.contains(event.target as Node)) setMenuOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setMenuOpen(false); menuRef.current?.querySelector("button")?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [menuOpen]);
  const canManage = company.role !== "member";
  const go = (suffix = "") => { setMenuOpen(false); onNavigate(companyPath(company.id, suffix)); };
  return <main data-mobile-shell={mobile ? "true" : undefined} className={`product-app ${fillViewport ? "flex h-dvh flex-col overflow-hidden" : "min-h-screen"} bg-paper text-ink`}>
    {mobile ? <MobileShellHeader user={user} company={company} companies={companies} screen={chatScreen ? "chat" : "other"} activePath={pathname ?? companyPath(company.id)} onCompanyChange={onCompanyChange} onNavigate={onNavigate} onLogout={onLogout} /> : <header className="product-header z-20 shrink-0 border-b border-line">
      <div className="product-header-inner mx-auto flex max-w-7xl items-center gap-3 px-4 py-4">
        <button onClick={() => go()} className="product-brand-button" aria-label="Arquivio, ir para consultas"><Brand compact /></button>
        <select aria-label="Organização ativa" value={company.id} onChange={(event) => onCompanyChange(event.target.value)} className="organization-select max-w-52 rounded-lg border border-line bg-white px-3 py-2 text-sm font-semibold">{companies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
        <span className="hidden rounded-full bg-sage px-2.5 py-1 text-xs font-semibold capitalize text-muted-foreground sm:inline">{roleLabel(company.role)}</span>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden text-sm text-muted-foreground md:block">{user.email}</span>
          {user.is_platform_staff && <button onClick={() => { setMenuOpen(false); onNavigate("/staff"); }} className="rounded-lg border border-violet-200 px-3 py-2 text-xs font-semibold text-violet-700"><ShieldCheck className="mr-1 inline" size={14} />Suporte</button>}
          <div ref={menuRef} className="relative">
            <button data-tour="navigation" onClick={() => setMenuOpen((open) => !open)} aria-expanded={menuOpen} aria-label="Navegar" aria-controls="product-navigation" className="inline-flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-2 text-sm font-semibold text-ink shadow-sm hover:bg-paper"><span>Navegar</span><ChevronRight size={16} className={`transition-transform ${menuOpen ? "rotate-90" : ""}`} /></button>
            {menuOpen && <nav id="product-navigation" aria-label="Navegação principal" className="absolute right-0 mt-2 w-60 overflow-hidden rounded-lg border border-line bg-white p-1.5 shadow-xl">
              <button onClick={() => go()} className="flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><Sparkles size={16} className="text-primary" /><span><span className="block">Consultas</span><span className="block text-xs font-normal text-muted-foreground">Voltar à conversa</span></span></button>
              <button onClick={() => go("/library")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><FolderOpen size={16} className="text-primary" /><span><span className="block">Biblioteca</span><span className="block text-xs font-normal text-muted-foreground">Explore e gerencie o índice</span></span></button>
              {company.role === "owner" && <button onClick={() => go("/team")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><Users size={16} className="text-primary" /><span><span className="block">Equipe</span><span className="block text-xs font-normal text-muted-foreground">Membros e convites</span></span></button>}
              {canManage && <button onClick={() => go("/integrations")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><HardDrive size={16} className="text-primary" /><span><span className="block">Integrações</span><span className="block text-xs font-normal text-muted-foreground">Fontes e sincronizações</span></span></button>}
              {canManage && <button onClick={() => go("/developer")} className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm font-semibold text-ink hover:bg-sage"><Code2 size={16} className="text-primary" /><span><span className="block">Desenvolvedor</span><span className="block text-xs font-normal text-muted-foreground">API e MCP</span></span></button>}
            </nav>}
          </div>
          <button onClick={onLogout} aria-label="Sair da conta" title="Sair" className="rounded-lg p-2 text-muted-foreground hover:bg-sage"><LogOut size={18} /></button>
        </div>
      </div>
    </header>}
    {alertMessage && <NotificationToast message={alertMessage} tone={alertTone} onDismiss={onDismiss} action={alertAction} />}
    <div className={`product-content mx-auto w-full max-w-7xl p-4 ${fillViewport ? "min-h-0 flex-1" : ""}`}><section className={`min-w-0 ${fillViewport ? "workspace-shell h-full min-h-0" : ""} ${pageSurface ? "page-surface" : ""}`}>{children}</section></div>
  </main>;
}
