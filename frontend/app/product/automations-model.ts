import type { Automation } from "./automations-api";
export type ScopeFolder = { id: string; name: string; path: string };
export type AutomationDraft = {
  name: string;
  trigger: "schedule" | "folder_change";
  frequency: "daily" | "weekly" | "monthly";
  time: string;
  weekday: number;
  monthDay: number;
  timezone: string;
  scopeFolders: ScopeFolder[];
  legacyFolderIds: string[];
  prompt: string;
  template: "summary" | "table" | "alert";
  recipientIds: string[];
  bell: boolean;
  email: boolean;
};
export const weekdays = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
export const promptTemplates = {
  resumo: "Resuma as principais informações dos arquivos, destaque o que mudou e cite as fontes de cada conclusão.",
  tabela: "Organize as informações dos arquivos em uma tabela comparativa, com os principais dados e as fontes de cada linha.",
  alerta: "Identifique prazos, pendências e pontos que precisam de atenção nos arquivos. Explique cada alerta e cite a fonte.",
};
export function newAutomationDraft(): AutomationDraft {
  return { name: "", trigger: "schedule", frequency: "weekly", time: "08:00", weekday: 1, monthDay: 1, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Sao_Paulo", scopeFolders: [], legacyFolderIds: [], prompt: "", template: "summary", recipientIds: [], bell: true, email: false };
}
export function validateAutomationStep(draft: AutomationDraft, step: number): string | null {
  if (step === 0) {
    if (!draft.name.trim()) return "Dê um nome à automação.";
    if (draft.name.trim().length > 160) return "Use até 160 caracteres no nome.";
    if (draft.trigger === "schedule" && !draft.timezone.trim()) return "Informe o fuso horário da agenda.";
    if (draft.trigger === "schedule") { try { new Intl.DateTimeFormat("pt-BR", { timeZone: draft.timezone }); } catch { return "Informe um fuso horário válido, como America/Sao_Paulo."; } }
    if (draft.trigger === "schedule" && !/^([01]\d|2[0-3]):00$/.test(draft.time)) return "Escolha uma hora cheia, entre 00h e 23h.";
    if (draft.trigger === "schedule" && draft.frequency === "weekly" && (!Number.isInteger(draft.weekday) || draft.weekday < 0 || draft.weekday > 6)) return "Escolha um dia da semana.";
    if (draft.trigger === "schedule" && draft.frequency === "monthly" && (!Number.isInteger(draft.monthDay) || draft.monthDay < 1 || draft.monthDay > 28)) return "Escolha um dia entre 1 e 28.";
  }
  if (step === 1 && (draft.scopeFolders.length ? draft.scopeFolders.length > 20 : !draft.legacyFolderIds.length)) return "Escolha entre 1 e 20 pastas indexadas.";
  if (step === 2 && (!draft.prompt.trim() || draft.prompt.length > 1000)) return "Escreva uma pergunta ou instrução de até 1000 caracteres.";
  if (step === 3) {
    if (!draft.bell && !draft.email) return "Escolha como receber o resultado: sino, e-mail ou ambos.";
  }
  return null;
}
export function scopeNames(draft: AutomationDraft, legacyNames: string[] = []): string[] {
  return draft.scopeFolders.length ? draft.scopeFolders.map((folder) => folder.name) : legacyNames;
}
export function triggerLabel(draft: AutomationDraft, folderNames: string[] = []): string {
  if (draft.trigger === "folder_change") return `Quando arquivos novos chegarem ${folderNames.length === 1 ? `na pasta ${folderNames[0]}` : "nas pastas selecionadas"}`;
  const time = draft.time.replace(/:00$/, "h").replace(":", "h");
  return draft.frequency === "daily" ? `Todos os dias às ${time}` : draft.frequency === "weekly" ? `Toda ${weekdays[draft.weekday]} às ${time}` : `Todo dia ${draft.monthDay} às ${time}`;
}

export function automationToDraft(item: Automation): AutomationDraft {
  return { ...newAutomationDraft(), name: item.name, trigger: item.trigger_kind === "folder_changed" ? "folder_change" : "schedule", frequency: item.trigger_config.frequency ?? "weekly", time: `${String(item.trigger_config.hour ?? 8).padStart(2, "0")}:00`, weekday: ((item.trigger_config.weekday ?? 0) + 1) % 7, monthDay: item.trigger_config.day ?? 1, timezone: item.trigger_config.timezone ?? "America/Sao_Paulo", scopeFolders: (item.scope.node_ids ?? []).map((id) => { const known = item.scope.folders?.find((folder) => folder.node_id === id); return { id, name: known?.name ?? "Pasta indisponível", path: known?.path ?? "Pasta indisponível" }; }), legacyFolderIds: item.scope.workspace_folder_ids ?? [], prompt: item.prompt, template: item.template, email: item.output_formats.includes("email"), recipientIds: item.recipients.filter((recipient) => recipient.user_id !== item.created_by_user_id).map((recipient) => recipient.user_id) };
}
export function automationPayload(draft: AutomationDraft) {
  return { name: draft.name.trim(), trigger_kind: draft.trigger === "folder_change" ? "folder_changed" : "schedule", trigger_config: draft.trigger === "folder_change" ? {} : { frequency: draft.frequency, hour: Number(draft.time.split(":")[0]), timezone: draft.timezone.trim(), ...(draft.frequency === "weekly" ? { weekday: (draft.weekday + 6) % 7 } : {}), ...(draft.frequency === "monthly" ? { day: draft.monthDay } : {}) }, scope: draft.scopeFolders.length ? { node_ids: draft.scopeFolders.map((folder) => folder.id) } : { workspace_folder_ids: draft.legacyFolderIds }, prompt: draft.prompt.trim(), template: draft.template, output_formats: draft.email ? ["email", "pdf"] : ["pdf"], recipient_user_ids: draft.recipientIds };
}
