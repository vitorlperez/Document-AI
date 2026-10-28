"use client";

import { Building2, Clock3, ExternalLink, FileText, Lock, UserRound, Users } from "lucide-react";
import { type FormEvent, type ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
import { useDialogBackdropClose } from "../modal-dismiss";
import { btn, closeDialogAnimated } from "../ui";
import {
  BILLING_SOON_MESSAGE, CHECKOUT_POLL_INTERVAL_MS, CHECKOUT_RETURN_MESSAGES, PLAN_CHANGED_EVENT, PLAN_ERROR_EVENT, ApiError, accountTypeLabel, api, billingReturnFrom, checkoutPollOutcome, companyPath,
  defaultBusinessPlan, downgradeBlockers, formatCents, formatInvoiceTotal, invoiceDate, invoiceStatusLabel, invoiceTitle, isLegacyPlan, isPersonal, messageFor, pendingPaymentNotice, planDialogCopy, planLabel, planTitle, sourceLabel,
  stripBillingReturn, subscriptionStatusLabel, upgradeDoneNotice, upgradeIntro, type BillingState, type Company, type InvoiceSummary, type PlanBlock, type PlanErrorInfo, type PlansResponse, type PublicPlan,
} from "./types-and-api";
import "./automation-modal.css";

export const notifyPlanChanged = () => { if (typeof window !== "undefined") window.dispatchEvent(new Event(PLAN_CHANGED_EVENT)); };
const adminPlanPath = (companyId: string) => companyPath(companyId, "/admin#plano");

/** Badge Pessoal/Empresa do seletor de organizações. Sem tipo (resposta antiga) não renderiza nada. */
export function AccountTypeBadge({ company, className = "" }: { company: Pick<Company, "account_type">; className?: string }) {
  const label = accountTypeLabel(company.account_type);
  if (!label) return null;
  const Icon = company.account_type === "business" ? Building2 : UserRound;
  return <span data-testid="account-type-badge" data-account-type={company.account_type} className={`inline-flex shrink-0 items-center gap-1 rounded-full border border-line px-2 py-0.5 text-[11px] font-semibold text-muted-foreground ${className}`}><Icon size={12} aria-hidden="true" />{label}</span>;
}

// ── Catálogo público ──────────────────────────────────────────────────────────
let plansCache: Promise<PlansResponse> | null = null;
export function usePlans() {
  const [plans, setPlans] = useState<PlansResponse | null>(null);
  useEffect(() => {
    let alive = true;
    plansCache ??= api<PlansResponse>("/plans").catch((caught) => { plansCache = null; throw caught; });
    plansCache.then((value) => { if (alive) setPlans(value); }).catch(() => { /* catálogo indisponível: formulários caem para valores padrão */ });
    return () => { alive = false; };
  }, []);
  return plans;
}

// ── Diálogo ───────────────────────────────────────────────────────────────────
export function PlanDialog({ title, onClose, busy = false, children }: { title: string; onClose: () => void; busy?: boolean; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const closing = useRef(false);
  const onClosed = useRef(onClose);
  useEffect(() => { onClosed.current = onClose; }, [onClose]);
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    if (element && !element.open) element.showModal();
    return () => { document.body.style.overflow = overflow; requestAnimationFrame(() => { if (trigger?.isConnected) trigger.focus({ preventScroll: true }); }); };
  }, []);
  function requestClose() {
    if (busy || closing.current) return;
    closing.current = true;
    closeDialogAnimated(dialog.current, () => onClosed.current());
  }
  useDialogBackdropClose(dialog, requestClose, busy);
  return <dialog ref={dialog} aria-modal="true" aria-labelledby={titleId} aria-busy={busy} data-testid="plan-dialog" className="automation-modal automation-modal-confirm" data-arquivio-motion-root="" onCancel={(event) => { event.preventDefault(); requestClose(); }}>
    <section data-arquivio-motion="panel" className="automation-modal-panel">
      <h2 id={titleId} className="text-xl font-semibold">{title}</h2>
      <div className="mt-3 space-y-3 text-sm">{children}</div>
      <div className="mt-6 flex justify-end"><button type="button" disabled={busy} className={btn("ghost")} onClick={requestClose}>Fechar</button></div>
    </section>
  </dialog>;
}

