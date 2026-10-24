import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  BILLING_SOON_MESSAGE, clearSignupIntent, daysLeft, defaultBusinessPlan, downgradeBlockers, formatCents, intentAccountType, parseSignupIntent, planLabel, planDialogCopy, planErrorFromResponse, readSignupIntent, saveSignupIntent, upgradeDoneNotice, upgradeIntro,
} from "../app/product/plan-model.ts";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const memory = () => { const map = new Map(); return { getItem: (k) => map.get(k) ?? null, setItem: (k, v) => map.set(k, v), removeItem: (k) => map.delete(k) }; };
const NOW = Date.parse("2026-10-23T12:00:00Z");

test("planErrorFromResponse reconhece só 402/403/429 com code de plano no status certo", () => {
  const body = { detail: "x", code: "seat_limit", limit: 5, used: 5, upgrade_to: "business_scale" };
  assert.deepEqual(planErrorFromResponse(402, body), { code: "seat_limit", status: 402, detail: "x", limit: 5, used: 5, upgradeTo: "business_scale" });
  assert.equal(planErrorFromResponse(500, body), null);
  assert.equal(planErrorFromResponse(402, { code: "personal_org_limit" }), null, "tratado no formulário, não no diálogo");
  assert.equal(planErrorFromResponse(403, { code: "billing_not_configured" }), null);
  assert.equal(planErrorFromResponse(402, { code: "usage_limit" }), null, "usage_limit só vale com 429");
  assert.equal(planErrorFromResponse(429, { code: "usage_limit", detail: "organization usage limit reached", limit: 10, used: 10, upgrade_to: "personal_pro" })?.upgradeTo, "personal_pro");
  assert.equal(planErrorFromResponse(403, { detail: "not allowed" }), null);
  assert.equal(planErrorFromResponse(403, null), null);
});

test("label do header: trial mostra dias, teste encerrado e pagamento pendente alertam; legacy/comp/assinatura em dia não veem", () => {
  const trial = { account_type: "personal", plan_key: "personal_trial", entitlement_source: "trial", trial_ends_at: "2026-10-26T12:00:00Z", read_only: false };
  const t3 = planLabel(trial, NOW);
  assert.equal(t3.kind, "trial"); assert.equal(t3.days, 3); assert.equal(t3.text, "Teste · 3 dias"); assert.equal(t3.short, "3d");
  assert.equal(t3.title, "Seu teste termina em 26/10"); assert.match(t3.aria, /^Seu teste termina em 3 dias/);
  assert.equal(planLabel({ ...trial, trial_ends_at: "2026-10-24T11:00:00Z" }, NOW).text, "Teste · 1 dia");
  assert.equal(planLabel({ ...trial, trial_ends_at: "2026-10-23T13:00:00Z" }, NOW).days, 1);
  const today = planLabel({ ...trial, trial_ends_at: "2026-10-23T12:00:00Z" }, NOW);
  assert.equal(today.text, "Teste termina hoje"); assert.equal(today.short, "Hoje");
  const expired = { account_type: "business", plan_key: "expired", entitlement_source: "expired", trial_ends_at: "2026-10-01T00:00:00Z", read_only: true };
  const ro = planLabel(expired, NOW);
  assert.equal(ro.kind, "read_only"); assert.equal(ro.text, "Teste encerrado"); assert.equal(ro.title, "Somente leitura — assine para voltar a editar");
  const pending = planLabel({ account_type: "business", plan_key: "business_team", entitlement_source: "subscription", read_only: true }, NOW);
  assert.equal(pending.kind, "payment_pending"); assert.equal(pending.text, "Pagamento pendente"); assert.match(pending.aria, /^Pagamento pendente\./);
  assert.equal(planLabel({ account_type: "business", plan_key: "business_team", entitlement_source: "subscription", read_only: false }, NOW), null);
  assert.equal(planLabel({ account_type: "business", plan_key: "legacy", entitlement_source: "legacy", read_only: false }, NOW), null);
  assert.equal(planLabel({ account_type: "business", plan_key: "business_team", entitlement_source: "comp", trial_ends_at: "2026-10-25T00:00:00Z" }, NOW), null);
  assert.equal(planLabel({ id: "x" }, NOW), null, "resposta sem bloco de plano = legado");
  assert.equal(planLabel(undefined, NOW), null);
});

