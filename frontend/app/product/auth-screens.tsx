"use client";

import { Building2, ChevronRight, CircleAlert, Plus, UserRound as User2 } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Brand } from "../brand";
import { type AccountType, type Company, type User, ApiError, api, clearSignupIntent, intentAccountType, isInvitationToken, messageFor, readSignupIntent } from "./types-and-api";
import { LoadingIndicator } from "./shared-ui";
import { btn } from "../ui";

export function Loading() { return <main className="auth-page"><div className="text-center"><Brand /><LoadingIndicator label="Preparando seu espaço de conhecimento…" className="mt-3 justify-center text-sm text-muted-foreground" /></div></main>; }
export { SignIn } from "./custom-login";
export function InvitationAcceptance({ token, onAccepted }: { token: string | undefined; onAccepted: (organizationId: string) => void }) {
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  if (!isInvitationToken(token)) return <main className="auth-page"><section className="max-w-md text-center"><CircleAlert className="mx-auto text-amber-300" size={34} /><h1 className="mt-4 text-2xl font-semibold">Convite indisponível</h1><p className="mt-3 text-muted-foreground">Este link não é válido. Peça um novo convite à pessoa responsável pela organização.</p></section></main>;
  async function accept() { setBusy(true); setError(null); try { const accepted = await api<{ organization_id: string }>(`/invitations/${encodeURIComponent(token ?? "")}/accept`, { method: "POST" }); onAccepted(accepted.organization_id); } catch (caught) { setError(caught instanceof ApiError && caught.status === 404 ? "Este convite expirou, já foi usado ou não pertence ao seu e-mail." : messageFor(caught)); } finally { setBusy(false); } }
  return <main className="auth-page"><section className="auth-card"><Brand /><p className="mt-6 text-sm font-semibold text-primary">Convite para uma organização</p><h1 className="mt-2 text-3xl font-semibold">Participar da equipe</h1><p className="mt-3 leading-6 text-muted-foreground">Ao aceitar, você terá acesso aos recursos compartilhados com os membros desta organização.</p>{error && <p className="mt-4 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">{error}</p>}<button disabled={busy} onClick={() => { void accept(); }} className="mt-7 w-full rounded-md bg-primary px-4 py-3 font-semibold text-primary-foreground disabled:opacity-50">{busy ? "Aceitando…" : "Aceitar convite"}</button></section></main>;
}
const ACCOUNT_CHOICES: { type: AccountType; title: string; hint: string; icon: typeof User2; placeholder: string }[] = [
  { type: "personal", title: "Para mim", hint: "Conta individual, só você. Dá para virar empresa depois.", icon: User2, placeholder: "Ex.: Meu espaço" },
  { type: "business", title: "Para minha empresa", hint: "Equipe com convites, papéis e mais limites.", icon: Building2, placeholder: "Ex.: Estúdio Aurora" },
];
export function Onboarding({ user, onCreated }: { user: User; onCreated: (company: Company) => void }) {
  const [name, setName] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const [accountType, setAccountType] = useState<AccountType>("personal");
  // Intenção vinda da LP (?tipo/&plano), guardada pelo login: pré-seleciona, mas a escolha continua explícita.
  useEffect(() => { const intent = readSignupIntent(); if (intent) queueMicrotask(() => setAccountType(intentAccountType(intent))); }, []);
  const choice = ACCOUNT_CHOICES.find((item) => item.type === accountType) ?? ACCOUNT_CHOICES[0];
  async function create(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError(null);
    try {
      const created = await api<Company>("/organizations", { method: "POST", body: JSON.stringify({ name: name.trim(), account_type: accountType }) });
      clearSignupIntent();
      onCreated({ ...created, name: name.trim() });
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "personal_org_limit") { setAccountType("business"); setError("Você já tem uma conta pessoal. Crie uma conta de empresa ou transforme a pessoal em empresa pelo menu Administração."); }
      else setError(messageFor(caught));
    } finally { setBusy(false); }
  }
  return <main className="auth-page"><section className="auth-card"><Brand /><p className="mt-6 text-sm text-muted-foreground">{user.email}</p><h1 className="mt-2 text-3xl font-semibold">Crie sua primeira organização</h1><p className="mt-3 leading-6 text-muted-foreground">Reúna os documentos em um só lugar. Depois, conecte uma fonte de arquivos{accountType === "business" ? " e convide as pessoas com quem você trabalha" : ""}. Teste grátis por 14 dias, sem cartão.</p>
    <form onSubmit={(event) => { void create(event); }} className="mt-7">
      <fieldset disabled={busy}><legend className="text-sm font-medium">Esta conta é…</legend>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">{ACCOUNT_CHOICES.map((item) => { const Icon = item.icon; return <label key={item.type} data-testid={`account-type-${item.type}`} className="flex cursor-pointer items-start gap-3 rounded-md border border-line bg-panel p-3 has-[:checked]:border-primary has-[:checked]:ring-2 has-[:checked]:ring-primary"><input type="radio" name="account-type" value={item.type} checked={accountType === item.type} onChange={() => setAccountType(item.type)} className="mt-1" /><span className="min-w-0"><b className="flex items-center gap-1.5 text-sm"><Icon size={16} aria-hidden="true" />{item.title}</b><span className="mt-1 block text-xs text-muted-foreground">{item.hint}</span></span></label>; })}</div>
      </fieldset>
      <label htmlFor="company-name" className="mt-5 block text-sm font-medium">{accountType === "business" ? "Nome da empresa" : "Nome da organização"}</label><input id="company-name" required maxLength={160} value={name} onChange={(event) => setName(event.target.value)} placeholder={choice.placeholder} className="mt-2 w-full rounded-md border border-line bg-panel px-4 py-3 outline-none ring-primary focus:ring-2" aria-describedby={error ? "company-name-error" : undefined} />{error && <p id="company-name-error" role="alert" className="mt-3 text-sm text-rose-700">{error}</p>}<button disabled={busy || !name.trim()} aria-busy={busy} className={btn("primary", "md", "mt-5")}><Plus size={18} aria-hidden="true" />{busy ? "Criando…" : "Criar organização"}</button></form></section></main>;
}
export function InvalidCompany({ companies, onChoose }: { companies: Company[]; onChoose: (id: string) => void }) { return <main className="auth-page"><section className="max-w-md text-center"><CircleAlert className="mx-auto text-amber-300" size={34} /><h1 className="mt-4 text-2xl font-semibold">Esta organização não está disponível</h1><p className="mt-3 text-muted-foreground">Você não tem acesso a este espaço ou ele não está mais disponível. Escolha uma organização da qual você participa.</p><div className="mt-6 space-y-2">{companies.map((company) => <button key={company.id} onClick={() => onChoose(company.id)} className="flex w-full items-center justify-between rounded-md border border-line bg-panel px-4 py-3 text-left hover:bg-sage"><span>{company.name}</span><ChevronRight size={16} /></button>)}</div></section></main>; }
