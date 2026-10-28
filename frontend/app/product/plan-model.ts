// Lógica pura dos tipos de conta (Pessoal/Empresa), planos e erros de plano. Sem React nem fetch — testável com node:test.
// Contrato: docs/contas-pessoal-empresa.md §14 e ADR-0022.

export type AccountType = "personal" | "business";
export type PlanKeyValue = "personal_trial" | "personal_basic" | "personal_pro" | "business_trial" | "business_team" | "business_scale" | "legacy" | "expired";
export type EntitlementSource = "comp" | "subscription" | "trial" | "legacy" | "expired";
export type Entitlements = {
  can_have_members: boolean; max_members: number | null; max_spaces: number | null; max_automations: number | null; max_api_keys: number | null;
  max_data_sources: number | null; mcp_enabled: boolean; public_api_enabled: boolean; webhooks_enabled: boolean; audit_panel_enabled: boolean;
  sso_enabled: boolean; allowed_providers: string[] | null;
};
/** Bloco de plano devolvido por GET /organizations, POST /organizations, GET /me e upgrade/downgrade. Opcional: ausente ⇒ tratado como legado. */
export type PlanBlock = {
  account_type?: AccountType; plan_key?: PlanKeyValue; entitlement_source?: EntitlementSource; trial_ends_at?: string | null; read_only?: boolean; entitlements?: Entitlements;
};

export const PLAN_ERROR_EVENT = "arquivio:plan-error";
export const PLAN_CHANGED_EVENT = "arquivio:plan-changed";

/** Códigos que abrem o diálogo único de upgrade. `personal_org_limit`, `billing_not_configured` e `downgrade_blocked` são tratados no próprio formulário. */
export const PLAN_ERROR_CODES = ["personal_no_members", "seat_limit", "trial_expired", "read_only", "space_limit", "automation_limit", "api_key_limit", "data_source_limit", "active_document_limit", "feature_unavailable", "provider_unavailable", "usage_limit"] as const;
export type PlanErrorCode = (typeof PLAN_ERROR_CODES)[number];
export type PlanErrorInfo = { code: PlanErrorCode; status: number; detail: string; limit: number | null; used: number | null; upgradeTo: string | null };

const isPlanErrorCode = (value: unknown): value is PlanErrorCode => typeof value === "string" && (PLAN_ERROR_CODES as readonly string[]).includes(value);
const numberOrNull = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : null;

/** Extrai o erro de plano de uma resposta HTTP (402/403/429 com `code`), ou null para qualquer outro erro. */
export function planErrorFromResponse(status: number, body: unknown): PlanErrorInfo | null {
  if (status !== 402 && status !== 403 && status !== 429) return null;
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (!isPlanErrorCode(record.code)) return null;
  // usage_limit é 429; os demais 402/403. Um código fora do seu status é ignorado.
  if ((record.code === "usage_limit") !== (status === 429)) return null;
  return { code: record.code, status, detail: typeof record.detail === "string" ? record.detail : "", limit: numberOrNull(record.limit), used: numberOrNull(record.used), upgradeTo: typeof record.upgrade_to === "string" ? record.upgrade_to : null };
}

export const isLegacyPlan = (plan: PlanBlock | null | undefined) => !plan || !plan.account_type || plan.entitlement_source === "legacy" || plan.plan_key === "legacy";
export const accountTypeLabel = (type: AccountType | undefined) => type === "business" ? "Empresa" : type === "personal" ? "Pessoal" : null;
export const isPersonal = (plan: PlanBlock | null | undefined) => plan?.account_type === "personal";

export const PLAN_TITLES: Record<string, string> = {
  personal_trial: "Pessoal — teste", personal_basic: "Pessoal Básico", personal_pro: "Pessoal Pro", business_trial: "Empresa — teste",
  business_team: "Empresa Team", business_scale: "Empresa Scale", legacy: "Plano atual (legado)", expired: "Encerrado",
};
export const planTitle = (key: string | null | undefined) => (key && PLAN_TITLES[key]) || "Plano";
export const sourceLabel = (source: EntitlementSource | undefined) => ({ comp: "Cortesia", subscription: "Assinatura", trial: "Teste grátis", legacy: "Conta anterior aos planos", expired: "Encerrado" } as Record<string, string>)[source ?? ""] ?? "—";

