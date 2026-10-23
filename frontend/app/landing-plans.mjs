/**
 * Catálogo de planos exibido na landing (preços, assentos e limites).
 *
 * ESPELHA o catálogo do backend (docs/contas-pessoal-empresa.md §2.3; o endpoint GET /plans está em
 * construção). Enquanto a LP não consome o endpoint, este é o ÚNICO lugar do frontend com preços e
 * limites: componentes da LP leem daqui e nunca escrevem valores em R$ no JSX. Ao mudar o catálogo
 * do backend, atualize este arquivo (o teste landing-plans.test.mjs guarda os valores aprovados).
 *
 * `key` = plan_key do backend; viaja no cadastro como `&plano=<key>`.
 * Valores em reais inteiros. `annual` é o total por ano; `extraSeatAnnual` idem por pessoa extra.
 */

/** @typedef {"personal_basic" | "personal_pro" | "business_team" | "business_scale"} PlanKey */
/** @typedef {"pessoal" | "empresa"} AccountKind */
/** @typedef {"monthly" | "annual"} BillingCycle */

export const TRIAL_DAYS = 14;
export const TRIAL_CTA = "Testar grátis por 14 dias"; // literal; o teste garante que bate com TRIAL_DAYS
export const BUSINESS_TRIAL_CTA = "Testar com minha empresa";
export const SALES_CTA = "Falar com vendas";
/** Canal de vendas provisório: o mesmo contato público da página de privacidade. Trocar quando houver canal próprio. */
export const SALES_HREF = "mailto:lagevitor.dev@gmail.com?subject=Arquivio%20para%20empresas";

/** @type {{ key: PlanKey; kind: AccountKind; name: string; audience: string; monthly: number; annual: number; seatsIncluded: number; seatsMax: number; extraSeatMonthly: number | null; extraSeatAnnual: number | null; limits: { documents: number; questionsPerMonth: number; sources: number; sourcesNote: string; spaces: number; automations: number; apiKeys: number; mcp: boolean; auditDays: number | null; support: string } }[]} */
export const PLANS = [
  {
    key: "personal_basic", kind: "pessoal", name: "Básico", audience: "Para organizar seus arquivos",
    monthly: 39, annual: 390, seatsIncluded: 1, seatsMax: 1, extraSeatMonthly: null, extraSeatAnnual: null,
    limits: { documents: 500, questionsPerMonth: 200, sources: 2, sourcesNote: "Google Drive e envio de arquivos", spaces: 1, automations: 3, apiKeys: 0, mcp: false, auditDays: null, support: "E-mail" },
  },
  {
    key: "personal_pro", kind: "pessoal", name: "Pro", audience: "Para uso individual intenso",
    monthly: 99, annual: 990, seatsIncluded: 1, seatsMax: 1, extraSeatMonthly: null, extraSeatAnnual: null,
    limits: { documents: 2000, questionsPerMonth: 600, sources: 5, sourcesNote: "inclui OneDrive e Notion", spaces: 3, automations: 10, apiKeys: 1, mcp: true, auditDays: null, support: "E-mail" },
  },
  {
    key: "business_team", kind: "empresa", name: "Team", audience: "Para times pequenos",
    monthly: 299, annual: 2990, seatsIncluded: 5, seatsMax: 15, extraSeatMonthly: 49, extraSeatAnnual: 490,
    limits: { documents: 3000, questionsPerMonth: 1000, sources: 10, sourcesNote: "todas as integrações", spaces: 25, automations: 20, apiKeys: 10, mcp: true, auditDays: 180, support: "E-mail prioritário" },
  },
  {
    key: "business_scale", kind: "empresa", name: "Scale", audience: "Para times em crescimento",
    monthly: 899, annual: 8990, seatsIncluded: 20, seatsMax: 100, extraSeatMonthly: 39, extraSeatAnnual: 390,
    limits: { documents: 20000, questionsPerMonth: 5000, sources: 30, sourcesNote: "todas as integrações", spaces: 200, automations: 100, apiKeys: 50, mcp: true, auditDays: 365, support: "Atendimento prioritário" },
  },
];