test("daysLeft arredonda para cima e nunca é negativo", () => {
  assert.equal(daysLeft(null, NOW), null);
  assert.equal(daysLeft("lixo", NOW), null);
  assert.equal(daysLeft("2026-10-01T00:00:00Z", NOW), 0);
  assert.equal(daysLeft("2026-11-06T12:00:00Z", NOW), 14);
});

test("diálogo: conta pessoal convidando vira CTA 'Transformar em empresa' para o dono; membro não recebe CTA", () => {
  const info = planErrorFromResponse(403, { code: "personal_no_members", detail: "x", upgrade_to: "business_team" });
  const personal = { account_type: "personal" };
  assert.equal(planDialogCopy(info, { plan: personal, role: "owner" }).cta, "upgrade");
  assert.equal(planDialogCopy(info, { plan: personal, role: "owner" }).ctaLabel, "Transformar em empresa");
  assert.equal(planDialogCopy(info, { plan: personal, role: "member" }).cta, "none");
  const seat = planErrorFromResponse(402, { code: "seat_limit", limit: 5, used: 5, upgrade_to: "business_scale" });
  const copy = planDialogCopy(seat, { plan: { account_type: "business" }, role: "owner" });
  assert.equal(copy.usage, "5 de 5 em uso");
  assert.deepEqual([copy.cta, copy.ctaLabel], ["plans", "Ver planos"]);
  const trial = planDialogCopy(planErrorFromResponse(402, { code: "trial_expired" }), { plan: { account_type: "business" }, role: "admin" });
  assert.equal(trial.cta, "plans");
  const limit = planDialogCopy(planErrorFromResponse(402, { code: "space_limit", limit: 3, used: 3 }), { plan: personal, role: "owner" });
  assert.equal(limit.cta, "upgrade");
});

test("defaultBusinessPlan respeita upgrade_to=business_scale e cai para team", () => {
  assert.equal(defaultBusinessPlan("business_scale"), "business_scale");
  assert.equal(defaultBusinessPlan(null), "business_team");
  assert.equal(defaultBusinessPlan("personal_pro"), "business_team");
});

test("intenção de cadastro: parse, plano implica tipo, valores inválidos são ignorados", () => {
  assert.deepEqual(parseSignupIntent("?mode=sign-up&tipo=empresa&plano=business_scale"), { tipo: "empresa", plano: "business_scale" });
  assert.deepEqual(parseSignupIntent("plano=personal_pro"), { tipo: "pessoal", plano: "personal_pro" });
  assert.deepEqual(parseSignupIntent("tipo=empresa"), { tipo: "empresa" });
  assert.equal(parseSignupIntent("tipo=admin&plano=legacy"), null);
  assert.equal(parseSignupIntent("mode=sign-up"), null);
  assert.equal(intentAccountType({ tipo: "empresa" }), "business");
  assert.equal(intentAccountType({ tipo: "pessoal" }), "personal");
  assert.equal(intentAccountType(null), "personal");
});

test("intenção persiste entre abas (storage), expira em 48h e é limpa após criar a organização", () => {
  const store = memory();
  saveSignupIntent({ tipo: "empresa", plano: "business_team" }, store, NOW);
  assert.deepEqual(readSignupIntent(store, NOW + 3_600_000), { tipo: "empresa", plano: "business_team" });
  assert.equal(readSignupIntent(store, NOW + 49 * 3_600_000), null);
  assert.equal(store.getItem("arquivio:signup-intent"), null, "expirada é removida");
  saveSignupIntent({ tipo: "pessoal" }, store, NOW);
  clearSignupIntent(store);
  assert.equal(readSignupIntent(store, NOW), null);
  assert.equal(readSignupIntent(null, NOW), null, "sem storage não quebra");
});

test("formatadores: preço em centavos e bloqueios do downgrade", () => {
  assert.match(formatCents(4900), /49/);
  assert.equal(formatCents(null), "—");
  assert.equal(downgradeBlockers(["members", "x"]).length, 2);
  assert.deepEqual(downgradeBlockers(undefined), []);
  assert.match(BILLING_SOON_MESSAGE, /em breve/);
});