/** Dias inteiros (arredondados para cima) até `endsAt`; null se não houver data válida. Nunca negativo. */
export function daysLeft(endsAt: string | null | undefined, now: number = Date.now()): number | null {
  if (!endsAt) return null;
  const end = Date.parse(endsAt);
  if (Number.isNaN(end)) return null;
  return Math.max(0, Math.ceil((end - now) / 86_400_000));
}

export type PlanLabelKind = "trial" | "read_only" | "payment_pending";
/** `text` = pill do header; `short` = versão compacta (mobile); `title` = tooltip; `aria` = frase completa para leitor de tela. */
export type PlanLabel = { kind: PlanLabelKind; days: number | null; text: string; short: string; title: string; aria: string };
const labelDate = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
/**
 * Label discreto do header. Aparece em trial (com data), somente-leitura de teste encerrado e pagamento pendente (assinatura em read_only).
 * Contas legado e cortesia (comp) nunca veem; assinatura em dia também não.
 */
export function planLabel(plan: PlanBlock | null | undefined, now: number = Date.now()): PlanLabel | null {
  if (!plan || isLegacyPlan(plan)) return null;
  if (plan.entitlement_source === "comp") return null;
  if (plan.entitlement_source === "subscription") {
    if (!plan.read_only) return null;
    const title = "Somente leitura — regularize o pagamento para voltar a editar";
    return { kind: "payment_pending", days: null, text: "Pagamento pendente", short: "Pagamento", title, aria: `Pagamento pendente. ${title}` };
  }
  if (plan.read_only) {
    const title = "Somente leitura — assine para voltar a editar";
    return { kind: "read_only", days: null, text: "Teste encerrado", short: "Encerrado", title, aria: `Teste encerrado. ${title}` };
  }
  if (plan.entitlement_source !== "trial") return null;
  const days = daysLeft(plan.trial_ends_at, now);
  if (days === null) return null;
  const text = days === 0 ? "Teste termina hoje" : days === 1 ? "Teste · 1 dia" : `Teste · ${days} dias`;
  const when = days === 0 ? "termina hoje" : days === 1 ? "termina em 1 dia" : `termina em ${days} dias`;
  const date = plan.trial_ends_at ? ` (${labelDate(plan.trial_ends_at)})` : "";
  return { kind: "trial", days, text, short: days === 0 ? "Hoje" : `${days}d`, title: `Seu teste termina em ${labelDate(plan.trial_ends_at!)}`, aria: `Seu teste ${when}${date}` };
}

export type PlanDialogCopy = { title: string; message: string; usage: string | null; cta: "upgrade" | "plans" | "none"; ctaLabel: string };
const formatLimit = (limit: number | null, used: number | null) => limit === null ? null : used === null ? `Limite do plano: ${limit}` : `${used} de ${limit} em uso`;

