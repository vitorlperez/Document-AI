"use client";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export type Role = "owner" | "admin" | "member";
export type Company = { id: string; name: string; membership_id: string; role: Role };
export class ApiError extends Error { constructor(public readonly status: number, message: string) { super(message); } }
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { credentials: "include", headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) }, ...init });
  if (response.status === 204) return undefined as T;
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null);
    const detail = typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string" ? body.detail : "Não foi possível concluir esta ação.";
    throw new ApiError(response.status, detail);
  }
  return response.json() as Promise<T>;
}
export const messageFor = (error: unknown) => error instanceof TypeError ? "Não conseguimos nos conectar ao serviço. Confira sua conexão e tente novamente." : error instanceof ApiError && error.status >= 500 ? "O serviço está temporariamente indisponível. Tente novamente em instantes." : error instanceof ApiError && error.status === 403 ? "Você não tem permissão para esta ação." : error instanceof Error ? error.message : "Ocorreu um erro inesperado.";
