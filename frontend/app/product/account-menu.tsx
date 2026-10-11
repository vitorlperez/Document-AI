"use client";

import { BarChart3, Code2, LogOut, UserRound } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { accountMenuItems, avatarInitial, displayNameFromEmail } from "./account-helpers";
import { type Company, type User, companyPath } from "./types-and-api";

const icons = { profile: UserRound, admin: BarChart3, developer: Code2 };
const itemClass = "flex min-h-11 w-full items-center gap-2.5 rounded-md px-3 text-left text-sm font-medium text-ink hover:bg-sage focus-visible:bg-sage focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary";

export function AvatarBadge({ user, size = 32 }: { user: User; size?: number }) {
  return <span aria-hidden="true" style={{ width: size, height: size, fontSize: size * 0.45 }} className="inline-flex shrink-0 select-none items-center justify-center rounded-full bg-primary font-semibold leading-none text-primary-foreground">{avatarInitial(displayNameFromEmail(user.email), user.email)}</span>;
}

export function AccountMenu({ user, company, onNavigate, onLogout }: { user: User; company: Company; onNavigate: (path: string) => void; onLogout: () => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const menuId = useId();
  const name = displayNameFromEmail(user.email) || user.email;
  const items = accountMenuItems(company.role);

  const close = (restoreFocus: boolean) => { setOpen(false); if (restoreFocus) trigger.current?.focus({ preventScroll: true }); };
  useEffect(() => {
    if (!open) return;
    menu.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus({ preventScroll: true });
    const onPointer = (event: MouseEvent | TouchEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onPointer); document.addEventListener("touchstart", onPointer);
    return () => { document.removeEventListener("mousedown", onPointer); document.removeEventListener("touchstart", onPointer); };
  }, [open]);

  function onKeyDown(event: React.KeyboardEvent) {
    if (event.key === "Escape") { event.stopPropagation(); close(true); return; }
    if (event.key === "Tab") { setOpen(false); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const nodes = [...(menu.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? [])];
    if (!nodes.length) return;
    event.preventDefault();
    const current = nodes.indexOf(document.activeElement as HTMLElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? nodes.length - 1 : (current + (event.key === "ArrowDown" ? 1 : -1) + nodes.length) % nodes.length;
    nodes[next].focus({ preventScroll: true });
  }
  const choose = (action: () => void) => () => { setOpen(false); action(); };

  return <div ref={root} className="relative" onKeyDown={open ? onKeyDown : undefined}>
    <button ref={trigger} type="button" onClick={() => setOpen((value) => !value)} onKeyDown={(event) => { if (event.key === "ArrowDown" && !open) { event.preventDefault(); setOpen(true); } }} aria-haspopup="menu" aria-expanded={open} aria-controls={open ? menuId : undefined} aria-label={`Menu da conta de ${name}`} title="Conta" data-testid="account-menu-trigger" className="inline-flex size-11 items-center justify-center rounded-full hover:bg-sage focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary min-[768px]:size-10"><AvatarBadge user={user} /></button>
    {open && <div ref={menu} id={menuId} role="menu" aria-label="Conta" className="absolute right-0 top-full z-50 mt-2 w-[min(18rem,calc(100vw-2rem))] rounded-lg border border-[var(--card-edge)] bg-[var(--surface-raised)] p-1.5 shadow-xl">
      <div className="px-3 py-2.5"><p className="truncate text-sm font-semibold text-ink">{name}</p><p className="truncate text-xs text-muted-foreground" title={user.email}>{user.email}</p></div>
      <div role="separator" className="my-1 border-t border-[var(--card-edge)]" />
      {items.map((item) => { const Icon = icons[item.key]; return <button key={item.key} type="button" role="menuitem" tabIndex={-1} onClick={choose(() => onNavigate(companyPath(company.id, item.suffix)))} className={itemClass}><Icon size={17} aria-hidden="true" />{item.label}</button>; })}
      <div role="separator" className="my-1 border-t border-[var(--card-edge)]" />
      <button type="button" role="menuitem" tabIndex={-1} onClick={choose(onLogout)} className={itemClass}><LogOut size={17} aria-hidden="true" />Sair</button>
    </div>}
  </div>;
}