/** Texto do diálogo de upgrade a partir do erro e do contexto da organização. */
export function planDialogCopy(info: PlanErrorInfo, context: { plan?: PlanBlock | null; role?: string }): PlanDialogCopy {
  const personal = isPersonal(context.plan);
  const owner = context.role === "owner";
  const usage = formatLimit(info.limit, info.used);
  const upgradeCta = personal && owner ? { cta: "upgrade" as const, ctaLabel: "Transformar em empresa" } : owner || context.role === "admin" ? { cta: "plans" as const, ctaLabel: "Ver planos" } : { cta: "none" as const, ctaLabel: "" };
  const ask = owner ? "" : " Peça ao responsável pela organização para ajustar o plano.";
  switch (info.code) {
    case "personal_no_members":
      return { title: "Contas pessoais não têm equipe", message: "Para convidar pessoas, transforme esta conta em uma conta de empresa. Seus dados, fontes e histórico continuam exatamente como estão." + ask, usage: null, ...upgradeCta };
    case "seat_limit":
      return { title: "Limite de assentos atingido", message: "O plano atual não comporta mais pessoas. Aumente os assentos ou mude de plano para convidar mais gente." + ask, usage, ...(owner || context.role === "admin" ? { cta: "plans" as const, ctaLabel: "Ver planos" } : { cta: "none" as const, ctaLabel: "" }) };
    case "trial_expired":
      return { title: "Seu teste terminou", message: "A organização está em modo somente leitura: você ainda consulta tudo, mas não pode criar nem alterar. Assine um plano para voltar a editar." + ask, usage: null, ...(owner || context.role === "admin" ? { cta: "plans" as const, ctaLabel: "Ver planos" } : { cta: "none" as const, ctaLabel: "" }) };
    case "read_only":
      return { title: "Organização em somente leitura", message: "Não há assinatura ativa, então alterações estão bloqueadas. Regularize o plano para voltar a editar." + ask, usage: null, ...(owner || context.role === "admin" ? { cta: "plans" as const, ctaLabel: "Ver planos" } : { cta: "none" as const, ctaLabel: "" }) };
    case "space_limit": return { title: "Limite de Espaços atingido", message: "O plano atual não permite criar mais Espaços." + ask, usage, ...upgradeCta };
    case "automation_limit": return { title: "Limite de automações atingido", message: "O plano atual não permite criar mais automações." + ask, usage, ...upgradeCta };
    case "api_key_limit": return { title: "Limite de chaves de API atingido", message: "O plano atual não permite criar mais chaves de API." + ask, usage, ...upgradeCta };
    case "data_source_limit": return { title: "Limite de fontes conectadas atingido", message: "O plano atual não permite conectar mais fontes de dados." + ask, usage, ...upgradeCta };
    case "active_document_limit": return { title: "Limite de documentos ativos atingido", message: "A organização chegou ao teto de documentos indexados do plano." + ask, usage, ...upgradeCta };
    case "feature_unavailable": return { title: "Recurso fora do seu plano", message: "A API pública e o MCP não estão incluídos no plano atual." + ask, usage: null, ...upgradeCta };
    case "provider_unavailable": return { title: "Conector fora do seu plano", message: "Este conector não está disponível no plano atual." + ask, usage: null, ...upgradeCta };
    case "usage_limit": return { title: "Limite mensal de uso atingido", message: "A cota mensal de processamento da organização acabou. Ela volta a zerar no início do próximo mês, ou você pode mudar de plano." + ask, usage, ...upgradeCta };
  }
}

export type UpgradeIntro = { text: string; blocked: boolean };
const dayMonth = (iso: string) => new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "2-digit" });
/**
 * O que o upgrade pessoal → empresa faz em cada estado (backend `upgrade_to_business`: mesma org, projeção recalculada, nada reinicia).
 * trial vivo → continua até a mesma data; assinatura → é migrada; cortesia pessoal → o backend recusa (409 comp_type_mismatch);
 * legado → segue sem limites; expirado → continua somente leitura (o teste NÃO reinicia).
 */
export function upgradeIntro(plan: PlanBlock | null | undefined, now: number = Date.now()): UpgradeIntro {
  const source = plan?.entitlement_source;
  if (source === "comp") return { blocked: true, text: "Esta conta tem uma cortesia de plano pessoal ativa. Ela precisa ser revogada antes da mudança — fale com a gente." };
  if (source === "subscription") return { blocked: false, text: "Sua assinatura atual será ajustada para o plano de empresa escolhido." };
  if (isLegacyPlan(plan)) return { blocked: false, text: "Sua conta continua sem os novos limites de plano." };
  const end = plan?.trial_ends_at ? Date.parse(plan.trial_ends_at) : NaN;
  if (source === "trial" && !plan?.read_only && !Number.isNaN(end) && end > now) return { blocked: false, text: `Seu teste continua até ${dayMonth(plan!.trial_ends_at!)}, sem cartão.` };
  return { blocked: false, text: "O teste desta conta já terminou: ela continua em somente leitura até você assinar um plano de empresa. A mudança não reinicia o teste." };
}
/** Aviso após o upgrade, na mesma verdade de `upgradeIntro`. */
export function upgradeDoneNotice(plan: PlanBlock | null | undefined, now: number = Date.now()): string {
  const intro = upgradeIntro(plan, now);
  return intro.blocked ? "" : `Conta transformada em empresa. ${intro.text}`;
}

