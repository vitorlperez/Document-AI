export type SyncStateName = "idle" | "queued" | "syncing" | "ready" | "partial_failure" | "failed";
export type SyncStage = "discovering" | "indexing" | "embedding" | "done" | null;

export type ToolSyncState = {
  sourceId: string; provider: string; libraryNodeId: string | null;
  state: SyncStateName; stage: SyncStage;
  processed: number; total: number; failed: number; /** Files skipped on purpose (e.g. empty). Neutral: never counted as a failure. */ skipped: number; queryable: boolean;
  errorCode?: string | null; lastSyncedAt?: string | null;
};

export type SyncStatusItemDto = {
  source_id: string; provider: string; library_node_id?: string | null;
  state?: string; stage?: string | null; processed?: number | null; total?: number | null; failed?: number | null; skipped?: number | null;
  queryable?: boolean; error_code?: string | null; last_synced_at?: string | null;
};

const STATES: SyncStateName[] = ["idle", "queued", "syncing", "ready", "partial_failure", "failed"];
const STAGES = ["discovering", "indexing", "embedding", "done"];
const count = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;

export function normalizeSyncItems(items: SyncStatusItemDto[] | null | undefined): ToolSyncState[] {
  return (items ?? []).map((item) => ({
    sourceId: item.source_id,
    provider: item.provider,
    libraryNodeId: item.library_node_id ?? null,
    state: STATES.includes(item.state as SyncStateName) ? item.state as SyncStateName : "idle",
    stage: STAGES.includes(item.stage ?? "") ? item.stage as SyncStage : null,
    processed: count(item.processed), total: count(item.total), failed: count(item.failed), skipped: count(item.skipped),
    queryable: Boolean(item.queryable),
    errorCode: item.error_code ?? null, lastSyncedAt: item.last_synced_at ?? null,
  }));
}

export const isActive = (tool: Pick<ToolSyncState, "state">) => tool.state === "queued" || tool.state === "syncing";
export const isIndeterminate = (tool: Pick<ToolSyncState, "total" | "state">) => isActive(tool) && tool.total <= 0;
export const anySyncing = (tools: ToolSyncState[]) => tools.some(isActive);
export const anyQueryable = (tools: ToolSyncState[]) => tools.some((tool) => tool.queryable);

/**
 * The ONE rule for every surface: the percent shown (text, tooltip, bar width) is exactly
 * round(processed / total * 100) of the CURRENT step. There is no weighting across steps and
 * no monotonic floor: the bar restarts when the step changes, and "Etapa N de 2" says so.
 * 0–100, or null when the total is unknown (indeterminate bar, no %).
 */
export function percent(tool: Pick<ToolSyncState, "processed" | "total" | "state">): number | null {
  if (tool.state === "ready") return 100;
  if (tool.total <= 0) return null;
  return Math.round(Math.max(0, Math.min(tool.processed, tool.total)) / tool.total * 100);
}

export const STEP_COUNT = 2;
const STEP_NAMES = ["Lendo arquivos", "Preparando para o chat"];

/** 1 = reading files, 2 = preparing for chat (indexing + embedding); null when not running a step (queued, idle, terminal). */
export function stepOf(tool: Pick<ToolSyncState, "state" | "stage">): 1 | 2 | null {
  if (tool.state !== "syncing") return null;
  return tool.stage === "indexing" || tool.stage === "embedding" || tool.stage === "done" ? 2 : 1;
}

export function stageLabel(tool: Pick<ToolSyncState, "state" | "stage"> & Partial<Pick<ToolSyncState, "queryable">>): string {
  if (tool.state === "queued") return "Na fila";
  if (tool.state === "ready") return tool.queryable === false ? "Sincronização concluída, sem conteúdo para o chat" : "Pronto para o chat";
  if (tool.state === "partial_failure") return "Sincronização concluída com problemas";
  if (tool.state === "failed") return "Não foi possível sincronizar";
  if (tool.state === "idle") return "Aguardando sincronização";
  return STEP_NAMES[(stepOf(tool) ?? 1) - 1];
}

