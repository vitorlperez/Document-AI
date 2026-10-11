"use client";

import { Bell, Building2, Mail, SlidersHorizontal, UserRound } from "lucide-react";
import { type ReactNode, useEffect, useState } from "react";
import { AvatarBadge } from "./account-menu";
import { displayNameFromEmail } from "./account-helpers";
import { type Company, type User, api, messageFor, roleLabel } from "./types-and-api";

const cardClass = "rounded-lg border border-[var(--card-edge)] bg-[var(--surface-raised)] p-5";

function Section({ icon: Icon, title, description, children }: { icon: typeof UserRound; title: string; description?: string; children: ReactNode }) {
  return <section className={cardClass} aria-labelledby={`profile-${title}`}>
    <h2 id={`profile-${title}`} className="flex items-center gap-2 text-base font-semibold text-ink"><Icon size={18} className="text-primary" aria-hidden="true" />{title}</h2>
    {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
    <div className="mt-4">{children}</div>
  </section>;
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return <div className="min-w-0"><dt className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{label}</dt><dd className="mt-1 break-words text-sm text-ink">{children}</dd></div>;
}

function EmailNotificationPreference({ company, setError }: { company: Company; setError: (message: string | null) => void }) {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const base = `/organizations/${company.id}/notification-preferences`;
  useEffect(() => {
    const controller = new AbortController();
    api<{ email_enabled: boolean }>(base, { signal: controller.signal, cache: "no-store" }).then((value) => setEnabled(value.email_enabled)).catch((caught) => { if (!controller.signal.aborted) setError(messageFor(caught)); });
    return () => controller.abort();
  }, [base, setError]);
  async function toggle() {
    if (enabled === null) return;
    const next = !enabled; setEnabled(next); setError(null);
    try { await api(base, { method: "PUT", body: JSON.stringify({ email_enabled: next }) }); } catch (caught) { setEnabled(!next); setError(messageFor(caught)); }
  }
  return <label className="flex min-h-11 items-start gap-3 text-sm">
    <input type="checkbox" className="mt-0.5 size-5 shrink-0 accent-[var(--color-primary)]" checked={enabled ?? false} disabled={enabled === null} onChange={() => void toggle()} />
    <span><span className="flex items-center gap-1.5 font-medium text-ink"><Bell size={15} aria-hidden="true" />Notificações por e-mail</span><span className="mt-0.5 block text-muted-foreground">Receba também por e-mail os avisos de perguntas seguidas e o resumo semanal desta organização.</span></span>
  </label>;
}

export function ProfileScreen({ user, company, setError }: { user: User; company: Company; setError: (message: string | null) => void }) {
  const name = displayNameFromEmail(user.email) || user.email;
  const since = user.created_at ? new Date(user.created_at) : null;
  return <div className="mx-auto max-w-3xl space-y-4">
    <h1 className="text-2xl font-semibold text-ink">Perfil</h1>
    <section className={`${cardClass} flex items-center gap-4`} aria-label="Resumo da conta">
      <AvatarBadge user={user} size={64} />
      <div className="min-w-0"><p className="truncate text-lg font-semibold text-ink">{name}</p><p className="truncate text-sm text-muted-foreground">{user.email}</p></div>
    </section>
    <Section icon={Mail} title="Conta">
      <dl className="grid gap-4 sm:grid-cols-2">
        <Field label="Nome">{name}</Field>
        <Field label="E-mail">{user.email}</Field>
        {since && !Number.isNaN(since.getTime()) && <Field label="Membro desde"><time dateTime={user.created_at}>{since.toLocaleDateString("pt-BR", { dateStyle: "long" })}</time></Field>}
      </dl>
    </Section>
    <Section icon={Building2} title="Organização">
      <dl className="grid gap-4 sm:grid-cols-2"><Field label="Organização atual">{company.name}</Field><Field label="Papel">{roleLabel(company.role)}</Field></dl>
    </Section>
    <Section icon={SlidersHorizontal} title="Preferências" description="Ajustes pessoais para esta organização.">
      <EmailNotificationPreference key={company.id} company={company} setError={setError} />
    </Section>
  </div>;
}
