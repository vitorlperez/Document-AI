"use client";

import { CircleAlert, Gift } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { ApiError, api, messageFor } from "./types-and-api";
import { EmptyState, ErrorState, LoadingBlock, SkeletonList, Spinner, btn } from "../ui";
import { usePlans } from "./plan-ui";
import { LIMIT_FIELDS, REASON_MAX, accountLabel, buildCompBody, canManageComps, compWarningMessage, extendBody, formatDate, isSupportDenied, plansForAccountType, seatsLabel, sourceLabel, staffPlanTitle } from "./staff-plan-logic.mjs";

// Tipos do contrato de staff (docs/contas-pessoal-empresa.md §14); declarados aqui para não depender de types-and-api.
export type StaffComp = { id: string; plan_key: string; limits_override: Record<string, unknown> | null; reason: string; expires_at: string | null; revoked_at: string | null; granted_by_user_id: string; organization_id?: string };
export type StaffEntitlement = {
  name: string; staff_role?: string; account_type: string; plan_key: string; entitlement_source: string; trial_ends_at: string | null; read_only: boolean;
  effective: Record<string, unknown> & { included_seats?: number; max_members?: number | null };
  trial_started_at: string | null; subscription: { status: string; plan_key: string; seats: number; provider: string } | null; comps: StaffComp[];
};
type PlanOption = { plan_key: string; account_type: string; title: string };
type CompResult = StaffComp & { warning: string | null };

const field = "mo-field mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm";
const liveComp = (comps: StaffComp[]) => comps.find((comp) => !comp.revoked_at && (!comp.expires_at || new Date(comp.expires_at) > new Date()));
const expiryText = (comp: StaffComp) => comp.expires_at ? `até ${formatDate(comp.expires_at)}` : "permanente";

/** O papel `support` lê plano/fonte/trial/assentos/cortesias (GET), mas conceder/estender/revogar é só do `admin`. */
function ReadOnlyNotice() {
  return <div role="note" data-testid="staff-readonly-note" className="mt-5 rounded-lg border border-line bg-paper p-4 text-sm"><b>Somente leitura</b><p className="mt-1 text-muted-foreground">Seu papel de staff é <b>support</b>: você consulta plano, assentos e cortesias, mas conceder, estender ou revogar cortesias exige o papel <b>admin</b>.</p></div>;
}
const catalogOf = (response: { plans: PlanOption[] } | null) => response?.plans ?? [];

