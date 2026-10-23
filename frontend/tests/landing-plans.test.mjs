import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  BUSINESS_TRIAL_CTA, PLANS, TRIAL_CTA, TRIAL_DAYS, annualMonthsFree, businessQuote, extraSeatPrice, formatBRL, planByKey, planFeatureLines, planPrice, plansOfKind, signupHref,
} from "../app/landing-plans.mjs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const landing = read("../app/landing-page.tsx");
const shared = read("../app/landing-shared.tsx");
const business = read("../app/business-landing.tsx");
const css = read("../app/landing.css");
const productApp = read("../app/product-app.tsx");

test("prices, seats and annual values match the owner's final decision", () => {
  const expected = {
    personal_basic: { monthly: 39, annual: 390, included: 1, max: 1, extra: null },
    personal_pro: { monthly: 99, annual: 990, included: 1, max: 1, extra: null },
    business_team: { monthly: 299, annual: 2990, included: 5, max: 15, extra: [49, 490] },
    business_scale: { monthly: 899, annual: 8990, included: 20, max: 100, extra: [39, 390] },
  };
  assert.deepEqual(PLANS.map((plan) => plan.key), Object.keys(expected));
  for (const [key, want] of Object.entries(expected)) {
    const plan = planByKey(key);
    assert.equal(plan.monthly, want.monthly); assert.equal(plan.annual, want.annual);
    assert.equal(plan.seatsIncluded, want.included); assert.equal(plan.seatsMax, want.max);
    assert.equal(plan.extraSeatMonthly, want.extra ? want.extra[0] : null);
    assert.equal(plan.extraSeatAnnual, want.extra ? want.extra[1] : null);
    assert.equal(annualMonthsFree(plan), 2, `${key}: annual = 2 months off`);
  }
  assert.deepEqual(plansOfKind("pessoal").map((plan) => plan.key), ["personal_basic", "personal_pro"]);
  assert.deepEqual(plansOfKind("empresa").map((plan) => plan.key), ["business_team", "business_scale"]);
});

test("cards render what the data module says (price, cycle, extra seat, features)", () => {
  const team = planByKey("business_team");
  assert.deepEqual(planPrice(team, "monthly"), { total: 299, perMonth: 299, unit: "/mês" });
  assert.equal(planPrice(team, "annual").total, 2990);
  assert.equal(extraSeatPrice(team, "annual"), 490);
  assert.equal(formatBRL(299), "R$ 299");
  assert.equal(formatBRL(32.5), "R$ 32,50");
  assert.match(formatBRL(8990), /^R\$ 8\.990$/);
  assert.equal(businessQuote(team, 8).total, 299 + 3 * 49);
  assert.equal(businessQuote(team, 16), null, "above the plan's seat cap");
  assert.equal(businessQuote(planByKey("personal_pro"), 1), null, "personal accounts have no seat quote");
  assert.ok(planFeatureLines(planByKey("personal_basic")).some((line) => line.includes("500")));
  // The JSX reads the module for every number.
  for (const needle of ["planPrice(plan, cycle)", "formatBRL(price.total)", "extraSeatPrice(plan, cycle)", "planFeatureLines(plan)", "businessQuote(team, 8, cycle)"]) assert.ok(shared.includes(needle), `missing ${needle}`);
});

test("no CTA says 'Começar grátis' and none promises a permanent free plan", () => {
  assert.equal(TRIAL_DAYS, 14);
  assert.equal(TRIAL_CTA, `Testar grátis por ${TRIAL_DAYS} dias`);
  assert.equal(BUSINESS_TRIAL_CTA, "Testar com minha empresa");
  for (const source of [landing, shared, business]) {
    assert.doesNotMatch(source, /Começar grátis|Começar com o Arquivio|Criar minha conta|Criar conta/i);
    // CTA labels are the JSX text of buttons/links.
    for (const match of source.matchAll(/<(?:button|a)\b[^>]*>([^<]*)</g)) assert.doesNotMatch(match[1], /plano grátis|gratuito/i);
  }
});

test("copy never names a payment tool or specific payment methods", () => {
  for (const source of [landing, shared, business, read("../app/landing-plans.mjs")]) assert.doesNotMatch(source, /stripe|boleto|\bpix\b|cartão de crédito|paypal|mercado\s?pago/i);
});

test("CTAs carry intent to the sign-up with ?tipo= and &plano=<plan_key>", () => {
  assert.equal(signupHref(), "/login?mode=sign-up");
  assert.equal(signupHref({ tipo: "pessoal" }), "/login?mode=sign-up&tipo=pessoal");
  assert.equal(signupHref({ tipo: "empresa", plano: "business_team" }), "/login?mode=sign-up&tipo=empresa&plano=business_team");
  assert.equal(signupHref({ tipo: "hack", plano: "x" }), "/login?mode=sign-up", "unknown values are dropped");
  assert.ok(shared.includes("onSignUp({ tipo: plan.kind, plano: plan.key })"), "every plan card sends its plan_key");
  assert.ok(landing.includes('onSignUp({ tipo: "pessoal" })') && landing.includes('onSignUp({ tipo: "empresa" })'));
  assert.ok(business.includes('onSignUp({ tipo: "empresa" })'));
  assert.ok(productApp.includes("signupHref(intent)"));
});

test("signed-in visitors get 'Ir para o app' on every CTA surface, never a signup", () => {
  assert.match(shared, /mode === "app" \? <button className="landing-button landing-plan-cta" onClick=\{onOpenApp\}>Ir para o app/);
  assert.match(shared, /mode === "app" \? <button className="landing-button" onClick=\{onOpenApp\}>Ir para o app/);
  for (const source of [landing, business]) assert.ok(source.includes("Ir para o app"));
});

test("/empresas is a public landing: routed, not auto-entered, with its own copy", () => {
  assert.match(read("../app/empresas/page.tsx"), /ProductApp screen="home"/);
  assert.match(productApp, /pathname === "\/empresas" \? <BusinessLandingPage/);
  for (const literal of ["ARQUIVIO PARA EMPRESAS", "O conhecimento do time, ", "em uma só pergunta.", "Conecte Drive, OneDrive, Notion, SharePoint e ClickUp. Seu time pergunta, o Arquivio responde e mostra de qual documento veio.", "Ninguém sabe onde está.", "Todo mundo pergunta no chat.", "Seu time já tem as respostas.", "Falta achá-las.", "Owner, Admin e Membro."]) assert.ok(business.includes(literal), `missing: ${literal}`);
  assert.ok(business.includes('kinds={["empresa"]}'), "only the business plans on /empresas");
});

test("no invented social proof", () => {
  for (const source of [landing, business]) assert.doesNotMatch(source, /depoimento|testimonial|nossos clientes|\+\s?\d+\s+empresas|logos? de clientes/i);
});

test("new landing styles stay scoped to .landing-* and keep mobile gutters", () => {
  assert.match(css, /\.landing-plan-grid \{ display: grid; grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(css, /@media \(max-width: 639px\) \{\s*\.landing-plan-grid \{ grid-template-columns: 1fr; \}/);
  assert.match(css, /\.landing-page \{ --lp-gutter: 16px/, "16px gutter at ≤560");
});