/** Compact label for dense lists (sidebar, library): the percent, "Fila" while queued, "…" while the total is unknown. */
export function shortLabel(tool: Pick<ToolSyncState, "processed" | "total" | "state" | "stage"> & Partial<Pick<ToolSyncState, "queryable">>): string {
  if (tool.state === "queued") return "Fila";
  return progressView(tool).short ?? "…";
}

export function countLabel(tool: Pick<ToolSyncState, "processed" | "total" | "state">): string | null {
  if (tool.total <= 0) return null;
  return `${tool.state === "ready" ? tool.total : Math.min(tool.processed, tool.total)} de ${tool.total} ${tool.total === 1 ? "documento" : "documentos"}`;
}

/**
 * Display model shared by every surface (compact chat indicator, sidebar, onboarding, drawer, library).
 * text    = "Etapa 1 de 2 · Lendo arquivos — 79 de 167 (47%)"
 * compact = "Etapa 1 de 2 · Lendo arquivos 79/167 · 47%"
 * short   = "47%"  (the same number, always: percent === round(processed/total*100) of the step)
 */
export type ProgressView = { percent: number | null; short: string | null; step: number | null; stepText: string | null; stage: string; count: string | null; compact: string; text: string; speech: string };

function buildView(step: number | null, stage: string, processed: number, total: number, extra = ""): ProgressView {
  const measured = total > 0;
  const done = Math.min(Math.max(processed, 0), total);
  const pct = measured ? Math.round(done / total * 100) : null;
  const stepText = step ? `Etapa ${step} de ${STEP_COUNT}` : null;
  const lead = stepText ? `${stepText} · ${stage}` : stage;
  const count = measured ? `${done} de ${total}` : null;
  const short = pct === null ? null : `${pct}%`;
  const text = measured ? `${lead} — ${count} (${short})${extra}` : `${lead}…${extra}`;
  const compact = measured ? `${lead} ${done}/${total} · ${short}${extra}` : `${lead}…${extra}`;
  const speech = measured ? `${lead}, ${done} de ${total} documentos, ${short}${extra}` : `${lead}${extra}`;
  return { percent: pct, short, step, stepText, stage, count, compact, text, speech };
}

export function progressView(tool: Pick<ToolSyncState, "processed" | "total" | "state" | "stage"> & Partial<Pick<ToolSyncState, "queryable">>): ProgressView {
  if (!isActive(tool)) {
    const stage = stageLabel(tool);
    return { percent: percent(tool), short: tool.state === "ready" ? "100%" : null, step: null, stepText: null, stage, count: null, compact: stage, text: stage, speech: stage };
  }
  if (tool.state === "queued") return { ...buildView(null, "Na fila", 0, 0), text: "Na fila", compact: "Na fila", speech: "Na fila" };
  return buildView(stepOf(tool), stageLabel(tool), tool.processed, tool.total);
}

/**
 * Aggregate for several tools syncing at once: the percent is processed/total summed over the tools
 * that are in the earliest running step (one step, one unit). Any running tool without a known total
 * makes the aggregate indeterminate (no %).
 */
export function summaryProgress(tools: ToolSyncState[]): ProgressView | null {
  const active = tools.filter(isActive);
  if (!active.length) return null;
  const running = active.filter((tool) => tool.state === "syncing");
  if (!running.length) return progressView(active[0]);
  const step = Math.min(...running.map((tool) => stepOf(tool) ?? 1));
  const group = running.filter((tool) => (stepOf(tool) ?? 1) === step);
  const extra = active.length > 1 ? ` · ${active.length} ferramentas` : "";
  if (active.some((tool) => isIndeterminate(tool) && tool.state === "syncing")) return buildView(step, STEP_NAMES[step - 1], 0, 0, extra);
  const processed = group.reduce((sum, tool) => sum + Math.min(tool.processed, tool.total), 0);
  const total = group.reduce((sum, tool) => sum + tool.total, 0);
  return buildView(step, STEP_NAMES[step - 1], processed, total, extra);
}

