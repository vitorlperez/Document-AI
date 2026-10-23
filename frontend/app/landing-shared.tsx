"use client";

import { useEffect, useRef, useState, type RefObject } from "react";
import { ArrowRight, ArrowUpRight, Check, ChevronDown, Menu } from "lucide-react";
import Link from "next/link";
import { Brand } from "./brand";
import { ThemeToggle } from "./theme-toggle";
import { avatarInitial, displayNameFromEmail } from "./product/account-helpers";
import { landingCtaMode } from "./landing-session.mjs";
import { nextHeaderState } from "./landing-header-scroll.mjs";
import {
  PLANS, SALES_CTA, SALES_HREF, TRIAL_CTA, TRIAL_DAYS, annualMonthsFree, businessQuote, extraSeatPrice, formatBRL, planFeatureLines, planPrice, planSeatLine, plansOfKind,
  type AccountKind, type BillingCycle, type PlanKey,
} from "./landing-plans.mjs";

export type LandingSession = { status: "loading" } | { status: "anonymous" } | { status: "authenticated"; email: string; organizationName?: string | null };
/** Intenção de cadastro que a LP envia ao /login (?tipo=&plano=). */
export type SignupIntent = { tipo?: AccountKind; plano?: PlanKey };
export type LandingActions = { onLogin: () => void; onSignUp: (intent?: SignupIntent) => void; onOpenApp?: () => void; onLogout?: () => void };
export type NavItem = { href: string; label: string };

/** Below-the-fold reveal is progressive enhancement: content stays visible without JS or with reduced motion. */
export function useSectionReveal(root: RefObject<HTMLDivElement | null>) {
  useEffect(() => {
    const page = root.current;
    if (!page || !("IntersectionObserver" in window) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const targets = Array.from(page.querySelectorAll<HTMLElement>("[data-reveal]")).filter((el) => el.getBoundingClientRect().top > window.innerHeight);
    if (targets.length === 0) return;
    // Repeats on every entry: the reveal observer adds .is-revealed; a second observer with no margin and threshold 0
    // removes it only once the section is fully outside the viewport (hysteresis against flicker at the edge).
    const reveal = new IntersectionObserver((entries) => {
      for (const entry of entries) if (entry.isIntersecting) entry.target.classList.add("is-revealed");
    }, { threshold: 0.1, rootMargin: "0px 0px -6% 0px" });
    const reset = new IntersectionObserver((entries) => {
      for (const entry of entries) if (!entry.isIntersecting) entry.target.classList.remove("is-revealed");
    }, { threshold: 0 });
    for (const el of targets) { el.classList.add("is-pending"); reveal.observe(el); reset.observe(el); }
    // Reduced motion switched on mid-page: reveal everything and stop observing, without animating.
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onReducedChange = (event: MediaQueryListEvent) => { if (!event.matches) return; reveal.disconnect(); reset.disconnect(); for (const el of targets) el.classList.add("is-revealed"); };
    reduced.addEventListener("change", onReducedChange);
    return () => { reduced.removeEventListener("change", onReducedChange); reveal.disconnect(); reset.disconnect(); for (const el of targets) el.classList.remove("is-pending", "is-revealed"); };
  }, [root]);
}

/** Account chip for the signed-in header: initial + name/e-mail (+ organization), with a two-item menu. */
function LandingAccount({ session, onOpenApp, onLogout }: { session: Extract<LandingSession, { status: "authenticated" }>; onOpenApp: () => void; onLogout: () => void }) {
  const name = displayNameFromEmail(session.email) || session.email;
  const close = (event: { currentTarget: HTMLElement }) => event.currentTarget.closest("details")?.removeAttribute("open");
  return (
    <details className="landing-account">
      <summary aria-label={`Conta de ${session.email}`}>
        <span className="landing-account-avatar" aria-hidden="true">{avatarInitial(name, session.email)}</span>
        <span className="landing-account-text"><strong>{name}</strong><small>{session.organizationName ?? session.email}</small></span>
        <ChevronDown size={16} aria-hidden="true" />
      </summary>
      <div className="landing-account-menu" role="group" aria-label="Conta">
        <p title={session.email}>{session.email}</p>
        <button onClick={(event) => { close(event); onOpenApp(); }}>Ir para o app</button>
        <button onClick={(event) => { close(event); onLogout(); }}>Sair</button>
      </div>
    </details>
  );
}

/** Hides the header on scroll down and brings it back on scroll up; always shown at the top, with a menu open or with focus inside. */
function useHidingHeader() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const bar = ref.current;
    if (!bar) return;
    let state = { hidden: false, lastY: window.scrollY };
    let frame = 0;
    const pinned = () => bar.matches(":focus-within") || bar.querySelector("details[open]") !== null;
    const apply = () => {
      frame = 0;
      state = nextHeaderState(state, window.scrollY, { pinned: pinned(), headerHeight: bar.offsetHeight });
      bar.dataset.hidden = String(state.hidden);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(apply); };
    const show = () => { state = { hidden: false, lastY: window.scrollY }; bar.dataset.hidden = "false"; };
    window.addEventListener("scroll", schedule, { passive: true });
    bar.addEventListener("focusin", show);
    bar.addEventListener("toggle", show, true);
    return () => { window.removeEventListener("scroll", schedule); bar.removeEventListener("focusin", show); bar.removeEventListener("toggle", show, true); if (frame) cancelAnimationFrame(frame); };
  }, []);
  return ref;
}

