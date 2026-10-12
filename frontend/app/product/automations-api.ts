import { API_BASE, api, ApiError, messageFor, type Evidence } from "./types-and-api";
import { type AutomationDraft } from "./automations-model";

export type RunStatus = "queued" | "running" | "ok" | "empty" | "quota" | "error";
export type AutomationRun = { id: string; automation_id: string; status: RunStatus; started_at: string | null; finished_at: string | null; documents_considered: number; questions_used: number; error_code: string | null; pdf_available: boolean; result: null | { answer: string | null; citations: Evidence[]; skipped_recipients: { user_id: string; reason: string }[]; notified: number } };
export type Automation = { id: string; name: string; enabled: boolean; trigger_kind: "schedule" | "folder_changed"; trigger_config: { frequency?: AutomationDraft["frequency"]; weekday?: number; hour?: number; day?: number; timezone?: string }; scope: { workspace_folder_ids: string[] }; prompt: string; template: AutomationDraft["template"]; output_formats: ("email" | "pdf")[]; recipients: { user_id: string; email: string }[]; created_by_user_id: string; last_run_at: string | null; next_run_at: string | null; last_run: { id: string; status: RunStatus; finished_at: string | null } | null };
export const automationPath = (organizationId: string, automationId?: string) => `/organizations/${organizationId}/automations${automationId ? `/${automationId}` : ""}`;
export const runStatusLabel = (status: RunStatus) => ({ queued: "Na fila", running: "Executando", ok: "Concluída", empty: "Sem alertas", quota: "Cota atingida", error: "Erro" })[status];
export const runErrorText = (run: AutomationRun) => run.status === "quota" ? "A cota mensal de perguntas da organização foi atingida. Esta execução não gerou resultado. Tente novamente quando houver cota disponível." : ({ creator_access_lost: "O criador perdeu acesso a uma pasta. Revise as permissões ou escolha outras pastas antes de executar novamente.", scope_unavailable: "Uma pasta selecionada não está disponível. Confira a conexão e o escopo da automação.", ai_unavailable: "Não foi possível gerar o resultado agora. Tente executar novamente em instantes.", internal_error: "Ocorreu uma falha ao executar a automação. Tente novamente." } as Record<string, string>)[run.error_code ?? ""] ?? "Não foi possível concluir a execução. Tente novamente.";
export function automationError(error: unknown): string {
  const code = error instanceof Error ? error.message : "";
  return ({ automation_limit_reached: "A organização atingiu o limite de automações. Edite uma existente ou peça ao administrador para liberar espaço.", scope_not_allowed: "Uma pasta não está disponível para o criador. Revise as pastas e as permissões.", recipient_not_member: "Um destinatário não é membro ativo desta organização. Revise os destinatários.", invalid_trigger_config: "Confira a frequência, a hora cheia e o fuso horário da agenda.", "automation not found": "Esta automação não está disponível. Atualize a lista.", run_has_no_result: "Esta execução ainda não tem resultado para baixar." } as Record<string, string>)[code] ?? (error instanceof ApiError && error.status === 422 ? "Confira os campos da automação e tente novamente." : messageFor(error));
}
export async function downloadRunPdf(organizationId: string, automationId: string, runId: string) {
  const response = await fetch(`${API_BASE}${automationPath(organizationId, automationId)}/runs/${runId}/pdf`, { credentials: "include", cache: "no-store" });
  if (!response.ok) throw new Error("Não foi possível baixar o PDF. Atualize o histórico e tente novamente.");
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url; link.download = `automacao-${runId}.pdf`;
  document.body.appendChild(link); link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export { api };

export { automationPayload, automationToDraft } from "./automations-model";
