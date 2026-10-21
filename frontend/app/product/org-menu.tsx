"use client";

import { BarChart3, Check, ChevronDown, Clock3, Code2, HardDrive, Users, UsersRound } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { type OrgMenuItemKey, orgMenuSections } from "./account-helpers";
import { type Company, companyPath, roleLabel } from "./types-and-api";
import { Transition } from "../ui";
import "./shell-motion.css";

export const orgItemIcons: Record<OrgMenuItemKey, typeof Users> = { spaces: Users, automations: Clock3, integrations: HardDrive, team: UsersRound, admin: BarChart3, developer: Code2 };
const itemClass = "shell-menu-item flex min-h-11 w-full items-center gap-2.5 rounded-md px-3 text-left text-sm font-medium text-ink hover:bg-sage focus-visible:bg-sage focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary";
const headingClass = "px-3 pb-1 pt-2 text-[11px] font-bold uppercase tracking-wider text-muted-foreground";

/** Org chip + menu: switch organization, work items (everyone) and the "Gerenciar" section (owners/admins only). */
export function OrgMenu({ company, companies, onCompanyChange, onNavigate }: { company: Company; companies: Company[]; onCompanyChange: (id: string) => void; onNavigate: (path: string) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const sections = orgMenuSections(company.role);

  const close = (restoreFocus: boolean) => { setOpen(false); if (restoreFocus) trigger.current?.focus({ preventScroll: true }); };
  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLElement>('[role^="menuitem"]')?.focus({ preventScroll: true });
    const onPointer = (event: MouseEvent | TouchEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onPointer); document.addEventListener("touchstart", onPointer);
    return () => { document.removeEventListener("mousedown", onPointer); document.removeEventListener("touchstart", onPointer); };
  }, [open]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") { event.stopPropagation(); close(true); return; }
    if (event.key === "Tab") { setOpen(false); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const nodes = [...(menu.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]') ?? [])];
    if (!nodes.length) return;
    event.preventDefault();
    const current = nodes.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? nodes.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + nodes.length) % nodes.length;
    nodes[next].focus({ preventScroll: true });
  }
  const choose = (action: () => void) => () => { setOpen(false); action(); };

  return <div ref={root} className="relative min-w-0" onKeyDown={open ? onKeyDown : undefined}>
    <button ref={trigger} type="button" onClick={() => setOpen((value) => !value)} onKeyDown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); setOpen(true); } }} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} aria-label={`Organização ativa: ${company.name}. Abrir menu da organização`} title={company.name} data-tour="org" data-testid="org-menu-trigger" className="organization-name mo-interactive inline-flex min-h-11 max-w-36 items-center gap-1.5 rounded-full border border-line bg-panel px-3 text-sm font-semibold hover:bg-sage focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary min-[1100px]:max-w-52"><span className="truncate">{company.name}</span><ChevronDown size={14} aria-hidden="true" className="shrink-0 text-muted-foreground" /></button>
    <Transition show={open} variant="scale" exitMs={120} className="shell-popover absolute left-0 top-full z-50 mt-2 w-[min(18rem,calc(100vw-2rem))]"><div ref={menu} id={menuId} role="menu" aria-label="Organização" className="max-h-[calc(100dvh-6rem)] overflow-y-auto rounded-lg border border-[var(--card-edge)] bg-[var(--surface-raised)] p-1.5 shadow-xl">
      <p className={headingClass} role="presentation">Organização</p>
      {companies.map((item) => <button key={item.id} type="button" role="menuitemradio" aria-checked={item.id === company.id} tabIndex={-1} onClick={choose(() => { if (item.id !== company.id) onCompanyChange(item.id); })} className={itemClass}><span className="min-w-0 flex-1 truncate">{item.name}</span><span className="shrink-0 text-xs font-normal text-muted-foreground">{roleLabel(item.role)}</span><Check size={16} aria-hidden="true" className={item.id === company.id ? "shrink-0 text-primary" : "invisible shrink-0"} /></button>)}
      {sections.map((section) => <div key={section.key} role="group" aria-label={section.label}>
        <div role="separator" className="my-1 border-t border-[var(--card-edge)]" />
        <p className={headingClass} role="presentation">{section.label}</p>
        {section.items.map((item) => { const Icon = orgItemIcons[item.key]; return <button key={item.key} type="button" role="menuitem" tabIndex={-1} onClick={choose(() => onNavigate(companyPath(company.id, item.suffix)))} className={itemClass}><Icon size={18} aria-hidden="true" />{item.label}</button>; })}
      </div>)}
    </div></Transition>
  </div>;
}
