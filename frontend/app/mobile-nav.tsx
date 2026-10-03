"use client";

import { Code2, FolderOpen, HardDrive, HelpCircle, LogOut, Menu, Plus, ShieldCheck, Sparkles, Users, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { Brand } from "./brand";
import { SyncBanner, useSyncStatus } from "./sync-status";
import { ToolsSidebar, type ToolSelection } from "./tools-sidebar";
import { type Company, type LibraryNode, type LibraryPage, type User, api, companyPath, roleLabel } from "./product/types-and-api";
import "./mobile-chat.css";
import "./interface-motion.css";

/** Contract C5: below 768px the mobile shell (header + drawer) replaces the desktop header. */
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

/** Tracks the visual viewport so the composer stays above the virtual keyboard (iOS does not shrink dvh). */
export function useVisualViewportHeight(enabled: boolean) {
  useEffect(() => {
    const viewport = window.visualViewport;
    const root = document.documentElement;
    if (!enabled || !viewport) return;
    const update = () => root.style.setProperty("--app-vh", `${Math.round(viewport.height)}px`);
    update();
    viewport.addEventListener("resize", update);
    viewport.addEventListener("scroll", update);
    return () => { viewport.removeEventListener("resize", update); viewport.removeEventListener("scroll", update); root.style.removeProperty("--app-vh"); };
  }, [enabled]);
}

const chatSelector = (suffix: string) => `#consultas ${suffix}`;

export function MobileShellHeader({ user, company, companies, screen, activePath, onCompanyChange, onNavigate, onLogout }: { user: User; company: Company; companies: Company[]; screen: "chat" | "other"; activePath: string; onCompanyChange: (id: string) => void; onNavigate: (path: string) => void; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const canManage = company.role !== "member";
  const sync = useSyncStatus(company.id, { enabled: true });
  const [roots, setRoots] = useState<LibraryNode[]>([]);
  useEffect(() => {
    const controller = new AbortController();
    api<LibraryPage>(`/library?organization_id=${company.id}`, { signal: controller.signal })
      .then((page) => setRoots(page.items ?? []))
      .catch(() => { if (!controller.signal.aborted) setRoots([]); });
    return () => controller.abort();
  }, [company.id, sync.anySyncing]);

  const go = useCallback((path: string) => { setOpen(false); onNavigate(path); }, [onNavigate]);
  const newConversation = () => {
    setOpen(false);
    if (screen === "chat") document.querySelector<HTMLButtonElement>(chatSelector('[data-tour="new-conversation"]'))?.click();
    else onNavigate(companyPath(company.id));
  };
  const showTour = () => {
    setOpen(false);
    const trigger = () => document.querySelector<HTMLButtonElement>(chatSelector('button[aria-label="Rever tour do app"]'))?.click();
    if (screen === "chat") trigger(); else onNavigate(companyPath(company.id));
  };
  const selectTool = (tool: ToolSelection) => go(`${companyPath(company.id, "/library")}?source=${encodeURIComponent(tool.libraryNodeId)}`);

  const navItems = [
    { key: "chat", label: "Consultas", icon: Sparkles, path: companyPath(company.id) },
    { key: "library", label: "Biblioteca", icon: FolderOpen, path: companyPath(company.id, "/library") },
    ...(company.role === "owner" ? [{ key: "team", label: "Equipe", icon: Users, path: companyPath(company.id, "/team") }] : []),
    ...(canManage ? [{ key: "integrations", label: "Integrações", icon: HardDrive, path: companyPath(company.id, "/integrations") }] : []),
    ...(canManage ? [{ key: "developer", label: "Desenvolvedor", icon: Code2, path: companyPath(company.id, "/developer") }] : []),
  ];

  return <>
    <header className="mobile-header" role="banner">
      <button ref={menuButtonRef} type="button" data-tour="navigation" className="mobile-header-button" onClick={() => setOpen(true)} aria-label="Abrir menu" aria-expanded={open} aria-controls="mobile-drawer" aria-haspopup="dialog"><Menu size={22} aria-hidden="true" /></button>
      <div className="mobile-header-title"><span>{company.name}</span></div>
      <button type="button" data-tour="new-conversation" className="mobile-header-new" onClick={newConversation}><Plus size={16} aria-hidden="true" />Nova conversa</button>
    </header>
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent side="left" showCloseButton={false} motionProfile="arquivio" id="mobile-drawer" className="mobile-drawer" aria-describedby="mobile-drawer-description" onCloseAutoFocus={(event) => { event.preventDefault(); menuButtonRef.current?.focus({ preventScroll: true }); }}>
        <div className="mobile-drawer-head">
          <Brand compact />
          <SheetClose className="mobile-header-button" aria-label="Fechar menu"><X size={20} aria-hidden="true" /></SheetClose>
        </div>
        <SheetTitle className="sr-only">Menu</SheetTitle>
        <SheetDescription id="mobile-drawer-description" className="sr-only">Navegação, ferramentas e conta</SheetDescription>
        <div className="mobile-drawer-body">
          <label className="mobile-drawer-field"><span>Organização</span>
            <select aria-label="Organização ativa" value={company.id} onChange={(event) => { setOpen(false); onCompanyChange(event.target.value); }}>{companies.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
          </label>
          <nav aria-label="Navegação principal" className="mobile-drawer-nav">
            {navItems.map(({ key, label, icon: Icon, path }) => <button key={key} type="button" onClick={() => go(path)} aria-current={activePath.replace(/\/$/, "") === path ? "page" : undefined}><Icon size={18} aria-hidden="true" />{label}</button>)}
            {screen === "chat" && <button type="button" onClick={showTour}><HelpCircle size={18} aria-hidden="true" />Conhecer o app</button>}
          </nav>
          <section aria-label="Ferramentas" className="mobile-drawer-section">
            <ToolsSidebar variant="list" orgId={company.id} canManage={canManage} collapsed={false} onToggle={() => undefined} onSelectTool={selectTool} onAdd={() => go(companyPath(company.id, "/integrations"))} tools={sync.tools} loading={sync.loading} libraryRoots={roots} />
          </section>
          <SyncBanner tools={sync.tools} className="mobile-drawer-sync" />
        </div>
        <div className="mobile-drawer-foot">
          <div className="mobile-drawer-user"><span title={user.email}>{user.email}</span><small>{roleLabel(company.role)}</small></div>
          {user.is_platform_staff && <button type="button" onClick={() => go("/staff")}><ShieldCheck size={18} aria-hidden="true" />Suporte</button>}
          <button type="button" onClick={() => { setOpen(false); onLogout(); }}><LogOut size={18} aria-hidden="true" />Sair</button>
        </div>
      </SheetContent>
    </Sheet>
  </>;
}
