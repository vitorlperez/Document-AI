"use client";

import { CircleAlert, ExternalLink, X } from "lucide-react";
import { useEffect, useId, useState, type FormEvent } from "react";
import { ModalOverlay } from "./modal-dismiss";
import { btn } from "./ui";
import { ApiError, api, messageFor } from "./product/types-and-api";
import { PRIORITIES, buildTaskPayload, initialForm, newIdempotencyKey, validateForm, type TaskForm, type TaskMember, type TaskPreview } from "./clickup-task-logic";

type Created = { task_id: string; url: string; status: string };
const field = "w-full rounded-md border border-line bg-panel px-3 py-2 text-sm text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary disabled:opacity-60";
const label = "mb-1 block text-xs font-semibold text-muted-foreground";
// The backend already writes a pt-BR sentence for every refusal; only transport failures need the generic copy.
const errorText = (error: unknown) => error instanceof ApiError ? error.message : messageFor(error);

/** Review-and-confirm step of "Criar tarefa no ClickUp": nothing is written until the user presses Criar. */
export function ClickUpTaskModal({ base, onClose }: { base: string; onClose: () => void }) {
  const titleId = useId();
  const [key] = useState(() => newIdempotencyKey()); // one per opening: a retry of this attempt never duplicates the task
  const [preview, setPreview] = useState<TaskPreview | null>(null);
  const [form, setForm] = useState<TaskForm | null>(null);
  const [members, setMembers] = useState<TaskMember[]>([]);
  const [membersNote, setMembersNote] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);

  useEffect(() => {
    let live = true;
    api<TaskPreview>(`${base}/preview`).then((result) => { if (live) { setPreview(result); setForm(initialForm(result)); } }).catch((caught) => { if (live) setLoadError(errorText(caught)); });
    return () => { live = false; };
  }, [base]);

  const listId = form?.listId;
  useEffect(() => {
    if (!listId) return;
    let live = true;
    api<{ members: TaskMember[] }>(`${base}/lists/${encodeURIComponent(listId)}/options`)
      .then((result) => { if (live) setMembers(result.members); })
      .catch(() => { if (live) setMembersNote("Não foi possível carregar os responsáveis desta lista. Você pode deixar em branco."); });
    return () => { live = false; };
  }, [base, listId]);

  const update = (patch: Partial<TaskForm>) => setForm((current) => current && { ...current, ...patch });
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form || busy || created) return;
    const invalid = validateForm(form);
    if (invalid) { setError(invalid); return; }
    setBusy(true); setError(null);
    try {
      setCreated(await api<Created>(base, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": key }, body: JSON.stringify(buildTaskPayload(form)) }));
    } catch (caught) { setError(errorText(caught)); }
    finally { setBusy(false); }
  }

  return <ModalOverlay onClose={onClose} busy={busy} labelledBy={titleId} className="aq-motion-overlay fixed inset-0 z-50 grid place-items-center bg-primary/40 p-4">
    <section className="max-h-[90vh] w-full max-w-xl overflow-y-auto rounded-lg bg-raised p-5 shadow-2xl dark:border dark:border-dialog-edge sm:p-6" data-arquivio-motion="panel-scale">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <h2 id={titleId} className="text-xl font-semibold text-ink">Criar tarefa no ClickUp</h2>
          <p className="mt-1 text-sm text-muted-foreground">Revise o rascunho. Nada é criado até você confirmar.</p>
        </div>
        <button type="button" onClick={onClose} disabled={busy} aria-label="Fechar" className={btn("ghost", "icon")}><X size={18} aria-hidden="true" /></button>
      </div>
      {loadError && <p role="alert" className="mt-4 flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" /><span className="min-w-0 break-words">{loadError}</span></p>}
      {!loadError && !form && <p role="status" className="mt-4 text-sm text-muted-foreground">Preparando o rascunho…</p>}
      {created && <div role="status" className="mt-4 rounded-md border border-emerald-200 bg-emerald-50 p-4 text-sm text-ink">
        <p className="font-semibold">Tarefa criada no ClickUp.</p>
        <a href={created.url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-flex items-center gap-1.5 font-semibold text-primary underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary">Abrir no ClickUp<ExternalLink size={14} aria-hidden="true" /></a>
      </div>}
      {form && preview && !created && (preview.lists.length === 0
        ? <p role="alert" className="mt-4 rounded-md border border-line bg-sage p-3 text-sm text-ink">Nenhuma lista do ClickUp foi liberada. Peça a um administrador para sincronizar ao menos uma lista em Integrações.</p>
        : <form className="mt-4 space-y-4" onSubmit={(event) => { void submit(event); }}>
          <div><label htmlFor={`${titleId}-list`} className={label}>Lista</label>
            <select id={`${titleId}-list`} className={field} value={form.listId} disabled={busy} onChange={(event) => { setMembers([]); setMembersNote(null); update({ listId: event.target.value, assignee: "" }); }}>
              {preview.lists.map((list) => <option key={list.id} value={list.id}>{list.path || list.name}</option>)}
            </select></div>
          <div><label htmlFor={`${titleId}-name`} className={label}>Título</label>
            <input id={`${titleId}-name`} className={field} value={form.name} maxLength={200} disabled={busy} onChange={(event) => update({ name: event.target.value })} /></div>
          <div><label htmlFor={`${titleId}-description`} className={label}>Descrição (Markdown)</label>
            <textarea id={`${titleId}-description`} className={`${field} min-h-40 font-mono text-xs leading-5`} value={form.description} disabled={busy} onChange={(event) => update({ description: event.target.value })} />
            <p className="mt-1 text-xs text-muted-foreground">Ao final será acrescentado: <i>{preview.footer}</i></p></div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div><label htmlFor={`${titleId}-assignee`} className={label}>Responsável</label>
              <select id={`${titleId}-assignee`} className={field} value={form.assignee} disabled={busy} onChange={(event) => update({ assignee: event.target.value })}>
                <option value="">Sem responsável</option>
                {members.map((member) => <option key={member.id} value={String(member.id)}>{member.name || member.email}</option>)}
              </select>
              {membersNote && <p className="mt-1 text-xs text-muted-foreground">{membersNote}</p>}</div>
            <div><label htmlFor={`${titleId}-due`} className={label}>Prazo</label>
              <input id={`${titleId}-due`} type="date" className={field} value={form.dueDate} disabled={busy} onChange={(event) => update({ dueDate: event.target.value })} /></div>
            <div><label htmlFor={`${titleId}-priority`} className={label}>Prioridade</label>
              <select id={`${titleId}-priority`} className={field} value={form.priority} disabled={busy} onChange={(event) => update({ priority: event.target.value })}>
                {PRIORITIES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select></div>
            <div><label htmlFor={`${titleId}-tags`} className={label}>Etiquetas (separadas por vírgula)</label>
              <input id={`${titleId}-tags`} className={field} value={form.tags} disabled={busy} onChange={(event) => update({ tags: event.target.value })} /></div>
          </div>
          <p role="note" className="rounded-md border border-line bg-sage p-3 text-xs leading-5 text-ink">O conteúdo será visível para quem acessa esta lista no ClickUp.</p>
          {error && <p role="alert" className="flex items-start gap-2 rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-rose-800"><CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" /><span className="min-w-0 break-words">{error}</span></p>}
          <div className="flex flex-wrap justify-end gap-2">
            <button type="button" onClick={onClose} disabled={busy} className={btn("secondary", "sm")}>Cancelar</button>
            <button type="submit" disabled={busy} className={btn("primary", "sm")}>{busy ? "Criando…" : "Criar"}</button>
          </div>
        </form>)}
      {created && <div className="mt-4 flex justify-end"><button type="button" onClick={onClose} className={btn("secondary", "sm")}>Fechar</button></div>}
    </section>
  </ModalOverlay>;
}