const FORM_ERRORS: Record<string, string> = {
  invalid_plan: "Este plano não é válido para a conta.", invalid_seats: "Número de assentos inválido para o plano escolhido.", seats_below_members: "Há mais membros do que os assentos escolhidos.",
  comp_type_mismatch: "Esta conta tem uma cortesia de outro tipo. Fale com a gente para ajustar.", personal_org_limit: "Você já tem uma conta pessoal. Transforme-a em empresa ou crie uma conta de empresa.",
};
export const planFormError = (caught: unknown) => caught instanceof ApiError ? (caught.code && FORM_ERRORS[caught.code]) || (caught.code === "billing_not_configured" ? BILLING_SOON_MESSAGE : messageFor(caught)) : messageFor(caught);

const businessPlans = (plans: PlansResponse | null): PublicPlan[] => plans?.plans.filter((plan) => plan.account_type === "business") ?? [];
const planPrice = (plan: PublicPlan, interval: "month" | "year") => interval === "year" ? plan.price_year_cents : plan.price_month_cents;

/** Escolha de plano/assentos/intervalo, compartilhada pelo upgrade e pela assinatura. */
function PlanPicker({ plans, planKey, onPlanKey, seats, onSeats, interval, onInterval, disabled }: { plans: PlansResponse | null; planKey: string; onPlanKey: (key: string) => void; seats: number; onSeats: (value: number) => void; interval: "month" | "year"; onInterval: (value: "month" | "year") => void; disabled: boolean }) {
  const options = businessPlans(plans);
  const selected = options.find((plan) => plan.plan_key === planKey);
  const maxSeats = selected?.max_seats ?? 100;
  return <div className="space-y-3">
    <fieldset className="space-y-2" disabled={disabled}><legend className="text-sm font-medium">Plano</legend>
      {(options.length ? options : [{ plan_key: "business_team", title: "Empresa Team" }, { plan_key: "business_scale", title: "Empresa Scale" }] as PublicPlan[]).map((plan) => <label key={plan.plan_key} className="flex cursor-pointer items-center gap-3 rounded-md border border-line-soft p-3 has-[:checked]:border-primary">
        <input type="radio" name="plan-key" value={plan.plan_key} checked={planKey === plan.plan_key} onChange={() => onPlanKey(plan.plan_key)} />
        <span className="min-w-0 flex-1"><b className="block text-sm">{plan.title}</b>{"price_month_cents" in plan && plan.price_month_cents !== undefined && <span className="text-xs text-muted-foreground">{formatCents(planPrice(plan, interval), plan.currency)}/{interval === "year" ? "ano" : "mês"}{plan.included_seats ? ` · ${plan.included_seats} assentos incluídos` : ""}</span>}</span>
      </label>)}
    </fieldset>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block text-sm font-medium">Assentos<input type="number" min={1} max={maxSeats} required value={seats} disabled={disabled} onChange={(event) => onSeats(Math.max(1, Math.min(maxSeats, Number(event.target.value) || 1)))} className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2" /></label>
      <label className="block text-sm font-medium">Cobrança<select value={interval} disabled={disabled} onChange={(event) => onInterval(event.target.value === "year" ? "year" : "month")} className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2"><option value="month">Mensal</option><option value="year">Anual</option></select></label>
    </div>
  </div>;
}

/** Transforma a conta pessoal em empresa (POST /organizations/{id}/upgrade): mesmo organization_id, dados e histórico preservados. */
export function UpgradeToBusinessForm({ company, hint, onDone }: { company: Company; hint?: string | null; onDone: () => void }) {
  const plans = usePlans(); const intro = upgradeIntro(company);
  const [name, setName] = useState(company.name); const [planKey, setPlanKey] = useState<string>(defaultBusinessPlan(hint));
  const [seats, setSeats] = useState(5); const [interval, setInterval] = useState<"month" | "year">("month");
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError(null);
    try {
      await api(`/organizations/${company.id}/upgrade`, { method: "POST", body: JSON.stringify({ name: name.trim(), plan_key: planKey, seats, interval }) });
      notifyPlanChanged(); onDone();
    } catch (caught) { setError(planFormError(caught)); } finally { setBusy(false); }
  }
  return <form onSubmit={(event) => { void submit(event); }} className="space-y-4" data-testid="upgrade-form" aria-busy={busy}>
    <p className="text-muted-foreground" data-testid="upgrade-intro">Seus documentos, fontes e histórico continuam exatamente como estão. {intro.text}</p>
    <label className="block text-sm font-medium">Nome da empresa<input required maxLength={160} value={name} disabled={busy} onChange={(event) => setName(event.target.value)} className="mt-1 w-full rounded-md border border-line bg-panel px-3 py-2" /></label>
    <PlanPicker plans={plans} planKey={planKey} onPlanKey={setPlanKey} seats={seats} onSeats={setSeats} interval={interval} onInterval={setInterval} disabled={busy} />
    {error && <p role="alert" className="text-sm text-rose-700">{error}</p>}
    <button type="submit" disabled={busy || !name.trim() || intro.blocked} className={btn("primary")}><Building2 size={16} aria-hidden="true" />{busy ? "Transformando…" : "Transformar em empresa"}</button>
  </form>;
}