/** Qual plano pré-selecionar no formulário de upgrade, a partir de `upgrade_to`/intenção. */
export const defaultBusinessPlan = (hint: string | null | undefined): "business_team" | "business_scale" => hint === "business_scale" ? "business_scale" : "business_team";

// ── Intenção de cadastro (?tipo=pessoal|empresa&plano=<plan_key>) ─────────────
export const SIGNUP_INTENT_KEY = "arquivio:signup-intent";
const INTENT_TTL_MS = 48 * 3_600_000;
const SELLABLE_PLANS = ["personal_basic", "personal_pro", "business_team", "business_scale"];
export type SignupIntent = { tipo?: "pessoal" | "empresa"; plano?: string };

/** Lê tipo/plano de uma query string; null se nada válido. O plano implica o tipo quando ele falta. */
export function parseSignupIntent(search: string | URLSearchParams): SignupIntent | null {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  const tipo = params.get("tipo");
  const plano = params.get("plano");
  const intent: SignupIntent = {};
  if (tipo === "pessoal" || tipo === "empresa") intent.tipo = tipo;
  if (plano && SELLABLE_PLANS.includes(plano)) { intent.plano = plano; intent.tipo ??= plano.startsWith("business_") ? "empresa" : "pessoal"; }
  return intent.tipo || intent.plano ? intent : null;
}
export const intentAccountType = (intent: SignupIntent | null | undefined): AccountType => intent?.tipo === "empresa" ? "business" : "personal";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;
const safeStorage = (): StorageLike | null => { try { return typeof window === "undefined" ? null : window.localStorage; } catch { return null; } };