/** Switch between the two models: "/" (personal) and "/empresas"; the current one is marked. */
function ModelSwitch({ current }: { current: "pessoal" | "empresa" }) {
  return (
    <nav className="landing-model-switch" aria-label="Modelo de conta">
      <Link href="/" aria-current={current === "pessoal" ? "page" : undefined}>Para você</Link>
      <Link href="/empresas" aria-current={current === "empresa" ? "page" : undefined}>Para empresas</Link>
    </nav>
  );
}

/** Header shared by "/" and "/empresas". `intent` is what the header signup button asks for. */
export function LandingHeader({ current, session, nav, intent, homeHref, onLogin, onSignUp, onOpenApp = onLogin, onLogout = () => undefined }: LandingActions & { current: "pessoal" | "empresa"; session: LandingSession; nav: NavItem[]; intent: SignupIntent; homeHref: string }) {
  const barRef = useHidingHeader();
  const mode = landingCtaMode(session);
  const signedIn = session.status === "authenticated" ? session : null;
  return (
    <div className="landing-header-bar" ref={barRef} data-hidden="false"><header className="landing-header landing-container">
      <a href={homeHref} className="landing-brand-link" aria-label="Arquivio, início"><Brand /></a>
      <ModelSwitch current={current} />
      <nav className="landing-desktop-nav" aria-label="Navegação principal">{nav.map((item) => <a key={item.href} href={item.href}>{item.label}</a>)}</nav>
      <div className="landing-header-actions" data-session={mode}><ThemeToggle />{mode === "anonymous" && <><button className="landing-login" onClick={onLogin}>Entrar</button><button className="landing-button landing-button-small" onClick={() => onSignUp(intent)}>{TRIAL_CTA} <ArrowUpRight size={16} /></button></>}{mode === "loading" && <span className="landing-session-placeholder" aria-hidden="true" />}{signedIn && <><button className="landing-button landing-button-small" onClick={onOpenApp}>Ir para o app <ArrowUpRight size={16} /></button><LandingAccount session={signedIn} onOpenApp={onOpenApp} onLogout={onLogout} /></>}</div>
      <details className="landing-mobile-menu"><summary aria-label="Abrir navegação"><Menu size={24} /></summary><nav aria-label="Navegação móvel"><ModelSwitch current={current} />{nav.map((item) => <a key={item.href} href={item.href}>{item.label}</a>)}<div className="landing-mobile-theme"><span>Aparência</span><ThemeToggle /></div>{mode === "anonymous" && <><button onClick={onLogin}>Entrar</button><button className="landing-mobile-signup" onClick={() => onSignUp(intent)}>{TRIAL_CTA}</button></>}{signedIn && <><p className="landing-mobile-account" title={signedIn.email}><span className="landing-account-avatar" aria-hidden="true">{avatarInitial(displayNameFromEmail(signedIn.email), signedIn.email)}</span><span><strong>{displayNameFromEmail(signedIn.email) || signedIn.email}</strong><small>{signedIn.organizationName ?? signedIn.email}</small></span></p><button className="landing-mobile-signup" onClick={onOpenApp}>Ir para o app</button><button onClick={onLogout}>Sair</button></>}</nav></details>
    </header></div>
  );
}