const ERROR_MESSAGES: Record<string, string> = {
  provider_error: "A ferramenta conectada não respondeu como esperado.",
  provider_auth_error: "O acesso à ferramenta expirou ou foi revogado.",
  auth_error: "O acesso à ferramenta expirou ou foi revogado.",
  token_expired: "O acesso à ferramenta expirou. Reconecte para continuar.",
  permission_denied: "Sem permissão para ler esse conteúdo na ferramenta.",
  rate_limited: "A ferramenta limitou as requisições. Tentaremos novamente mais tarde.",
  provider_rate_limited: "A ferramenta limitou as requisições. Tentaremos novamente mais tarde.",
  workspace_scope_not_found: "A pasta escolhida não está mais disponível para sincronizar.",
  not_found: "O conteúdo escolhido não foi encontrado na ferramenta.",
  timeout: "A ferramenta demorou demais para responder.",
};

/** Friendly pt-BR reason for a raw error_code; never exposes the code itself. */
export function errorReason(code: string | null | undefined): string | null {
  if (!code || code === "usage_limit_exceeded") return null;
  return ERROR_MESSAGES[code] ?? "Ocorreu um erro inesperado ao sincronizar.";
}

export function errorMessage(tool: Pick<ToolSyncState, "state" | "errorCode" | "failed"> & Partial<Pick<ToolSyncState, "queryable">>): string | null {
  if (tool.errorCode === "usage_limit_exceeded") return "O limite de uso do plano foi atingido. Parte dos documentos não foi indexada; revise o plano para continuar.";
  if (tool.state === "failed") return `A sincronização falhou${errorReason(tool.errorCode) ? `: ${errorReason(tool.errorCode)!.replace(/\.$/, "")}` : ""}. Tente novamente em instantes; seus arquivos originais não foram alterados.`;
  if (tool.state === "partial_failure") return `${errorReason(tool.errorCode) ? `${errorReason(tool.errorCode)} ` : ""}${tool.failed > 0 ? `${tool.failed} ${tool.failed === 1 ? "arquivo não pôde" : "arquivos não puderam"} ser lido${tool.failed === 1 ? "" : "s"}` : "Alguns arquivos não puderam ser lidos"}. ${tool.queryable ? "O conteúdo pronto já está disponível nas respostas." : "Ainda não há conteúdo disponível para respostas."}`;
  return null;
}

export type OnboardingSyncState = "empty" | "idle" | "syncing-nothing-ready" | "syncing-partial-ready" | "done-ready" | "done-empty" | "done-with-errors" | "all-failed";
export type SyncSummary = { state: OnboardingSyncState; processed: number; total: number; known: boolean; percent: number | null; syncing: boolean; queryable: boolean; errors: ToolSyncState[]; allReady: boolean };

// Re-evaluate each poll: active work wins; terminal errors never imply ongoing work.
function onboardingState(tools: ToolSyncState[], syncing: boolean, queryable: boolean, errors: ToolSyncState[]): OnboardingSyncState {
  if (syncing) return queryable ? "syncing-partial-ready" : "syncing-nothing-ready";
  if (!tools.length) return "empty";
  if (!queryable && tools.every((tool) => tool.state === "failed")) return "all-failed";
  if (errors.length) return "done-with-errors";
  if (queryable) return "done-ready";
  if (tools.every((tool) => tool.state === "idle")) return "idle";
  return "done-empty";
}

export function summarize(tools: ToolSyncState[]): SyncSummary {
  const active = tools.filter(isActive);
  const measured = active.filter((tool) => tool.total > 0);
  const processed = measured.reduce((sum, tool) => sum + Math.min(tool.processed, tool.total), 0);
  const total = measured.reduce((sum, tool) => sum + tool.total, 0);
  const known = active.length > 0 && measured.length === active.length;
  const syncing = active.length > 0;
  const queryable = anyQueryable(tools);
  const errors = tools.filter((tool) => tool.state === "failed" || tool.state === "partial_failure" || tool.errorCode === "usage_limit_exceeded");
  return {
    state: onboardingState(tools, syncing, queryable, errors),
    processed, total, known, percent: known && total > 0 ? Math.round(processed / total * 100) : null,
    syncing, queryable, errors,
    allReady: tools.length > 0 && queryable && errors.length === 0 && tools.every((tool) => tool.state === "ready"),
  };
}

