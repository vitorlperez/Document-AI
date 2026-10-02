"use client";

import { FileText, FolderOpen, HardDrive, Table2 } from "lucide-react";
import { useCallback, useEffect, useRef } from "react";
import { cleanAnswerForDisplay } from "../answer-display";
import { providerKey, type QuestionContext } from "../question-scope";
import { type MentionCandidate } from "../mention-composer";
import { type CatalogFolder } from "../new-space-options";
import { ProviderLogo, type ProviderLogoName } from "../provider-logo";

export const API_BASE = import.meta.env.VITE_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
export const SESSION_PATH = API_BASE.replace(/\/$/, "") === "/api" ? "/session" : "/me";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

export type Role = "owner" | "admin" | "member";
export type Screen = "home" | "company" | "library" | "team" | "integrations" | "developer" | "staff" | "invitation";
export type Company = { id: string; name: string; membership_id: string; role: Role };
export type User = { id: string; email: string; is_platform_staff?: boolean };
export type Folder = { id: string; name: string; status: string; last_synced_at: string | null; source_id?: string; external_folder_id?: string; selection_kind?: string; selection_folder_ids?: string[] };
export type DocumentFailure = { id: string; name: string; status: "failed"; error_code: string | null; source_url: string };
export type LibraryDocumentRef = { workspace_folder_id: string; document_id: string };
export type LibraryNode = { id: string; parent_id: string | null; source_id: string; source_provider?: string | null; kind: "source" | "folder" | "file"; external_id?: string; name: string; mime_type: string | null; source_url: string | null; workspace_documents?: LibraryDocumentRef[] };
export type LibraryPage = { items: LibraryNode[]; page?: number; pages?: number; total?: number };
export type LibraryContext = QuestionContext;
export type LibrarySync = { id: string; source_id: string; workspace_folder_id: string; workspace_name: string; status: string; created_at: string; started_at: string | null; completed_at: string | null; error_code: string | null };
export const FULL_RESYNC_CONFIRM = "Ressincronização completa: todos os arquivos serão relidos e reconstruídos (texto, OCR, trechos e embeddings), mesmo os que não mudaram. Pode levar bastante tempo e consumir a cota de processamento. Continuar?";
export type SkippedItem = { name: string; reason: string };
export const skippedReasonLabel = (reason: string | null | undefined) => reason === "empty_content" ? "Arquivo vazio — nada para indexar" : "Ignorado — nada para indexar";
export type ManualSync = { skipped?: number | null; skipped_items?: SkippedItem[] | null; id: string; operation: "sync" | "resync"; mode?: "incremental" | "full" | null; scope_kind: string; scope_name: string; triggered_by: string | null; status: string; created_at: string; started_at: string | null; completed_at: string | null; total: number | null; processed: number | null; failed: number | null; failures: { external_id: string; name: string; error_code: string }[]; tasks: { workspace_folder_id: string; workspace_name: string; status: string; error_code: string | null }[] };
export type Member = { id: string; email: string; role: Role };
export type Source = { id: string; provider: string; status: string; account_email: string | null; connected_by_email?: string | null };
export const latestSourcePerProvider = (items: Source[]) => [...new Map(items.map((item) => [item.provider, item])).values()];
export type ToolCategory = "Arquivos" | "Documentação";
type RemoteFolder = CatalogFolder;
export type ScopeCatalog = { folders: RemoteFolder[]; root_files: { available: boolean; label: string }; all_accessible: { available: boolean; label: string } };
export type SavedQuery = { id: string; workspace_folder_id: string; name: string; query: string };
export type Evidence = { document_id: string; document_name: string; excerpt: string; page_number: number | null; source_url: string | null; source_provider?: string | null };
export type Answer = { answer: string | null; confidence: string; citations: Evidence[]; retrieval_status: string; coverage?: { total_folders: number; eligible_folders: number; pending_folders: number }; conversation_id?: string };
export type ConversationMessage = { id: string; role: "user" | "assistant"; content: string; contextName: string; contextId?: string; mentions?: MentionCandidate[]; providers?: string[]; allTools?: boolean; answer?: Answer; pending?: boolean; error?: string };
export type PersistedConversationMessage = { id: string; role: "user" | "assistant"; content: string; context: { providers?: string[]; mentions?: MentionCandidate[] } | null; response: Answer | null };
export type StaffCompany = { organization_id: string; name: string };
type StaffFolder = Folder & { failure_summary: { error_code: string; count: number }[] };
export type StaffOverview = { organization_id: string; name: string; folders: StaffFolder[] };

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
export const isUuid = (value: string | undefined): value is string => Boolean(value && UUID.test(value));
export const isInvitationToken = (value: string | undefined): value is string => Boolean(value && /^[A-Za-z0-9_-]{20,128}$/.test(value));
export const messageFor = (error: unknown) => error instanceof TypeError ? "Não conseguimos nos conectar ao serviço. Confira sua conexão e tente novamente." : error instanceof ApiError && error.status >= 500 ? "O serviço está temporariamente indisponível. Tente novamente em instantes." : error instanceof ApiError && error.status === 403 ? "Você não tem permissão para esta ação." : error instanceof Error ? error.message : "Ocorreu um erro inesperado.";
export const roleLabel = (role: Role) => ({ owner: "Responsável", admin: "Administrador", member: "Membro" })[role];
export const statusLabel = (status: string) => ({ ready: "Pronto", queued: "Na fila", syncing: "Sincronizando", partial_failure: "Com falhas", failed: "Falhou", pending: "Aguardando", connected: "Conectado", disconnected: "Desconectado", reauth_required: "Reconexão necessária" } as Record<string, string>)[status] ?? "Aguardando";
export const documentFailureLabel = (code: string | null) => ({
  source_file_unavailable: "A fonte conectada não permitiu ler este arquivo.",
  text_extraction_failed: "Não foi possível extrair texto; o arquivo pode estar danificado ou usar uma estrutura não suportada.",
  file_too_large: "O arquivo excede o tamanho máximo suportado para indexação.",
  file_encrypted: "O arquivo está protegido por senha e não pode ser lido.",
  ocr_budget_exceeded: "O limite de OCR desta sincronização foi atingido; o arquivo será tentado novamente na próxima.",
  ocr_failed: "Não foi possível reconhecer o texto deste arquivo escaneado.",
  ocr_document_too_large: "O documento escaneado tem páginas demais para o OCR automático.",
  empty_extracted_text: "Nenhum texto foi extraído. Se o PDF é escaneado, o OCR não está ativo neste ambiente; peça ao administrador para ativá-lo.",
  empty_document: "O documento está vazio (não há texto para indexar).",
} as Record<string, string>)[code ?? ""] ?? "Não há uma explicação disponível para este código.";
const providerFromName = (name: string) => ({
  "google drive": "google_drive",
  onedrive: "onedrive",
  sharepoint: "sharepoint",
  notion: "notion",
} as Record<string, string | undefined>)[name.trim().toLowerCase()];
export function ProviderMark({ provider, size = "md" }: { provider?: string | null; size?: "sm" | "md" }) {
  const key = providerKey(provider ?? "");
  if (["google", "onedrive", "sharepoint", "notion", "github", "teams"].includes(key)) return <ProviderLogo provider={key as ProviderLogoName} size={size === "sm" ? 18 : 26} />;
  return <HardDrive aria-hidden="true" size={size === "sm" ? 16 : 20} />;
}
export function LibraryNodeIcon({ item, size = 16 }: { item: LibraryNode; size?: number }) {
  const isRoot = item.kind === "source" || item.parent_id === null;
  const provider = isRoot ? item.source_provider ?? providerFromName(item.name) : undefined;
  if (provider) return <ProviderMark provider={provider} size={size <= 14 ? "sm" : "md"} />;
  if (item.kind === "folder" && item.external_id?.startsWith("notion:container:")) return item.mime_type === "application/x-notion-database" || item.mime_type === "application/x-notion-data_source" ? <Table2 size={size} /> : <FileText size={size} />;
  return item.kind === "file" ? <FileText size={size} /> : <FolderOpen size={size} />;
}
export function useLatestRequest<T>() {
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);
  const cancel = useCallback(() => controller.current?.abort(), []);
  const request = useCallback(async (path: string, onSuccess: (value: T) => void, onError: (error: unknown) => void, onSettled?: () => void) => {
    controller.current?.abort();
    const next = new AbortController();
    controller.current = next;
    try { const value = await api<T>(path, { signal: next.signal, cache: "no-store" }); if (!next.signal.aborted) onSuccess(value); }
    catch (error) { if (!next.signal.aborted) onError(error); }
    finally { if (!next.signal.aborted) onSettled?.(); }
  }, []);
  return { request, cancel };
}
export const companyPath = (companyId: string, suffix = "") => `/companies/${companyId}${suffix}`;
export const libraryPath = (companyId: string, sourceNodeId?: string | null) => companyPath(companyId, `/library${sourceNodeId ? `?source=${encodeURIComponent(sourceNodeId)}` : ""}`);
const retrievalMessage = (status: string) => status === "no_indexed_content" ? "Ainda não há conteúdo consultável neste escopo. Aguarde a sincronização ou escolha outra pasta." : status === "no_compatible_embeddings" ? "O conteúdo foi encontrado, mas a indexação de IA ainda não terminou. Tente novamente em alguns instantes." : status === "invalid_generation_output" ? "Encontrei trechos relevantes, mas não foi possível produzir uma resposta verificável. Tente novamente." : "Não encontrei evidência suficiente neste escopo para responder com segurança.";
export const answerText = (answer: Answer) => cleanAnswerForDisplay(answer.answer) || (answer.answer === null ? retrievalMessage(answer.retrieval_status) : "Confira as fontes abaixo.");
export const citationSourceKey = (citation: Evidence) => {
  if (!citation.source_url?.trim()) return `document:${citation.document_id}`;
  try {
    const source = new URL(citation.source_url.trim());
    source.hash = "";
    if (source.pathname !== "/") source.pathname = source.pathname.replace(/\/+$/, "");
    return `source:${source.toString()}`;
  } catch {
    return `source:${citation.source_url.trim()}`;
  }
};
export const compactCitations = (citations: Evidence[]): Evidence[] => {
  const grouped = new Map<string, Evidence>();
  for (const citation of citations) {
    const key = citationSourceKey(citation);
    const existing = grouped.get(key);
    if (!existing) {
      grouped.set(key, citation);
      continue;
    }
    if (!existing.source_url && citation.source_url) existing.source_url = citation.source_url;
    if (!existing.source_provider && citation.source_provider) existing.source_provider = citation.source_provider;
  }
  return [...grouped.values()];
};