export function LandingFooter({ homeHref, links }: { homeHref: string; links: NavItem[] }) {
  return (
    <footer className="landing-footer landing-container"><a href={homeHref} className="landing-brand-link" aria-label="Arquivio, voltar ao início"><Brand /></a><p>Conhecimento que encontra o seu contexto.</p><nav className="landing-legal-links" aria-label="Informações legais">{links.map((link) => <a key={link.href} href={link.href}>{link.label} <ArrowUpRight size={14} /></a>)}<a href="/privacidade">Privacidade <ArrowUpRight size={14} /></a><a href="/termos">Termos de uso <ArrowUpRight size={14} /></a><a href="/docs/api">API <ArrowUpRight size={14} /></a></nav></footer>
  );
}

export function FaqSection({ questions, eyebrow = "ANTES DE COMEÇAR" }: { questions: string[][]; eyebrow?: string }) {
  return (
    <section className="landing-faq landing-container" id="perguntas" aria-labelledby="landing-faq-title" data-reveal>
      <div><p className="landing-eyebrow">{eyebrow}</p><h2 id="landing-faq-title">O que você<br /><em>precisa saber.</em></h2></div>
      <div className="landing-faq-list">{questions.map(([question, answer]) => <details key={question}><summary>{question}<ChevronDown size={20} /></summary><p>{answer}</p></details>)}</div>
    </section>
  );
}

function PlanCard({ plan, cycle, mode, onSignUp, onOpenApp }: { plan: (typeof PLANS)[number]; cycle: BillingCycle; mode: ReturnType<typeof landingCtaMode>; onSignUp: LandingActions["onSignUp"]; onOpenApp: () => void }) {
  const price = planPrice(plan, cycle);
  const extra = extraSeatPrice(plan, cycle);
  const annual = cycle === "annual";
  return (
    <article className="landing-plan" aria-labelledby={`plan-${plan.key}`}>
      <header><h4 id={`plan-${plan.key}`}>{plan.name}</h4><p>{plan.audience}</p></header>
      <p className="landing-plan-price"><strong>{formatBRL(price.total)}</strong><span>{price.unit}</span></p>
      <p className="landing-plan-cycle">{annual ? `Equivale a ${formatBRL(price.perMonth)}/mês · ${annualMonthsFree(plan)} meses de desconto` : "Cobrança mensal"}</p>
      <p className="landing-plan-seats"><strong>{planSeatLine(plan)}</strong>{extra !== null && <span>+ {formatBRL(extra)}{annual ? "/ano" : "/mês"} por pessoa extra, até {plan.seatsMax}</span>}</p>
      <ul>{planFeatureLines(plan).map((line) => <li key={line}><Check size={14} aria-hidden="true" />{line}</li>)}</ul>
      {mode === "app" ? <button className="landing-button landing-plan-cta" onClick={onOpenApp}>Ir para o app</button>
        : mode === "loading" ? <span className="landing-session-placeholder landing-plan-cta" aria-hidden="true" />
        : <button className="landing-button landing-plan-cta" onClick={() => onSignUp({ tipo: plan.kind, plano: plan.key })}>{TRIAL_CTA}</button>}
    </article>
  );
}