test("contrato de fiação: api() dispara o diálogo único, onboarding envia account_type, login guarda a intenção", () => {
  const types = read("product/types-and-api.tsx");
  assert.match(types, /planErrorFromResponse\(response\.status, body\)/);
  assert.match(types, /PLAN_ERROR_EVENT/);
  assert.match(types, /Company = \{[^}]*\} & PlanBlock/);
  const onboarding = read("product/auth-screens.tsx");
  assert.match(onboarding, /account_type: accountType/);
  assert.match(onboarding, /personal_org_limit/);
  assert.match(onboarding, /Para mim/);
  assert.match(onboarding, /Para minha empresa/);
  assert.match(read("product/custom-login.tsx"), /saveSignupIntent\(intent\)/);
  const shell = read("product/shell.tsx");
  assert.match(shell, /<PlanLabel /);
  assert.doesNotMatch(shell, /PlanBanner/);
  assert.match(shell, /<PlanErrorHost /);
  assert.match(read("product/admin-screen.tsx"), /<PlanBillingSection /);
  assert.match(read("product-app.tsx"), /PersonalTeamUpgrade/);
  assert.match(read("product-app.tsx"), /PLAN_CHANGED_EVENT/);
  const ui = read("product/plan-ui.tsx");
  assert.match(ui, /billing_not_configured/);
  assert.match(ui, /downgrade_blocked/);
  assert.match(read("product/org-menu.tsx"), /AccountTypeBadge/);
  assert.match(read("product/org-picker.tsx"), /AccountTypeBadge/);
});

test("painel de uso aceita limite null (ilimitado) sem quebrar a Administração", () => {
  const panel = read("product/usage-panel.tsx");
  assert.match(panel, /limit: number \| null/);
  assert.match(panel, /row\.limit === null/);
});

test("upgradeIntro diz a verdade do backend em cada estado (o upgrade nunca reinicia o teste)", () => {
  const trial = { account_type: "personal", plan_key: "personal_trial", entitlement_source: "trial", trial_ends_at: "2026-11-06T12:00:00+00:00", read_only: false };
  assert.deepEqual(upgradeIntro(trial, NOW), { blocked: false, text: "Seu teste continua até 06/11, sem cartão." });
  assert.equal(upgradeDoneNotice(trial, NOW), "Conta transformada em empresa. Seu teste continua até 06/11, sem cartão.");
  const expired = upgradeIntro({ account_type: "personal", plan_key: "expired", entitlement_source: "expired", trial_ends_at: "2026-10-01T12:00:00+00:00", read_only: true }, NOW);
  assert.equal(expired.blocked, false); assert.match(expired.text, /já terminou.*somente leitura.*não reinicia/);
  assert.match(upgradeIntro({ account_type: "personal", plan_key: "expired", entitlement_source: "expired", trial_ends_at: null, read_only: true }, NOW).text, /não reinicia/);
  assert.match(upgradeIntro({ account_type: "personal", plan_key: "personal_trial", entitlement_source: "trial", trial_ends_at: "2026-10-01T12:00:00+00:00", read_only: false }, NOW).text, /já terminou/, "trial com data vencida não promete continuidade");
  assert.match(upgradeIntro({ account_type: "personal", plan_key: "personal_pro", entitlement_source: "subscription" }, NOW).text, /assinatura atual será ajustada/);
  const comp = upgradeIntro({ account_type: "personal", plan_key: "personal_pro", entitlement_source: "comp" }, NOW);
  assert.equal(comp.blocked, true); assert.match(comp.text, /cortesia.*revogada/); assert.equal(upgradeDoneNotice({ entitlement_source: "comp", account_type: "personal" }, NOW), "");
  assert.match(upgradeIntro({ plan_key: "legacy", entitlement_source: "legacy", account_type: "business" }, NOW).text, /sem os novos limites/);
  for (const state of [trial, { entitlement_source: "expired", account_type: "personal" }]) assert.doesNotMatch(upgradeIntro(state, NOW).text, /14 dias começa/);
});
test("o label do header é só texto (sem link/botão/next-link) e o diálogo usa upgradeIntro", () => {
  const ui = read("product/plan-ui.tsx");
  const label = ui.slice(ui.indexOf("export function PlanLabel"), ui.indexOf("// ── Equipe em conta pessoal"));
  assert.match(label, /data-testid="plan-label"/);
  assert.match(label, /aria-label=\{label\.aria\}/);
  assert.match(label, /title=\{label\.title\}/);
  assert.doesNotMatch(label, /<a |<button|Ver planos|next\/link|onNavigate/, "sem ação por enquanto");
  assert.doesNotMatch(ui, /plan-banner/, "faixa de largura total removida");
  assert.match(read("mobile-nav.tsx"), /<PlanLabel company=\{company\} compact \/>/, "versão compacta no header mobile");
  assert.match(ui, /upgradeIntro\(company\)/); assert.doesNotMatch(ui, /começa sem cartão|Seu teste de 14 dias começou/);
});