export function StaffPlanPanel({ organizationId }: { organizationId: string }) {
  const [state, setState] = useState<StaffEntitlement | null>(null); const plans = catalogOf(usePlans());
  const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [denied, setDenied] = useState(false);
  const [notice, setNotice] = useState<string | null>(null); const [warning, setWarning] = useState<string | null>(null);
  const load = useCallback(() => {
    setLoading(true); setError(null); setDenied(false);
    void api<StaffEntitlement>(`/platform/organizations/${organizationId}/entitlement`)
      .then(setState)
      .catch((caught) => { setState(null); if (caught instanceof ApiError && isSupportDenied(caught.status)) setDenied(true); else setError(messageFor(caught)); })
      .finally(() => setLoading(false));
  }, [organizationId]);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);

  if (loading) return <LoadingBlock label="Carregando plano…" className="mt-5"><SkeletonList rows={3} avatar={false} /></LoadingBlock>;
  if (denied) return <p role="note" className="mt-5 text-sm text-muted-foreground">Sem permissão para ver o plano desta organização.</p>;
  if (error || !state) return <ErrorState className="mt-5" icon={<CircleAlert size={22} />} title="Não foi possível carregar o plano" description={error ?? "Resposta vazia."} actions={<button onClick={load} className="mo-interactive min-h-11 underline">Tentar novamente</button>} />;
  const comp = liveComp(state.comps);
  const history = state.comps.filter((item) => item !== comp);
  const manage = canManageComps(state.staff_role); const title = (key: string) => staffPlanTitle(key, plans);
  return <section className="mt-5 rounded-lg border border-line-soft bg-panel p-6" aria-label="Plano e cortesia">
    <h2 className="text-xl font-semibold">Plano e cortesia</h2>
    <dl className="mt-4 grid gap-3 text-sm sm:grid-cols-2" data-testid="staff-plan-summary">
      <div><dt className="text-muted-foreground">Tipo de conta</dt><dd className="font-semibold">{accountLabel(state.account_type)}</dd></div>
      <div><dt className="text-muted-foreground">Plano efetivo</dt><dd className="font-semibold">{title(state.plan_key)}{state.read_only ? " · somente leitura" : ""}</dd></div>
      <div><dt className="text-muted-foreground">Fonte</dt><dd className="font-semibold">{sourceLabel(state.entitlement_source)}</dd></div>
      <div><dt className="text-muted-foreground">Fim do teste</dt><dd className="font-semibold">{formatDate(state.trial_ends_at) ?? "—"}</dd></div>
      <div><dt className="text-muted-foreground">Assentos</dt><dd className="font-semibold">{seatsLabel(state)}{state.subscription ? ` · assinatura ${state.subscription.status} (${state.subscription.seats})` : ""}</dd></div>
      <div><dt className="text-muted-foreground">Cortesia ativa</dt><dd className="font-semibold">{comp ? `${title(comp.plan_key)} · ${expiryText(comp)}` : "Nenhuma"}</dd></div>
    </dl>
    {notice && <p role="status" className="mt-4 rounded-md border border-line bg-sage p-3 text-sm">{notice}</p>}
    {warning && <p role="alert" className="mt-4 rounded-md border border-line bg-paper p-3 text-sm font-semibold">{warning}</p>}
    {!manage && <ReadOnlyNotice />}
    {comp && <ActiveComp organizationId={organizationId} comp={comp} title={title(comp.plan_key)} readOnly={!manage} onChanged={(message) => { setNotice(message); setWarning(null); load(); }} />}
    {manage && <GrantForm organizationId={organizationId} accountType={state.account_type} plans={plans} replacing={Boolean(comp)} onGranted={(result) => { setNotice("Cortesia concedida."); setWarning(compWarningMessage(result.warning)); load(); }} />}
    {history.length > 0 && <div className="mt-6"><h3 className="text-sm font-semibold">Histórico de cortesias</h3><ul className="mt-2 space-y-2 text-xs text-muted-foreground">{history.map((item) => <li key={item.id} className="rounded-md border border-line-soft p-2">{title(item.plan_key)} · {item.revoked_at ? `revogada em ${formatDate(item.revoked_at)}` : `venceu em ${formatDate(item.expires_at)}`} · {item.reason}</li>)}</ul></div>}
  </section>;
}

function ActiveComp({ organizationId, comp, title, readOnly, onChanged }: { organizationId: string; comp: StaffComp; title: string; readOnly: boolean; onChanged: (message: string) => void }) {
  const [date, setDate] = useState(""); const [busy, setBusy] = useState<"extend" | "revoke" | null>(null); const [error, setError] = useState<string | null>(null);
  async function extend(event: FormEvent) {
    event.preventDefault(); const built = extendBody(date) as { body?: { expires_at: string }; error?: string }; if (built.error || !built.body) { setError(built.error ?? "Dados inválidos."); return; }
    setBusy("extend"); setError(null);
    try { await api(`/platform/organizations/${organizationId}/comps/${comp.id}`, { method: "PATCH", body: JSON.stringify(built.body) }); onChanged("Validade estendida."); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(null); }
  }
  async function revoke() {
    if (!window.confirm("Revogar esta cortesia? A organização volta ao plano que ela teria sem a cortesia.")) return;
    setBusy("revoke"); setError(null);
    try { await api(`/platform/organizations/${organizationId}/comps/${comp.id}`, { method: "DELETE" }); onChanged("Cortesia revogada."); } catch (caught) { setError(messageFor(caught)); } finally { setBusy(null); }
  }
  return <div className="mt-5 rounded-md border border-line-soft p-4" data-testid="staff-active-comp"><b className="text-sm">Cortesia ativa: {title} ({expiryText(comp)})</b><p className="mt-1 text-xs text-muted-foreground">Motivo: {comp.reason}</p>
    {comp.limits_override && Object.keys(comp.limits_override).length > 0 && <p className="mt-1 text-xs text-muted-foreground">Limites: {Object.entries(comp.limits_override).map(([key, value]) => `${key}=${value === null ? "ilimitado" : String(value)}`).join(", ")}</p>}
    {!readOnly && <form onSubmit={extend} className="mt-3 flex flex-wrap items-end gap-2"><label className="text-sm font-medium" htmlFor="comp-extend-date">Nova validade<input id="comp-extend-date" type="date" value={date} onChange={(event) => setDate(event.target.value)} className={field} /></label><button disabled={busy !== null} className={btn("secondary", "md")}>{busy === "extend" && <Spinner size={16} />}Estender validade</button><button type="button" disabled={busy !== null} onClick={() => { void revoke(); }} className={btn("danger-ghost", "md")}>{busy === "revoke" && <Spinner size={16} />}Revogar cortesia</button></form>}
    {error && <p role="alert" className="mt-2 text-sm text-[var(--danger-fg)]">{error}</p>}</div>;
}

