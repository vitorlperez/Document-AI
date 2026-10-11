const FALLBACK = "Não foi possível concluir esta ação.";

/** Readable reason from an API error body: our own string `detail`, or FastAPI's validation list ("campo: motivo"). */
export function errorDetail(body: unknown): string {
  const detail = typeof body === "object" && body !== null && "detail" in body ? (body as { detail: unknown }).detail : null;
  if (typeof detail === "string") return detail || FALLBACK;
  if (!Array.isArray(detail)) return FALLBACK;
  const reasons = detail.flatMap((item): string[] => {
    if (typeof item !== "object" || item === null || typeof item.msg !== "string") return [];
    const where = Array.isArray(item.loc) ? item.loc.filter((part: unknown) => part !== "body" && part !== "query").join(".") : "";
    return [where ? `${where}: ${item.msg}` : item.msg];
  });
  return reasons.length ? `Dados recusados pelo servidor — ${reasons.join("; ")}` : FALLBACK;
}