/** @param {AccountKind} kind */
export const plansOfKind = (kind) => PLANS.filter((plan) => plan.kind === kind);
/** @param {PlanKey} key */
export const planByKey = (key) => PLANS.find((plan) => plan.key === key);
export const isPlanKey = (value) => PLANS.some((plan) => plan.key === value);

/** "R$ 1.234" ou "R$ 32,50" (centavos só quando existem). */
export function formatBRL(value) {
  const hasCents = Math.round(value * 100) % 100 !== 0;
  return `R$ ${value.toLocaleString("pt-BR", { minimumFractionDigits: hasCents ? 2 : 0, maximumFractionDigits: 2 })}`;
}
export const formatInt = (value) => value.toLocaleString("pt-BR");

/** Preço de tabela no ciclo: total cobrado e equivalente mensal (para o anual). */
export function planPrice(plan, cycle) {
  return cycle === "annual" ? { total: plan.annual, perMonth: plan.annual / 12, unit: "/ano" } : { total: plan.monthly, perMonth: plan.monthly, unit: "/mês" };
}
export const extraSeatPrice = (plan, cycle) => (cycle === "annual" ? plan.extraSeatAnnual : plan.extraSeatMonthly);

/** Total de uma empresa com `seats` pessoas (base + extras). Retorna null fora do intervalo do plano. */
export function businessQuote(plan, seats, cycle = "monthly") {
  if (plan.kind !== "empresa" || seats < 1 || seats > plan.seatsMax) return null;
  const extras = Math.max(0, seats - plan.seatsIncluded);
  const base = cycle === "annual" ? plan.annual : plan.monthly;
  const extra = extraSeatPrice(plan, cycle) ?? 0;
  return { base, extras, extra, total: base + extras * extra };
}

/** Quanto o anual economiza sobre 12 mensalidades, em meses de preço. */
export const annualMonthsFree = (plan) => Math.round((plan.monthly * 12 - plan.annual) / plan.monthly);

/** Linhas de recursos exibidas em cada card, derivadas só dos dados acima. */
export function planFeatureLines(plan) {
  const l = plan.limits;
  const lines = [
    `${formatInt(l.documents)} documentos indexados`,
    `${formatInt(l.questionsPerMonth)} perguntas por mês${plan.kind === "empresa" ? " (de toda a empresa)" : ""}`,
    `${l.sources} fontes conectadas: ${l.sourcesNote}`,
    l.spaces === 1 ? "1 espaço" : `${formatInt(l.spaces)} espaços`,
    `${l.automations} automações`,
  ];
  if (l.apiKeys > 0) lines.push(`${l.apiKeys} ${l.apiKeys === 1 ? "chave" : "chaves"} de API${l.mcp ? " e acesso MCP" : ""}`);
  if (l.auditDays) lines.push(`Histórico de auditoria de ${l.auditDays} dias`);
  lines.push(`Suporte: ${l.support}`);
  return lines;
}

/** Linha de pessoas do card: "1 pessoa" ou "5 pessoas incluídas". */
export function planSeatLine(plan) {
  if (plan.kind === "pessoal") return "1 pessoa (conta individual)";
  return `${plan.seatsIncluded} pessoas incluídas`;
}

/**
 * Destino dos CTAs de cadastro: intenção em query (`tipo`, `plano`). O fluxo de signup ainda não lê esses
 * parâmetros (próxima onda); até lá o /login simplesmente os ignora.
 * @param {{ tipo?: AccountKind; plano?: PlanKey }} [intent]
 */
export function signupHref(intent) {
  const params = new URLSearchParams({ mode: "sign-up" });
  if (intent?.tipo === "pessoal" || intent?.tipo === "empresa") params.set("tipo", intent.tipo);
  if (intent?.plano && isPlanKey(intent.plano)) params.set("plano", intent.plano);
  return `/login?${params.toString()}`;
}
