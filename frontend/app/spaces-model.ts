export type SpaceRef = { id: string; name: string };
const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;

export function parseSpaceFilter(search: string, allowed: SpaceRef[]): string[] {
  const raw = new URLSearchParams(search.startsWith("?") ? search : `?${search}`).get("spaces") ?? "";
  const known = new Set(allowed.map((space) => space.id));
  return [...new Set(raw.split(",").filter((id) => known.has(id)))];
}
export const serializeSpaceFilter = (ids: string[]) => ids.join(",");

export function spaceBadges(spaces: SpaceRef[], max = 2) {
  return { visible: spaces.slice(0, max).map((space) => space.name), hiddenCount: Math.max(0, spaces.length - max) };
}
export function scopeSummary(selected: string[], all: SpaceRef[]): string {
  if (selected.length === 0 || selected.length >= all.length) return `Todos os meus Espaços (${all.length})`;
  const names = selected.map((id) => all.find((space) => space.id === id)?.name).filter(Boolean) as string[];
  return names.length <= 2 ? names.join(", ") : `${names[0]} +${names.length - 1}`;
}
export function canManageMembers(orgRole: "owner" | "admin" | "member", myRole: "member" | "manager" | null) {
  return orgRole !== "member" || myRole === "manager";
}
export function impactSentence(name: string, impact: { documents_lost: number; conversations_hidden: number; automations_paused: number }) {
  const parts = [`${name} deixará de ver ${plural(impact.documents_lost, "documento", "documentos")}.`];
  if (impact.conversations_hidden) parts.push(`${plural(impact.conversations_hidden, "conversa terá", "conversas terão")} trechos ocultados.`);
  if (impact.automations_paused) parts.push(`${plural(impact.automations_paused, "automação será", "automações serão")} pausada${impact.automations_paused === 1 ? "" : "s"}.`);
  return parts.join(" ");
}