/** Preços: toggle mensal/anual + os planos pedidos. Todos os valores vêm de landing-plans.mjs. */
export function PricingSection({ kinds, mode, onSignUp, onOpenApp, title, subtitle }: { kinds: AccountKind[]; mode: ReturnType<typeof landingCtaMode>; onSignUp: LandingActions["onSignUp"]; onOpenApp: () => void; title: React.ReactNode; subtitle: string }) {
  const [cycle, setCycle] = useState<BillingCycle>("monthly");
  const groupTitle: Record<AccountKind, string> = { pessoal: "Para você", empresa: "Para empresas" };
  const team = PLANS.find((plan) => plan.key === "business_team")!;
  const quote = businessQuote(team, 8, cycle);
  return (
    <section className="landing-pricing landing-container" id="precos" aria-labelledby="landing-pricing-title" data-reveal>
      <div className="landing-pricing-head">
        <div><p className="landing-eyebrow">PREÇOS</p><h2 id="landing-pricing-title">{title}</h2><p>{subtitle}</p></div>
        <div className="landing-cycle" role="group" aria-label="Ciclo de cobrança">
          <button type="button" aria-pressed={cycle === "monthly"} onClick={() => setCycle("monthly")}>Mensal</button>
          <button type="button" aria-pressed={cycle === "annual"} onClick={() => setCycle("annual")}>Anual</button>
        </div>
      </div>
      <div className={`landing-plan-groups${kinds.length === 1 ? " is-single" : ""}`}>
        {kinds.map((kind) => (
          <div key={kind} className="landing-plan-group" role="group" aria-label={groupTitle[kind]}>
            <h3>{groupTitle[kind]}</h3>
            <div className="landing-plan-grid">{plansOfKind(kind).map((plan) => <PlanCard key={plan.key} plan={plan} cycle={cycle} mode={mode} onSignUp={onSignUp} onOpenApp={onOpenApp} />)}</div>
          </div>
        ))}
      </div>
      {kinds.includes("empresa") && quote && <p className="landing-pricing-example"><strong>Como o preço da empresa funciona:</strong> um valor base com pessoas incluídas, mais um valor por pessoa extra. Time de 8 pessoas no {team.name}: {formatBRL(quote.base)} + {quote.extras} × {formatBRL(quote.extra)} = <strong>{formatBRL(quote.total)}{cycle === "annual" ? "/ano" : "/mês"}</strong>.</p>}
      <ul className="landing-pricing-notes">
        <li>O teste grátis dura {TRIAL_DAYS} dias e não pede cartão. Depois dele, a conta fica em modo de leitura (seus arquivos continuam lá) até você assinar um plano.</li>
        {kinds.includes("pessoal") && <li>Contas pessoais não adicionam pessoas. Para trabalhar em equipe, transforme sua conta em conta de empresa.</li>}
        <li>Valores em reais. No plano anual, você economiza o equivalente a 2 meses.</li>
      </ul>
    </section>
  );
}

/** Faixa do caminho de upgrade pessoal → empresa. */
export function UpgradeBand({ mode, onOpenApp }: { mode: ReturnType<typeof landingCtaMode>; onOpenApp: () => void }) {
  return (
    <section className="landing-upgrade landing-container" aria-labelledby="landing-upgrade-title" data-reveal>
      <div><h2 id="landing-upgrade-title">Começou sozinho?<br /><em>Leve o Arquivio para o time.</em></h2><p>Quando outras pessoas precisarem entrar, transforme sua conta pessoal em conta de empresa. Seus documentos e suas fontes conectadas ficam onde estão.</p></div>
      {mode === "app" ? <button className="landing-button" onClick={onOpenApp}>Ir para o app <ArrowRight size={18} /></button> : <a className="landing-button" href="#perguntas">Ver como funciona <ArrowRight size={18} /></a>}
    </section>
  );
}

/** Link "Falar com vendas" (canal provisório em landing-plans.mjs). */
export function SalesLink({ className = "landing-login" }: { className?: string }) {
  return <a className={className} href={SALES_HREF}>{SALES_CTA}</a>;
}