function GrantForm({ organizationId, accountType, plans, replacing, onGranted }: { organizationId: string; accountType: string; plans: PlanOption[]; replacing: boolean; onGranted: (result: CompResult) => void }) {
  const options = plansForAccountType(plans, accountType) as PlanOption[];
  const [planKey, setPlanKey] = useState(""); const [reason, setReason] = useState(""); const [permanent, setPermanent] = useState(false); const [date, setDate] = useState("");
  const [limits, setLimits] = useState<Record<string, string>>({}); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); const built = buildCompBody({ planKey, reason, permanent, expiresDate: date, limits }) as { body?: Record<string, unknown>; error?: string }; if (built.error || !built.body) { setError(built.error ?? "Dados inválidos."); return; }
    setBusy(true); setError(null);
    try { const result = await api<CompResult>(`/platform/organizations/${organizationId}/comps`, { method: "POST", body: JSON.stringify(built.body) }); setReason(""); setDate(""); setLimits({}); setPermanent(false); onGranted(result); } catch (caught) { setError(caught instanceof ApiError && caught.status === 403 ? "Apenas o papel admin concede cortesias." : messageFor(caught)); } finally { setBusy(false); }
  }
  return <form onSubmit={submit} className="mt-6 border-t border-line-soft pt-5" aria-label="Conceder cortesia"><h3 className="flex items-center gap-2 font-semibold"><Gift size={16} />Conceder cortesia</h3>{replacing && <p className="mt-1 text-xs text-muted-foreground">Conceder uma nova cortesia revoga a atual.</p>}
    <label className="mt-3 block text-sm font-medium" htmlFor="comp-plan">Plano ({accountLabel(accountType)})<select id="comp-plan" value={planKey} onChange={(event) => setPlanKey(event.target.value)} className={field}><option value="">Selecione</option>{options.map((plan) => <option key={plan.plan_key} value={plan.plan_key}>{plan.title}</option>)}</select></label>
    <label className="mt-3 block text-sm font-medium" htmlFor="comp-reason">Motivo (obrigatório)<textarea id="comp-reason" value={reason} maxLength={REASON_MAX} onChange={(event) => setReason(event.target.value)} rows={2} className={field} /></label><p className="text-xs text-muted-foreground">{reason.length}/{REASON_MAX}</p>
    <div className="mt-3 flex flex-wrap items-end gap-4"><label className="text-sm font-medium" htmlFor="comp-date">Validade<input id="comp-date" type="date" disabled={permanent} value={date} onChange={(event) => setDate(event.target.value)} className={field} /></label><label className="flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" checked={permanent} onChange={(event) => setPermanent(event.target.checked)} />Permanente (sem validade)</label></div>
    <fieldset className="mt-4 min-w-0 border-0 p-0"><legend className="text-sm font-medium">Limites personalizados (opcional)</legend><p className="text-xs text-muted-foreground">Vazio mantém o do plano. Use um número ou &quot;ilimitado&quot;.</p><div className="mt-2 grid gap-2 sm:grid-cols-2">{(LIMIT_FIELDS as string[][]).map(([key, label]) => <label key={key} className="text-xs font-medium" htmlFor={`comp-limit-${key}`}>{label}<input id={`comp-limit-${key}`} value={limits[key] ?? ""} onChange={(event) => setLimits((current) => ({ ...current, [key]: event.target.value }))} className={field} inputMode="numeric" /></label>)}</div></fieldset>
    {error && <p role="alert" className="mt-3 text-sm text-[var(--danger-fg)]">{error}</p>}
    <button disabled={busy} aria-busy={busy} className={btn("primary", "md", "mt-4")}>{busy && <Spinner size={16} />}{busy ? "Concedendo…" : "Conceder cortesia"}</button></form>;
}