// ── Diálogo único de upgrade (402/403/429 com code) ───────────────────────────
export function PlanErrorHost({ company, onNavigate }: { company: Company; onNavigate: (path: string) => void }) {
  const [info, setInfo] = useState<PlanErrorInfo | null>(null); const [stage, setStage] = useState<"info" | "upgrade">("info");
  useEffect(() => {
    const handler = (event: Event) => { setInfo((event as CustomEvent<PlanErrorInfo>).detail); setStage("info"); };
    window.addEventListener(PLAN_ERROR_EVENT, handler);
    return () => window.removeEventListener(PLAN_ERROR_EVENT, handler);
  }, []);
  if (!info) return null;
  const copy = planDialogCopy(info, { plan: company, role: company.role });
  const close = () => setInfo(null);
  return <PlanDialog title={stage === "upgrade" ? "Transformar em empresa" : copy.title} onClose={close}>
    {stage === "upgrade" ? <UpgradeToBusinessForm company={company} hint={info.upgradeTo} onDone={close} /> : <>
      <p>{copy.message}</p>
      {copy.usage && <p data-testid="plan-usage" className="rounded-md bg-sage px-3 py-2 font-semibold">{copy.usage}</p>}
      {copy.cta === "upgrade" && <button type="button" className={btn("primary")} onClick={() => setStage("upgrade")}><Building2 size={16} aria-hidden="true" />{copy.ctaLabel}</button>}
      {copy.cta === "plans" && <button type="button" className={btn("primary")} onClick={() => { close(); onNavigate(adminPlanPath(company.id)); }}>{copy.ctaLabel}</button>}
    </>}
  </PlanDialog>;
}

// ── Label do header ───────────────────────────────────────────────────────────
/** Pill discreto (sem link/botão) no header; `compact` mostra a versão curta no mobile. O diálogo de limite (402) segue em PlanErrorHost. */
export function PlanLabel({ company, compact = false }: { company: PlanBlock; compact?: boolean }) {
  const label = planLabel(company);
  if (!label) return null;
  const Icon = label.kind === "trial" ? Clock3 : Lock;
  return <span role="status" aria-label={label.aria} title={label.title} data-testid="plan-label" data-kind={label.kind} data-compact={compact ? "true" : undefined} className="plan-label"><Icon size={12} aria-hidden="true" /><span aria-hidden="true">{compact ? label.short : label.text}</span></span>;
}

// ── Equipe em conta pessoal ───────────────────────────────────────────────────
export function PersonalTeamUpgrade({ company }: { company: Company }) {
  const [open, setOpen] = useState(false);
  return <section data-testid="personal-team-upgrade" className="max-w-xl rounded-lg border border-line-soft bg-panel p-7">
    <Users className="text-primary" aria-hidden="true" />
    <h1 className="mt-4 text-2xl font-semibold">Contas pessoais não têm equipe</h1>
    <p className="mt-3 leading-6 text-muted-foreground">Para convidar pessoas e compartilhar a biblioteca, transforme esta conta em uma conta de empresa. Nada se perde: seus dados, fontes e histórico continuam aqui.</p>
    <button type="button" className={btn("primary", "md", "mt-5")} onClick={() => setOpen(true)}><Building2 size={16} aria-hidden="true" />Transformar em empresa</button>
    {open && <PlanDialog title="Transformar em empresa" onClose={() => setOpen(false)}><UpgradeToBusinessForm company={company} onDone={() => setOpen(false)} /></PlanDialog>}
  </section>;
}

