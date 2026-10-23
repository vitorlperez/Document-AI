"use client";

import { Check, ChevronDown, FolderOpen, HelpCircle, History, Keyboard, MoreHorizontal, Plus, Search, ShieldCheck, Sparkles, UserRound, LogOut, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { ThemeToggle } from "./theme-toggle";
import { NotificationBell } from "./product/notification-bell";
import { accountMenuItems, activePrimaryTab, orgMenuSections } from "./product/account-helpers";
import { orgItemIcons } from "./product/org-menu";
import { openPalette, openShortcuts, requestTourReplay } from "./product/nav-events";
import { type Company, type User, accountTypeLabel, companyPath, roleLabel } from "./product/types-and-api";
import "./mobile-chat.css";
import "./interface-motion.css";

/** Contract C5: below 768px the mobile shell (header + bottom tab bar + "Mais" sheet) replaces the desktop header. */
const MOBILE_QUERY = "(max-width: 767px)";

export function useIsMobileShell() {
  const [mobile, setMobile] = useState(false);
  useEffect(() => {
    const query = window.matchMedia(MOBILE_QUERY);
    const update = () => setMobile(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return mobile;
}

/**
 * Keeps the app pinned to the *visible* area when the virtual keyboard opens.
 * iOS Safari never shrinks the layout viewport (dvh stays) and instead scrolls the visual viewport down to the
 * focused field, so the shell must follow both its height (--app-vh) and its offset (--app-vt) — otherwise the
 * header scrolls away and the composer lands in the wrong place. With `lockDocument` (the full-height chat shell) the document
 * itself is frozen so only the transcript scrolls; other screens keep normal page scrolling.
 */
export function useVisualViewportHeight(enabled: boolean, lockDocument = false) {
  useEffect(() => {
    const viewport = window.visualViewport;
    const root = document.documentElement;
    if (!enabled || !viewport) return;
    if (lockDocument) root.dataset.appLock = "true";
    const update = () => {
      root.style.setProperty("--app-vh", `${Math.round(viewport.height)}px`);
      root.style.setProperty("--app-vt", `${Math.round(viewport.offsetTop)}px`);
      if (lockDocument && (window.scrollY !== 0 || window.scrollX !== 0)) window.scrollTo(0, 0);
    };
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    window.addEventListener("scroll", update);
    return () => { viewport.removeEventListener("resize", update); viewport.removeEventListener("scroll", update); window.removeEventListener("scroll", update); root.style.removeProperty("--app-vh"); root.style.removeProperty("--app-vt"); delete root.dataset.appLock; };
  }, [enabled, lockDocument]);
}

const chatSelector = (suffix: string) => `#consultas ${suffix}`;

/** The soft keyboard shrinks the visual viewport; the tab bar steps aside so it never sits on top of the composer. */
function useKeyboardOpen() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const viewport = window.visualViewport;
    if (!viewport) return;
    const update = () => setOpen(window.innerHeight - viewport.height > 150);
    update();
    viewport.addEventListener("resize", update);
    return () => viewport.removeEventListener("resize", update);
  }, []);
  return open;
}

/** Sheet with the org menu content (orgs, work, manage) plus the personal items; the same source of items as the desktop menus. */
export function MoreSheet({ open, onOpenChange, user, company, companies, onCompanyChange, onNavigate, onLogout, pathname }: { open: boolean; onOpenChange: (open: boolean) => void; user: User; company: Company; companies: Company[]; onCompanyChange: (id: string) => void; onNavigate: (path: string) => void; onLogout: () => void; pathname: string }) {
  const sections = orgMenuSections(company.role);
  const go = (action: () => void) => () => { onOpenChange(false); action(); };
  return <Sheet open={open} onOpenChange={onOpenChange}>
    <SheetContent side="bottom" showCloseButton={false} motionProfile="arquivio" id="mobile-more-sheet" className="mobile-more-sheet" aria-describedby="mobile-more-description">
      <div className="mobile-more-head"><SheetTitle className="mobile-more-title">Menu</SheetTitle><SheetClose className="mobile-header-button" aria-label="Fechar menu"><X size={20} aria-hidden="true" /></SheetClose></div>
      <SheetDescription id="mobile-more-description" className="sr-only">Organização, trabalho, gerenciamento e conta</SheetDescription>
      <div className="mobile-more-body">
        <section aria-label="Organização"><p className="mobile-more-label">Organização</p>
          <div className="mobile-drawer-nav">{companies.map((item) => <button key={item.id} type="button" aria-current={item.id === company.id ? "true" : undefined} onClick={go(() => { if (item.id !== company.id) onCompanyChange(item.id); })}><span className="mobile-more-grow">{item.name}</span><small>{roleLabel(item.role)}{accountTypeLabel(item.account_type) ? ` · ${accountTypeLabel(item.account_type)}` : ""}</small>{item.id === company.id && <Check size={16} aria-hidden="true" />}</button>)}</div>
        </section>
        {sections.map((section) => <section key={section.key} aria-label={section.label}><p className="mobile-more-label">{section.key === "manage" ? "Gerenciar" : section.label}</p>
          <div className="mobile-drawer-nav">{section.items.map((item) => { const Icon = orgItemIcons[item.key]; const path = companyPath(company.id, item.suffix); return <button key={item.key} type="button" aria-current={pathname.replace(/\/$/, "") === path ? "page" : undefined} onClick={go(() => onNavigate(path))}><Icon size={18} aria-hidden="true" />{item.label}</button>; })}</div>
        </section>)}
        <section aria-label="Eu"><p className="mobile-more-label">Eu · {user.email}</p>
          <div className="mobile-drawer-nav">
            {accountMenuItems(company.role).map((item) => <button key={item.key} type="button" aria-current={pathname.replace(/\/$/, "") === companyPath(company.id, item.suffix) ? "page" : undefined} onClick={go(() => onNavigate(companyPath(company.id, item.suffix)))}><UserRound size={18} aria-hidden="true" />{item.label}</button>)}
          </div>
          <ThemeToggle className="mobile-drawer-theme" showLabels />
          <div className="mobile-drawer-nav">
            <button type="button" onClick={go(() => requestTourReplay(pathname, company.id, onNavigate))}><HelpCircle size={18} aria-hidden="true" />Conhecer o app</button>
            <button type="button" onClick={go(openShortcuts)}><Keyboard size={18} aria-hidden="true" />Atalhos</button>
            {user.is_platform_staff && <button type="button" onClick={go(() => onNavigate("/staff"))}><ShieldCheck size={18} aria-hidden="true" />Suporte</button>}
            <button type="button" onClick={go(onLogout)}><LogOut size={18} aria-hidden="true" />Sair</button>
          </div>
        </section>
      </div>
    </SheetContent>
  </Sheet>;
}

/** Mobile top bar: org chip (opens the "Mais" sheet), search, conversation history (chat only) and the bell. */
export function MobileShellHeader({ company, pathname, more, onOpenMore }: { company: Company; pathname: string; more: boolean; onOpenMore: () => void }) {
  const screen = activePrimaryTab(pathname) === "chat" ? "chat" : "other";
  const showHistory = () => document.querySelector<HTMLButtonElement>(chatSelector('[data-tour="history"]'))?.click();
  return <header className="mobile-header" role="banner">
    <button type="button" data-tour="org" className="mobile-header-org" onClick={onOpenMore} aria-haspopup="dialog" aria-expanded={more} aria-controls="mobile-more-sheet" aria-label={`Organização ativa: ${company.name}. Abrir menu`}><span>{company.name}</span><ChevronDown size={14} aria-hidden="true" /></button>
    <span className="mobile-header-title" />
    <button type="button" className="mobile-header-button" onClick={openPalette} aria-label="Buscar"><Search size={20} aria-hidden="true" /></button>
    {screen === "chat" && <button type="button" data-testid="mobile-history" className="mobile-header-button" onClick={showHistory} aria-label="Conversas"><History size={20} aria-hidden="true" /></button>}
    <NotificationBell key={company.id} company={company} />
  </header>;
}

export function MobileTabBar({ user, company, pathname, onNavigate, onOpenMore }: { user: User; company: Company; pathname: string; onNavigate: (path: string) => void; onOpenMore: () => void }) {
  const keyboardOpen = useKeyboardOpen();
  const active = activePrimaryTab(pathname);
  const chat = active === "chat";
  const newConversation = () => {
    if (chat) document.querySelector<HTMLButtonElement>(chatSelector('[data-tour="new-conversation"]'))?.click();
    else onNavigate(companyPath(company.id));
  };
  return <nav aria-label="Navegação principal" data-tour="navigation" className="mobile-tab-bar" hidden={keyboardOpen}>
    <button type="button" onClick={() => onNavigate(companyPath(company.id))} aria-current={active === "chat" ? "page" : undefined}><Sparkles size={22} aria-hidden="true" /><span>Conversa</span></button>
    <button type="button" onClick={() => onNavigate(companyPath(company.id, "/library"))} aria-current={active === "library" ? "page" : undefined}><FolderOpen size={22} aria-hidden="true" /><span>Biblioteca</span></button>
    <button type="button" data-tour="new-conversation" onClick={newConversation} aria-label="Nova conversa"><Plus size={22} aria-hidden="true" /><span>Nova</span></button>
    <button type="button" data-tour="account" onClick={onOpenMore} aria-haspopup="dialog" aria-controls="mobile-more-sheet" aria-label={`Mais e conta de ${user.email}`}><MoreHorizontal size={22} aria-hidden="true" /><span>Mais</span></button>
  </nav>;
}