type SyncPresentation = { title: string; description: string; callout: string; tone: "info" | "success" | "warning"; action: "connect" | "chat" | "background"; cta: string; backLabel: string };

export function onboardingSyncPresentation(summary: SyncSummary): SyncPresentation {
  const base = { backLabel: "Voltar", tone: "info" as const };
  switch (summary.state) {
    case "empty":
    case "idle": return { ...base, title: "Escolha o conteúdo da sua base", description: "Conecte uma ferramenta e escolha os documentos que sua equipe poderá consultar.", callout: "Nenhuma sincronização em andamento. Volte para conectar e inicie a sincronização do conteúdo escolhido.", action: "connect", cta: "Escolher conteúdo" };
    case "syncing-nothing-ready": return { ...base, title: "Estamos preparando sua base", description: "Lemos seus documentos, organizamos o conteúdo e o preparamos para o chat. Acompanhe o andamento de cada ferramenta abaixo.", callout: "Ainda não há conteúdo pronto para perguntas. Você pode continuar em segundo plano e acompanhar o progresso na conversa.", action: "background", cta: "Continuar em segundo plano" };
    case "syncing-partial-ready": return { ...base, title: "Seu conteúdo já começou a ficar pronto", description: "A sincronização continua nas ferramentas abaixo. Novos documentos ficam disponíveis conforme são preparados.", callout: "Já dá para conversar com o conteúdo pronto, sem esperar a sincronização terminar.", tone: "success", action: "chat", cta: "Começar a conversar" };
    case "done-ready": return { ...base, title: "Sua base está pronta", description: "A sincronização terminou. Confira o resultado de cada ferramenta abaixo.", callout: "Seus documentos já podem ser consultados no chat, com respostas e fontes.", tone: "success", action: "chat", cta: "Começar a conversar" };
    case "done-empty": return { ...base, title: "A sincronização terminou sem conteúdo", description: "Não encontramos conteúdo consultável na seleção atual. Nenhuma sincronização está em andamento.", callout: "Escolha outra pasta ou conteúdo com documentos e inicie uma nova sincronização para preparar sua base.", action: "connect", cta: "Escolher outra pasta" };
    case "done-with-errors": return { ...base, title: "A sincronização terminou com problemas", description: "Algumas ferramentas ou arquivos não puderam ser sincronizados. Confira os detalhes abaixo.", callout: summary.queryable ? "Você pode conversar com o conteúdo pronto. Para recuperar o que falhou, volte às conexões e tente sincronizar novamente." : "Ainda não há conteúdo pronto para perguntas. Volte às conexões, revise o acesso e tente sincronizar novamente.", tone: "warning", action: summary.queryable ? "chat" : "connect", cta: summary.queryable ? "Começar a conversar" : "Voltar para conectar", backLabel: "Revisar conexões" };
    case "all-failed": return { ...base, title: "Não foi possível sincronizar sua base", description: "Todas as sincronizações falharam. Nenhuma ferramenta está sincronizando agora.", callout: "Volte às conexões para revisar o acesso e tentar novamente, ou escolha outra ferramenta ou conteúdo.", tone: "warning", action: "connect", cta: "Voltar para conectar" };
  }
}

export function bannerCopy(summary: SyncSummary): string | null {
  if (!summary.syncing) return null;
  return "Sua base ainda está sincronizando — as respostas usam o que já está pronto.";
}

export function pollInterval(syncing: boolean): number { return syncing ? 3000 : 5000; }

/** 0 = lendo arquivos, 1 = preparando para o chat, 2 = concluído. */
export function stageIndex(tool: Pick<ToolSyncState, "state" | "stage">): number {
  if (tool.state === "ready" || tool.state === "partial_failure") return 2;
  return (stepOf(tool) ?? 1) - 1;
}
