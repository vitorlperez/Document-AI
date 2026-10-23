// Lógica pura da tela de staff "Plano e cortesia" (contrato: docs/contas-pessoal-empresa.md §14).
export const REASON_MAX = 240;
export const LIMIT_FIELDS = [
  ["max_members", "Máx. membros"], ["max_spaces", "Máx. Espaços"], ["max_automations", "Máx. automações"],
  ["max_api_keys", "Máx. chaves de API"], ["max_data_sources", "Máx. fontes de dados"], ["active_documents", "Documentos ativos"],
];
export const SOURCE_LABELS = { comp: "Cortesia", subscription: "Assinatura", trial: "Teste", legacy: "Legado", expired: "Expirada" };
export const ACCOUNT_LABELS = { personal: "Pessoal", business: "Empresa" };
/** Estados internos que não existem no catálogo vendido (GET /plans só traz os 4 planos à venda). */
export const STATE_PLAN_TITLES = { personal_trial: "Teste Pessoal", business_trial: "Teste Empresa", legacy: "Legado", expired: "Expirado" };
/** Nome amigável do plano: estados internos conhecidos, depois o título do catálogo (GET /plans), por fim a própria chave. */
export function staffPlanTitle(planKey, catalog) {
  if (!planKey) return "—";
  if (STATE_PLAN_TITLES[planKey]) return STATE_PLAN_TITLES[planKey];
  return (catalog ?? []).find((plan) => plan.plan_key === planKey)?.title ?? planKey;
}
/** Só o papel admin concede/estende/revoga cortesias; support e papel desconhecido veem em modo somente leitura. */
export const canManageComps = (staffRole) => staffRole === "admin";
export const sourceLabel = (source) => SOURCE_LABELS[source] ?? source ?? "—";
export const accountLabel = (type) => ACCOUNT_LABELS[type] ?? type ?? "—";

/** Planos concedíveis como cortesia: só os do tipo da org (o backend também recusa com 422). */
export function plansForAccountType(plans, accountType) {
  return (plans ?? []).filter((plan) => plan.account_type === accountType);
}

/** "2026-12-31" -> ISO ao fim do dia local (UTC) para a validade nunca cair antes do dia escolhido. */
export function expiryToIso(dateValue) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dateValue ?? "")) return null;
  const date = new Date(`${dateValue}T23:59:59.000Z`);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** Campos vazios = sem override; "ilimitado" = null explícito ("unlimited"); número inteiro >= 0. Erro => { error }. */
export function buildLimitsOverride(raw) {
  const out = {};
  for (const [key, label] of LIMIT_FIELDS) {
    const text = String(raw?.[key] ?? "").trim().toLowerCase();
    if (!text) continue;
    if (text === "ilimitado" || text === "unlimited") { out[key] = "unlimited"; continue; }
    if (!/^\d+$/.test(text)) return { error: `${label}: use um número inteiro ou "ilimitado".` };
    out[key] = Number(text);
  }
  return { value: Object.keys(out).length ? out : null };
}

/** Corpo do POST /comps ou erro de validação em PT-BR. */
export function buildCompBody({ planKey, reason, permanent, expiresDate, limits, now = new Date() }) {
  if (!planKey) return { error: "Escolha um plano." };
  const trimmed = (reason ?? "").trim();
  if (!trimmed) return { error: "Informe o motivo da cortesia." };
  if (trimmed.length > REASON_MAX) return { error: `O motivo pode ter no máximo ${REASON_MAX} caracteres.` };
  const body = { plan_key: planKey, reason: trimmed };
  if (permanent) body.permanent = true;
  else {
    const iso = expiryToIso(expiresDate);
    if (!iso) return { error: "Informe a validade ou marque como permanente." };
    if (new Date(iso) <= now) return { error: "A validade precisa ser uma data futura." };
    body.expires_at = iso;
  }
  const override = buildLimitsOverride(limits);
  if (override.error) return { error: override.error };
  if (override.value) body.limits_override = override.value;
  return { body };
}

export function extendBody(expiresDate, now = new Date()) {
  const iso = expiryToIso(expiresDate);
  if (!iso) return { error: "Informe a nova validade." };
  if (new Date(iso) <= now) return { error: "A validade precisa ser uma data futura." };
  return { body: { expires_at: iso } };
}

export const isSupportDenied = (status) => status === 403;

export function formatDate(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toLocaleDateString("pt-BR");
}

export function seatsLabel(state) {
  const eff = state?.effective ?? {};
  const used = state?.seats_used;
  const max = eff.max_members ?? state?.entitlements?.max_members;
  if (max === null || max === undefined) return "ilimitados";
  return typeof used === "number" ? `${used} / ${max}` : String(max);
}

export function compWarningMessage(warning) {
  return warning === "active_subscription"
    ? "Esta organização tem assinatura ativa: a cortesia vale para o acesso, mas NÃO cancela nem reembolsa a cobrança."
    : null;
}
