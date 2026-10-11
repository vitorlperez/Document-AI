/** Pure helpers for "Criar tarefa no ClickUp" (ADR-0020): visibility, form defaults and the POST payload. */

type ContextLike = { source_provider: string; source_status?: string };

export type TaskList = { id: string; name: string; path: string };
export type TaskPreview = { lists: TaskList[]; suggested_list_id: string | null; name: string; description: string; footer: string };
export type TaskMember = { id: number; name: string; email: string | null };
export type TaskForm = { listId: string; name: string; description: string; assignee: string; dueDate: string; priority: string; tags: string };
export type TaskPayload = { list_id: string; name: string; description: string; assignees: number[]; due_date: string | null; priority: number | null; tags: string[] };

export const MAX_TAGS = 10;
export const PRIORITIES = [{ value: "", label: "Sem prioridade" }, { value: "1", label: "Urgente" }, { value: "2", label: "Alta" }, { value: "3", label: "Normal" }, { value: "4", label: "Baixa" }];

/** The ClickUp source is active for the organization: decided from the question contexts the chat already loads (no ClickUp call). */
export function clickUpConnected(contexts: readonly ContextLike[]): boolean {
  return contexts.some((context) => context.source_provider === "clickup" && context.source_status === "connected");
}

/** The button needs an active ClickUp source and an answer already stored by the backend. */
export function canCreateClickUpTask(input: { contexts: readonly ContextLike[]; persisted: boolean; hasConversation: boolean }): boolean {
  return input.persisted && input.hasConversation && clickUpConnected(input.contexts);
}

export function initialForm(preview: TaskPreview): TaskForm {
  const known = preview.lists.some((list) => list.id === preview.suggested_list_id);
  return { listId: known ? String(preview.suggested_list_id) : preview.lists[0]?.id ?? "", name: preview.name, description: preview.description, assignee: "", dueDate: "", priority: "", tags: "" };
}

export function parseTags(text: string): string[] {
  return [...new Set(text.split(/[,;\n]/).map((tag) => tag.trim().replace(/\s+/g, " ")).filter(Boolean))];
}

export function validateForm(form: TaskForm): string | null {
  if (!form.listId) return "Escolha uma lista do ClickUp.";
  if (!form.name.trim()) return "Informe o título da tarefa.";
  if (parseTags(form.tags).length > MAX_TAGS) return `Use no máximo ${MAX_TAGS} etiquetas.`;
  if (form.dueDate && !/^\d{4}-\d{2}-\d{2}$/.test(form.dueDate)) return "Prazo inválido.";
  return null;
}

export function buildTaskPayload(form: TaskForm): TaskPayload {
  const assignee = Number(form.assignee);
  return {
    list_id: form.listId,
    name: form.name.trim(),
    description: form.description.trim(),
    assignees: form.assignee && Number.isSafeInteger(assignee) && assignee > 0 ? [assignee] : [],
    due_date: form.dueDate || null,
    priority: form.priority ? Number(form.priority) : null,
    tags: parseTags(form.tags),
  };
}

/** One key per opening of the modal: retries of the same attempt reuse it, a new opening is a new task. */
export function newIdempotencyKey(): string {
  const random = globalThis.crypto;
  if (typeof random?.randomUUID === "function") return random.randomUUID();
  const bytes = random.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}
