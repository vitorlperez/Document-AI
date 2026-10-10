import { ApiError } from "./types-and-api";

export const USAGE_LIMIT_MESSAGE = "O limite mensal de perguntas da organização foi atingido. Peça a um administrador para conferir o painel de uso ou aguarde o início do próximo mês.";

/** True when the API refused the request because a monthly quota is exhausted (HTTP 429). */
export const isUsageLimitError = (error: unknown): error is ApiError => error instanceof ApiError && error.status === 429;

/** Friendly pt-BR text for a quota refusal, or null when the error is something else. */
export const usageLimitMessage = (error: unknown): string | null => isUsageLimitError(error) ? USAGE_LIMIT_MESSAGE : null;