/** Cortesias vencendo em N dias (+ permanentes), GET /platform/comps?expiring_within=30. Admin e support leem; só não-staff recebe 403. */
export function StaffExpiringComps({ names }: { names: Map<string, string> }) {
  const plans = catalogOf(usePlans()); const [comps, setComps] = useState<StaffComp[] | null>(null); const [error, setError] = useState<string | null>(null); const [denied, setDenied] = useState(false);
  const load = useCallback(() => { setError(null); setDenied(false); void api<StaffComp[]>("/platform/comps?expiring_within=30").then(setComps).catch((caught) => { if (caught instanceof ApiError && isSupportDenied(caught.status)) setDenied(true); else setError(messageFor(caught)); }); }, []);
  useEffect(() => { void Promise.resolve().then(load); }, [load]);
  return <section className="rounded-lg border border-line-soft bg-panel p-4" aria-label="Cortesias vencendo"><h2 className="font-semibold">Cortesias vencendo</h2><p className="text-xs text-muted-foreground">Próximos 30 dias e permanentes.</p>
    {denied ? <p role="note" className="mt-3 text-sm text-muted-foreground">Sem permissão para ver cortesias.</p> : error ? <p role="alert" className="mt-3 text-sm text-[var(--danger-fg)]">{error} <button onClick={load} className="underline">Tentar novamente</button></p> : comps === null ? <LoadingBlock label="Carregando cortesias…" className="mt-3"><SkeletonList rows={2} avatar={false} /></LoadingBlock> : comps.length === 0 ? <EmptyState title="Nenhuma cortesia vencendo" description="Sem cortesias ativas nesta janela." /> : <ul className="mt-3 space-y-2 text-sm">{comps.map((comp) => <li key={comp.id} className="rounded-md border border-line-soft p-2"><b>{names.get(comp.organization_id ?? "") ?? comp.organization_id}</b><br /><span className="text-xs text-muted-foreground">{staffPlanTitle(comp.plan_key, plans)} · {expiryText(comp)} · {comp.reason}</span></li>)}</ul>}</section>;
}

/** Lista de organizações com tipo/plano/fonte (uma leitura de entitlement por org, limitada). Falha 403 (não-staff) esconde a lista. */
export function StaffOrgPlans({ companies, onSelect }: { companies: { organization_id: string; name: string }[]; onSelect: (company: { organization_id: string; name: string }) => void }) {
  const plans = catalogOf(usePlans()); const [rows, setRows] = useState<Record<string, StaffEntitlement>>({});
  useEffect(() => {
    let alive = true;
    void (async () => {
      for (const company of companies.slice(0, 40)) {
        try { const ent = await api<StaffEntitlement>(`/platform/organizations/${company.organization_id}/entitlement`); if (alive) setRows((current) => ({ ...current, [company.organization_id]: ent })); } catch (caught) { if (caught instanceof ApiError && isSupportDenied(caught.status)) return; }
      }
    })();
    return () => { alive = false; };
  }, [companies]);
  if (Object.keys(rows).length === 0) return null;
  return <ul className="mt-4 space-y-2 text-xs" aria-label="Planos das organizações">{companies.map((company) => { const ent = rows[company.organization_id]; if (!ent) return null; const comp = liveComp(ent.comps); return <li key={company.organization_id}><button type="button" onClick={() => onSelect(company)} className="mo-interactive w-full rounded-md border border-line-soft p-2 text-left"><b className="block truncate">{company.name}</b><span className="text-muted-foreground">{accountLabel(ent.account_type)} · {staffPlanTitle(ent.plan_key, plans)} · {sourceLabel(ent.entitlement_source)}{comp ? ` · ${expiryText(comp)}` : ""}</span></button></li>; })}</ul>;
}