/** Guarda a intenção (localStorage com validade: o link de verificação de e-mail pode abrir em outra aba). */
export function saveSignupIntent(intent: SignupIntent, store: StorageLike | null = safeStorage(), now: number = Date.now()) {
  try { store?.setItem(SIGNUP_INTENT_KEY, JSON.stringify({ ...intent, at: now })); } catch { /* storage indisponível */ }
}
export function readSignupIntent(store: StorageLike | null = safeStorage(), now: number = Date.now()): SignupIntent | null {
  try {
    const raw = store?.getItem(SIGNUP_INTENT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { tipo?: string; plano?: string; at?: number };
    if (typeof parsed.at !== "number" || now - parsed.at > INTENT_TTL_MS) { store?.removeItem(SIGNUP_INTENT_KEY); return null; }
    const params = new URLSearchParams();
    if (parsed.tipo) params.set("tipo", parsed.tipo);
    if (parsed.plano) params.set("plano", parsed.plano);
    return parseSignupIntent(params);
  } catch { return null; }
}
export function clearSignupIntent(store: StorageLike | null = safeStorage()) { try { store?.removeItem(SIGNUP_INTENT_KEY); } catch { /* storage indisponível */ } }

// ── Dinheiro e catálogo (GET /plans) ──────────────────────────────────────────
export type PublicPlan = {
  plan_key: string; account_type: AccountType; title: string; price_month_cents: number | null; price_year_cents: number | null; currency: string;
  included_seats: number | null; max_seats: number | null; extra_seat_month_cents: number | null; extra_seat_year_cents: number | null;
  can_have_members: boolean; limits: Record<string, number | null>; features: Record<string, unknown>;
};
export type PlansResponse = { currency: string; trial_days: number; trial_requires_card: boolean; billing_configured: boolean; plans: PublicPlan[] };
export const formatCents = (cents: number | null | undefined, currency = "BRL") => cents === null || cents === undefined ? "—" : new Intl.NumberFormat("pt-BR", { style: "currency", currency, minimumFractionDigits: cents % 100 === 0 ? 0 : 2 }).format(cents / 100);

export type BillingState = PlanBlock & {
  billing_configured: boolean; provider: string | null; /** Já existe cliente no provedor (Stripe). Ausente em respostas antigas ⇒ false. */ has_billing_customer?: boolean; legacy: boolean; seats_used: number | null; comp_expires_at: string | null; grace_ends_at: string | null;
  subscription: { status: string; plan_key: string; interval: string | null; seats: number | null; current_period_end: string | null; cancel_at_period_end: boolean; coupon_code: string | null; discount_summary: string | null } | null;
  account_type_changed_at: string | null;
};

export const BILLING_SOON_MESSAGE = "Assinatura online em breve — fale com a gente para assinar agora.";
export const DOWNGRADE_BLOCKER_LABEL: Record<string, string> = {
  members: "Remova os outros membros da organização.",
  pending_invitations: "Cancele os convites pendentes.",
  cooldown: "A conta mudou de tipo recentemente; aguarde alguns dias para voltar.",
};
export const downgradeBlockers = (blockers: unknown): string[] => Array.isArray(blockers) ? blockers.filter((item): item is string => typeof item === "string").map((item) => DOWNGRADE_BLOCKER_LABEL[item] ?? item) : [];

// ── Retorno do Checkout/Portal e faturas (GET …/billing/invoices) ─────────────
/** Status de assinatura do provedor (iguais aos do backend `SUBSCRIPTION_STATUSES`) em pt-BR. */
export const SUBSCRIPTION_STATUS_LABELS: Record<string, string> = {
  active: "ativa", trialing: "em teste", past_due: "com pagamento atrasado", unpaid: "não paga", paused: "pausada",
  incomplete: "aguardando pagamento", incomplete_expired: "expirada sem pagamento", canceled: "cancelada",
};
export const subscriptionStatusLabel = (status: string | null | undefined) => (status && SUBSCRIPTION_STATUS_LABELS[status]) || status || "—";

/** Parâmetro deixado pelo backend nas URLs de retorno: `?checkout=success|canceled` (Checkout) e `?billing=portal` (Portal). */
export type BillingReturn = "checkout_success" | "checkout_canceled" | "portal";
export function billingReturnFrom(search: string | URLSearchParams): BillingReturn | null {
  const params = typeof search === "string" ? new URLSearchParams(search) : search;
  const checkout = params.get("checkout");
  if (checkout === "success") return "checkout_success";
  if (checkout === "canceled") return "checkout_canceled";
  return params.get("billing") === "portal" ? "portal" : null;
}
/** Remove só os parâmetros de retorno, preservando o resto da URL (para `history.replaceState`). */
export function stripBillingReturn(href: string): string {
  const url = new URL(href);
  url.searchParams.delete("checkout");
  url.searchParams.delete("billing");
  return `${url.pathname}${url.search}${url.hash}`;
}

/** Poll curto de GET …/billing depois do Checkout: o acesso só muda quando o webhook chega. */
export const CHECKOUT_POLL_INTERVAL_MS = 2_000;
export const CHECKOUT_POLL_MAX_MS = 20_000;
const PAID_STATUSES = new Set(["active", "trialing"]);
export type CheckoutPollOutcome = "active" | "pending" | "timeout";
/** `active` quando a assinatura já está ativa/em teste; `timeout` ao estourar o prazo; senão `pending` (continua). */
export function checkoutPollOutcome(state: Pick<BillingState, "subscription"> | null | undefined, elapsedMs: number, maxMs: number = CHECKOUT_POLL_MAX_MS): CheckoutPollOutcome {
  if (state?.subscription && PAID_STATUSES.has(state.subscription.status)) return "active";
  return elapsedMs >= maxMs ? "timeout" : "pending";
}
export const CHECKOUT_RETURN_MESSAGES = {
  pending: "Confirmando seu pagamento…",
  active: "Assinatura confirmada. Obrigado!",
  timeout: "Recebemos seu retorno do pagamento, mas a confirmação ainda não chegou. Ela pode levar alguns minutos — atualize esta página em instantes.",
  canceled: "Pagamento não concluído. Nenhuma cobrança foi feita.",
} as const;

export type InvoiceSummary = {
  id: string; number: string | null; status: string | null; total: number; currency: string; created: string;
  hosted_invoice_url: string | null; invoice_pdf: string | null;
};
export const INVOICE_STATUS_LABELS: Record<string, string> = { draft: "Rascunho", open: "Em aberto", paid: "Paga", uncollectible: "Não cobrável", void: "Anulada" };
export const invoiceStatusLabel = (status: string | null | undefined) => (status && INVOICE_STATUS_LABELS[status]) || "—";
/** Total da fatura em centavos → moeda (sempre com centavos: "R$ 49,90"). Moeda desconhecida cai para BRL. */
export function formatInvoiceTotal(cents: number, currency: string | null | undefined = "BRL"): string {
  const code = (currency || "BRL").toUpperCase();
  try { return new Intl.NumberFormat("pt-BR", { style: "currency", currency: code }).format(cents / 100); }
  catch { return new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(cents / 100); }
}
export const invoiceDate = (iso: string) => { const time = Date.parse(iso); return Number.isNaN(time) ? "—" : new Date(time).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" }); };
export const invoiceTitle = (invoice: Pick<InvoiceSummary, "number">) => invoice.number ? `Fatura ${invoice.number}` : "Fatura";

/**
 * Pagamento pendente visível na seção de cobrança. Boleto/Pix voltam pelo `hosted_voucher_url` (não pelo success_url),
 * então o poll pós-Checkout não roda: basta GET …/billing mostrar a assinatura `incomplete`/`past_due`.
 */
export function pendingPaymentNotice(state: Pick<BillingState, "subscription"> | null | undefined): string | null {
  const status = state?.subscription?.status;
  if (status === "incomplete") return "Pagamento pendente — assim que o boleto/Pix for compensado, seu plano é ativado.";
  if (status === "past_due") return "Pagamento pendente — regularize em Gerenciar cobrança para manter o plano ativo.";
  return null;
}

// ── Portal e plano pessoal ────────────────────────────────────────────────────
/** O portal só abre quando a organização já tem cliente no provedor ou assinatura; antes disso o backend responde 409 subscription_required. */
export const canOpenPortal = (state: Pick<BillingState, "subscription"> & { has_billing_customer?: boolean } | null | undefined): boolean =>
  Boolean(state && (state.has_billing_customer === true || state.subscription != null));

/** Planos pessoais vendáveis, na ordem do catálogo (básico antes de pro); sem catálogo, lista vazia. */
export const PERSONAL_SELLABLE_KEYS = ["personal_basic", "personal_pro"] as const;
export const personalPlanOptions = (plans: PlansResponse | null | undefined): PublicPlan[] =>
  PERSONAL_SELLABLE_KEYS.flatMap((key) => plans?.plans.filter((plan) => plan.plan_key === key && plan.account_type === "personal") ?? []);

const LIVE_SUBSCRIPTION_STATUSES = new Set(["active", "trialing", "past_due", "unpaid", "paused", "incomplete"]);
/** Assinatura que ainda ocupa a conta: novo Checkout duplicaria a cobrança, então a troca/gestão vai pelo portal. */
export const hasLiveSubscription = (state: Pick<BillingState, "subscription"> | null | undefined): boolean =>
  Boolean(state?.subscription && LIVE_SUBSCRIPTION_STATUSES.has(state.subscription.status));

/** Corpo do checkout pessoal: nunca envia price id; assentos sempre 1. Retorna null se o plano não é vendável para conta pessoal. */
export function personalCheckoutBody(planKey: string, interval: "month" | "year"): { plan_key: string; interval: "month" | "year"; seats: 1 } | null {
  return (PERSONAL_SELLABLE_KEYS as readonly string[]).includes(planKey) ? { plan_key: planKey, interval, seats: 1 } : null;
}
