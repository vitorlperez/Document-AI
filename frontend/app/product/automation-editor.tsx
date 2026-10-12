"use client";

import { useEffect, useRef, useState } from "react";
import { type AutomationDraft, promptTemplates, validateAutomationStep, weekdays } from "./automations-model";
import { AutomationFolderPicker, type LibraryFetch } from "./automation-folder-picker";
import { AutomationRecipients, type RecipientOption } from "./automation-recipients";
import type { Folder } from "./types-and-api";
import { Enter, ProgressIndicator, Spinner } from "../ui";

const control = "mo-field mt-2 min-h-11 w-full rounded-lg border border-line bg-panel px-3 py-2 focus-visible:outline-2 focus-visible:outline-primary";
export const automationButton = "mo-interactive min-h-11 rounded-lg border border-line px-4 py-2 text-sm font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50";
const steps = ["Quando", "Onde", "O que fazer", "Entregar"];

export function AutomationEditor({ fetchJson, organizationId, initial, folders, saving, serverError, onSave, onCancel, loadRecipients, canChooseRecipients }: { fetchJson: LibraryFetch; organizationId: string; loadRecipients: (query: string, signal: AbortSignal) => Promise<RecipientOption[]>; canChooseRecipients: boolean; initial: AutomationDraft; folders: Folder[]; saving: boolean; serverError: string | null; onSave: (draft: AutomationDraft) => void; onCancel: () => void }) {
  const [draft, setDraft] = useState(initial);
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState<"forward" | "back">("forward");
  const [error, setError] = useState<string | null>(null);
  const [recipients, setRecipients] = useState<RecipientOption[]>([]);
  const [recipientLoading, setRecipientLoading] = useState(true);
  const [recipientError, setRecipientError] = useState<string | null>(null);
  const [recipientRevision, setRecipientRevision] = useState(0);
  const scopeQuery = new URLSearchParams(draft.scopeFolders.length ? draft.scopeFolders.map((folder) => ["node_ids", folder.id]) : draft.legacyFolderIds.map((id) => ["workspace_folder_ids", id])).toString();
  useEffect(() => {
    if (!canChooseRecipients || step !== 3) return;
    const controller = new AbortController();
    void Promise.resolve().then(async () => {
      if (controller.signal.aborted) return;
      setRecipientLoading(true); setRecipientError(null);
      try {
        const items = await loadRecipients(scopeQuery, controller.signal);
        if (!controller.signal.aborted) setRecipients(items);
      } catch (caught) { if (!controller.signal.aborted) setRecipientError(caught instanceof Error ? caught.message : "Tente novamente."); }
      finally { if (!controller.signal.aborted) setRecipientLoading(false); }
    });
    return () => controller.abort();
  }, [loadRecipients, canChooseRecipients, step, scopeQuery, recipientRevision]);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, [step]);
  function update<K extends keyof AutomationDraft>(key: K, value: AutomationDraft[K]) { setDraft((current) => ({ ...current, [key]: value })); setError(null); }
  function next() {
    const invalid = validateAutomationStep(draft, step);
    if (invalid) { setError(invalid); return; }
    if (step < 3) { setError(null); setDirection("forward"); setStep(step + 1); return; }
    for (let index = 0; index < 4; index++) { const message = validateAutomationStep(draft, index); if (message) { setDirection("back"); setStep(index); setError(message); return; } }
    onSave(draft);
  }
  return <section className="mo-enter mt-6 rounded-lg border border-line bg-panel p-4 sm:p-6" data-variant="slide" aria-busy={saving}>
    <ol aria-label="Etapas da automação" className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">{steps.map((label, index) => <li key={label} aria-current={index === step ? "step" : undefined} className={`rounded-lg px-3 py-3 transition-[background-color,color] duration-[var(--motion-base)] ease-[var(--ease-out)] ${index === step ? "bg-sage font-semibold text-primary" : "text-muted-foreground"}`}>{index + 1}. {label}</li>)}</ol>
    <ProgressIndicator value={((step + 1) / steps.length) * 100} label={`Etapa ${step + 1} de ${steps.length}`} className="mt-3" />
    <form onSubmit={(event) => { event.preventDefault(); next(); }} className="mt-6 max-w-2xl">
      <h2 ref={heading} tabIndex={-1} className="text-xl font-semibold outline-none">{steps[step]}</h2>
      <Enter key={step} variant={direction === "forward" ? "slide-x" : "fade"}>
      {step === 0 && <div className="mt-4 space-y-4">
        <label className="block">Nome da automação<input autoComplete="off" maxLength={160} className={control} value={draft.name} onChange={(event) => update("name", event.target.value)} placeholder="Ex.: Resumo semanal de projetos" /></label>
        <label className="block">Quando executar<select className={control} value={draft.trigger} onChange={(event) => update("trigger", event.target.value as AutomationDraft["trigger"])}><option value="schedule">Em um horário programado</option><option value="folder_change">Quando arquivos novos chegarem na pasta</option></select></label>
        {draft.trigger === "schedule" ? <>
          <label className="block">Frequência<select className={control} value={draft.frequency} onChange={(event) => update("frequency", event.target.value as AutomationDraft["frequency"])}><option value="daily">Diária</option><option value="weekly">Semanal</option><option value="monthly">Mensal</option></select></label>
          {draft.frequency === "weekly" && <label className="block">Dia da semana<select className={control} value={draft.weekday} onChange={(event) => update("weekday", Number(event.target.value))}>{weekdays.map((day, index) => <option key={day} value={index}>{day}</option>)}</select></label>}
          {draft.frequency === "monthly" && <label className="block">Dia do mês<input className={control} type="number" min={1} max={28} value={draft.monthDay} onChange={(event) => update("monthDay", Number(event.target.value))} /></label>}
          <label className="block">Horário<input className={control} type="time" step={3600} value={draft.time} onChange={(event) => update("time", event.target.value)} /></label>
          <label className="block">Fuso horário<input className={control} value={draft.timezone} onChange={(event) => update("timezone", event.target.value)} placeholder="America/Sao_Paulo" /></label>
          <p className="text-sm text-muted-foreground">Escolha uma hora cheia. O horário segue o fuso informado; a execução pode iniciar até 5 minutos depois.</p>
        </> : <p className="text-sm text-muted-foreground">A automação considera arquivos novos após a sincronização das pastas escolhidas.</p>}
      </div>}
      {step === 1 && <section className="mt-4" aria-label="Pastas da automação"><p className="text-sm text-muted-foreground">Quais pastas a automação deve consultar?</p><AutomationFolderPicker fetchJson={fetchJson} organizationId={organizationId} selected={draft.scopeFolders} onChange={(next) => update("scopeFolders", next)} legacyNames={draft.legacyFolderIds.map((id) => folders.find((folder) => folder.id === id)?.name ?? "pasta")} /></section>}
      {step === 2 && <div className="mt-4">
        <p className="text-sm text-muted-foreground">Escreva o resultado que você quer receber ou comece com um modelo.</p>
        <div className="mt-3 flex flex-wrap gap-2">{Object.entries(promptTemplates).map(([name, prompt]) => <button type="button" key={name} className={automationButton} onClick={() => { update("prompt", prompt); update("template", name === "tabela" ? "table" : name === "alerta" ? "alert" : "summary"); }}>Usar modelo de {name}</button>)}</div>
        <label className="mt-4 block">Formato do resultado<select className={control} value={draft.template} onChange={(event) => update("template", event.target.value as AutomationDraft["template"])}><option value="summary">Resumo</option><option value="table">Tabela</option><option value="alert">Alerta (só notificar se houver algo a reportar)</option></select></label>
        <label className="mt-4 block">Pergunta ou instrução<textarea className={`${control} min-h-40`} maxLength={1000} value={draft.prompt} aria-describedby="prompt-count" onChange={(event) => update("prompt", event.target.value)} placeholder="Ex.: Quais prazos vencem nesta semana? Liste responsáveis e cite os documentos." /></label>
        <p id="prompt-count" className="mt-2 text-sm text-muted-foreground">{draft.prompt.length}/1000 caracteres. O resultado deve se apoiar nos arquivos das pastas escolhidas.</p>
      </div>}
      {step === 3 && <fieldset className="mt-4 space-y-3"><legend className="mb-2 text-sm text-muted-foreground">Escolha onde receber os resultados.</legend>
        <label className="flex min-h-11 items-center gap-3"><input type="checkbox" checked disabled />Sino de notificações do app (sempre ativo)</label>
        <label className="flex min-h-11 items-center gap-3"><input type="checkbox" checked={draft.email} onChange={(event) => update("email", event.target.checked)} />E-mail</label>
        <p className="text-sm text-muted-foreground">O criador sempre recebe o resultado. O e-mail respeita as preferências de notificação de cada usuário.</p>
        {canChooseRecipients && <AutomationRecipients items={recipients} selected={draft.recipientIds} loading={recipientLoading} error={recipientError} onChange={(ids) => update("recipientIds", ids)} onRetry={() => setRecipientRevision((value) => value + 1)} />}
        <p className="text-sm text-muted-foreground">Os resultados também ficam no histórico desta automação.</p>
      </fieldset>}
      </Enter>
      {(error || serverError) && <Enter key={error || serverError} variant="slide"><p role="alert" className="mt-4 rounded-lg border border-rose-200 p-3 text-sm text-rose-700">{error || serverError}</p></Enter>}
      <div className="mt-6 flex flex-wrap gap-3"><button type="button" disabled={saving} className={automationButton} onClick={onCancel}>Cancelar</button>{step > 0 && <button type="button" disabled={saving} className={automationButton} onClick={() => { setError(null); setDirection("back"); setStep(step - 1); }}>Voltar</button>}<button type="submit" disabled={saving} className={`${automationButton} bg-primary text-primary-foreground`}>{saving ? <span className="inline-flex items-center gap-2"><Spinner size={14} />Salvando…</span> : step === 3 ? "Salvar automação" : "Continuar"}</button></div>
    </form>
  </section>;
}