// ── Plano e cobrança (Administração) ──────────────────────────────────────────
const dateFormat = (value: string | null | undefined) => value ? new Date(value).toLocaleDateString("pt-BR") : "—";
const limitText = (value: number | null | undefined) => value === null || value === undefined ? "Ilimitado" : value.toLocaleString("pt-BR");

/** Faturas do provedor (GET …/billing/invoices, só o responsável). Sem provedor (501) a lista some. */
function InvoiceList({ companyId, refreshKey }: { companyId: string; refreshKey: number }) {
  const [invoices, setInvoices] = useState<InvoiceSummary[] | null>(null); const [hidden, setHidden] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api<InvoiceSummary[]>(`/organizations/${companyId}/billing/invoices`, { cache: "no-store" })
      .then((value) => { if (alive) { setInvoices(value); setError(null); } })
      .catch((caught) => { if (!alive) return; if (caught instanceof ApiError && (caught.status === 501 || caught.code === "billing_not_configured")) setHidden(true); else setError(messageFor(caught)); });
    return () => { alive = false; };
  }, [companyId, refreshKey]);
  if (hidden) return null;
  return <div data-testid="invoice-list" className="mt-6">
    <h3 className="flex items-center gap-2 text-sm font-semibold"><FileText size={16} aria-hidden="true" />Faturas</h3>
    {error && <p role="alert" className="mt-2 text-sm text-rose-700">{error}</p>}
    {!error && invoices === null && <p className="mt-2 text-sm text-muted-foreground">Carregando faturas…</p>}
    {invoices?.length === 0 && <p className="mt-2 text-sm text-muted-foreground">Nenhuma fatura ainda.</p>}
    {invoices && invoices.length > 0 && <ul className="mt-2 divide-y divide-line-soft rounded-md border border-line-soft text-sm">
      {invoices.map((invoice) => <li key={invoice.id} data-testid="invoice-row" className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2">
        <span className="min-w-0 flex-1"><b className="block truncate">{invoiceTitle(invoice)}</b><span className="text-xs text-muted-foreground">{invoiceDate(invoice.created)} · {invoiceStatusLabel(invoice.status)}</span></span>
        <span className="font-semibold tabular-nums">{formatInvoiceTotal(invoice.total, invoice.currency)}</span>
        <span className="flex gap-3 text-xs">
          {invoice.hosted_invoice_url && <a href={invoice.hosted_invoice_url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline">Ver fatura<ExternalLink size={12} aria-hidden="true" /></a>}
          {invoice.invoice_pdf && <a href={invoice.invoice_pdf} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 underline">PDF<ExternalLink size={12} aria-hidden="true" /></a>}
        </span>
      </li>)}
    </ul>}
  </div>;
}

export function PlanBillingSection({ company, setNotice }: { company: Company; setNotice?: (message: string | null) => void }) {
  const plans = usePlans();
  const owner = company.role === "owner";
  const [billing, setBilling] = useState<BillingState | null>(null); const [loadError, setLoadError] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "info" | "error"; text: string } | null>(null); const [blockers, setBlockers] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null); const [upgrade, setUpgrade] = useState(false); const [subscribe, setSubscribe] = useState(false);
  const [planKey, setPlanKey] = useState<string>("business_team"); const [seats, setSeats] = useState(5); const [interval, setInterval] = useState<"month" | "year">("month");
  const load = useCallback(() => { setLoadError(null); api<BillingState>(`/organizations/${company.id}/billing`, { cache: "no-store" }).then(setBilling).catch((caught) => setLoadError(messageFor(caught))); }, [company.id]);
  useEffect(() => { void Promise.resolve().then(load); }, [load, company.account_type, company.plan_key]);
  const loaded = billing !== null;
  const [returnedFrom] = useState(() => typeof window === "undefined" ? null : billingReturnFrom(window.location.search));
  const [confirming, setConfirming] = useState(false); const [invoicesKey, setInvoicesKey] = useState(0);
  useEffect(() => { if (loaded && (window.location.hash === "#plano" || returnedFrom)) document.getElementById("plano")?.scrollIntoView({ block: "start" }); }, [loaded, returnedFrom]);
  // Volta do Checkout/Portal (?checkout=…|?billing=portal): o acesso só muda via webhook, então apenas relemos GET …/billing por alguns segundos.
  useEffect(() => {
    if (!returnedFrom) return;
    window.history.replaceState(window.history.state, "", stripBillingReturn(window.location.href));
    let alive = true; let timer: number | undefined; const started = Date.now();
    const poll = async () => {
      let state: BillingState | null = null;
      try { state = await api<BillingState>(`/organizations/${company.id}/billing`, { cache: "no-store" }); if (alive) setBilling(state); } catch { /* falha transitória: tenta de novo até o prazo */ }
      if (!alive) return;
      const outcome = checkoutPollOutcome(state, Date.now() - started);
      if (outcome === "pending") { timer = window.setTimeout(() => { void poll(); }, CHECKOUT_POLL_INTERVAL_MS); return; }
      setConfirming(false); setMessage({ tone: "info", text: CHECKOUT_RETURN_MESSAGES[outcome] });
      if (outcome === "active") { notifyPlanChanged(); setInvoicesKey((value) => value + 1); }
    };
    void Promise.resolve().then(() => {
      if (!alive) return;
      if (returnedFrom === "checkout_canceled") { setMessage({ tone: "info", text: CHECKOUT_RETURN_MESSAGES.canceled }); return; }
      if (returnedFrom === "portal") { notifyPlanChanged(); return; }
      setConfirming(true); setMessage({ tone: "info", text: CHECKOUT_RETURN_MESSAGES.pending });
      void poll();
    });
    return () => { alive = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, [returnedFrom, company.id]);

  const block = billing ?? company;
  const legacy = isLegacyPlan(block);
  const personal = isPersonal(block);
  const ents = block.entitlements;
  const seatsMax = ents?.max_members ?? null;
  const seatsUsed = billing?.seats_used ?? null;
  const pendingPayment = pendingPaymentNotice(billing);

  async function billingCall(kind: "checkout" | "portal") {
    setBusy(kind); setMessage(null);
    try {
      const body = kind === "checkout" ? { plan_key: planKey, interval, seats } : {};
      const { url } = await api<{ url: string }>(`/organizations/${company.id}/billing/${kind}`, { method: "POST", body: JSON.stringify(body) });
      window.location.assign(url);
    } catch (caught) {
      // Sem provedor de pagamento o backend responde 501 billing_not_configured: mensagem amigável, nunca quebrar.
      setMessage(caught instanceof ApiError && (caught.status === 501 || caught.code === "billing_not_configured") ? { tone: "info", text: BILLING_SOON_MESSAGE } : { tone: "error", text: planFormError(caught) });
    } finally { setBusy(null); }
  }
  async function downgrade() {
    if (!window.confirm("Voltar para uma conta pessoal? Automações além do limite pessoal serão pausadas.")) return;
    setBusy("downgrade"); setMessage(null); setBlockers([]);
    try {
      await api(`/organizations/${company.id}/downgrade`, { method: "POST", body: JSON.stringify({ plan_key: "personal_basic" }) });
      notifyPlanChanged(); setNotice?.("Conta convertida para pessoal."); load();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === "downgrade_blocked") { setBlockers(downgradeBlockers(caught.body?.blockers)); setMessage({ tone: "error", text: "Ainda não é possível voltar para uma conta pessoal." }); }
      else setMessage({ tone: "error", text: planFormError(caught) });
    } finally { setBusy(null); }
  }

  return <section id="plano" data-testid="plan-billing" className="rounded-lg border border-line-soft bg-panel p-4 sm:p-6" aria-labelledby="plan-title">
    <div className="flex flex-wrap items-center gap-3"><Building2 size={22} className="text-primary" aria-hidden="true" /><h2 id="plan-title" className="text-xl font-semibold">Plano e cobrança</h2><AccountTypeBadge company={block} /></div>
    {loadError && <p role="alert" className="mt-4 text-sm text-rose-700">{loadError} <button type="button" onClick={load} className="underline">Tentar novamente</button></p>}
    <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
      <div><dt className="text-muted-foreground">Plano atual</dt><dd className="mt-1 font-semibold" data-testid="plan-current">{planTitle(block.plan_key)}</dd></div>
      <div><dt className="text-muted-foreground">Origem</dt><dd className="mt-1 font-semibold">{sourceLabel(block.entitlement_source)}</dd></div>
      <div><dt className="text-muted-foreground">Assentos</dt><dd className="mt-1 font-semibold" data-testid="plan-seats">{legacy ? "Sem limite" : personal ? "1 (conta individual)" : seatsMax === null ? `${seatsUsed ?? "—"} (sem limite)` : `${seatsUsed ?? "—"} de ${seatsMax}`}</dd></div>
      {block.entitlement_source === "trial" && <div><dt className="text-muted-foreground">Teste até</dt><dd className="mt-1 font-semibold">{dateFormat(block.trial_ends_at)}</dd></div>}
      {block.read_only && <div><dt className="text-muted-foreground">Situação</dt><dd className="mt-1 font-semibold text-rose-700">Somente leitura</dd></div>}
    </dl>
    {legacy && <p className="mt-4 text-sm text-muted-foreground">Esta conta é anterior aos planos e segue sem novos limites ou bloqueios.</p>}
    {billing?.subscription && <p className="mt-4 text-sm text-muted-foreground">Assinatura {subscriptionStatusLabel(billing.subscription.status)}{billing.subscription.interval ? ` · ${billing.subscription.interval === "year" ? "anual" : "mensal"}` : ""}{billing.subscription.current_period_end ? ` · renova em ${dateFormat(billing.subscription.current_period_end)}` : ""}{billing.subscription.cancel_at_period_end ? " · cancelada ao fim do período" : ""}.</p>}
    {ents && !legacy && block.plan_key !== "expired" && <p className="mt-3 text-xs text-muted-foreground">Limites: {limitText(ents.max_spaces)} Espaços · {limitText(ents.max_automations)} automações · {limitText(ents.max_data_sources)} fontes · {limitText(ents.max_api_keys)} chaves de API.</p>}
    {pendingPayment && <p role="status" data-testid="payment-pending" className="mt-4 flex items-start gap-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900"><Clock3 size={16} className="mt-0.5 shrink-0" aria-hidden="true" />{pendingPayment}</p>}
    {message && <p role={message.tone === "error" ? "alert" : "status"} aria-busy={confirming} data-testid="plan-message" data-pending={confirming ? "true" : undefined} className={`mt-4 rounded-md px-3 py-2 text-sm ${message.tone === "error" ? "bg-rose-50 text-rose-800" : "bg-sage text-ink"}`}>{message.text}</p>}
    {blockers.length > 0 && <ul data-testid="downgrade-blockers" className="mt-2 list-disc space-y-1 pl-5 text-sm text-rose-800">{blockers.map((item) => <li key={item}>{item}</li>)}</ul>}
    {!legacy && (owner ? <div className="mt-5 space-y-4">
      <div className="flex flex-wrap gap-3">
        {personal && <button type="button" className={btn("primary")} onClick={() => setUpgrade(true)} data-testid="upgrade-open"><Building2 size={16} aria-hidden="true" />Transformar em empresa</button>}
        {!personal && <button type="button" className={btn("primary")} onClick={() => setSubscribe((value) => !value)} aria-expanded={subscribe}>Assinar</button>}
        {(!personal || billing?.subscription) && <button type="button" className={btn("secondary")} disabled={busy !== null} onClick={() => { void billingCall("portal"); }} data-testid="billing-portal">{busy === "portal" ? "Abrindo…" : "Gerenciar cobrança"}</button>}
        {!personal && <button type="button" className={btn("ghost")} disabled={busy !== null} onClick={() => { void downgrade(); }}>{busy === "downgrade" ? "Convertendo…" : "Voltar para conta pessoal"}</button>}
      </div>
      {!personal && subscribe && <div className="space-y-3 rounded-md border border-line-soft p-4"><PlanPicker plans={plans} planKey={planKey} onPlanKey={setPlanKey} seats={seats} onSeats={setSeats} interval={interval} onInterval={setInterval} disabled={busy !== null} /><button type="button" className={btn("primary")} disabled={busy !== null} onClick={() => { void billingCall("checkout"); }}>{busy === "checkout" ? "Abrindo…" : "Continuar para o pagamento"}</button></div>}
      {billing?.billing_configured && <InvoiceList companyId={company.id} refreshKey={invoicesKey} />}
    </div> : <p className="mt-4 text-sm text-muted-foreground">Somente o responsável altera o plano e a cobrança.</p>)}
    {upgrade && <PlanDialog title="Transformar em empresa" onClose={() => setUpgrade(false)}><UpgradeToBusinessForm company={company} onDone={() => { setUpgrade(false); setNotice?.(upgradeDoneNotice(company)); load(); }} /></PlanDialog>}
  </section>;
}
