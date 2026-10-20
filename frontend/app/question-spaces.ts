/** Lógica pura dos Espaços no chat: filtro opcional, faixa "Procurando em…" e selos das citações. */
export type SpaceTag = { id: string; name: string };

/** Vazio = visão unificada (todos os contextos). Com filtro: só os contextos que algum dos Espaços escolhidos concede. */
export function contextsInSpaces<T extends { spaces?: SpaceTag[] }>(contexts: T[], spaceIds: readonly string[]): T[] {
  if (spaceIds.length === 0) return contexts;
  const wanted = new Set(spaceIds);
  return contexts.filter((context) => context.spaces?.some((space) => wanted.has(space.id)));
}
/** `space_ids` só vai na pergunta quando há filtro; vazio ⇒ omitido (a pergunta usa a união dos Espaços da pessoa). */
export const payloadSpaceIds = (spaceIds: readonly string[]): string[] | undefined => spaceIds.length ? [...spaceIds] : undefined;

/** Texto da faixa fixa sob o composer. */
export function lookingInLabel(selected: readonly string[], all: SpaceTag[]): string {
  const chosen = selected.map((id) => all.find((space) => space.id === id)?.name).filter(Boolean) as string[];
  if (chosen.length === 0 || chosen.length >= all.length) return all.length === 1 ? all[0].name : `todos os meus Espaços (${all.length})`;
  return chosen.length <= 2 ? chosen.join(", ") : `${chosen[0]} +${chosen.length - 1}`;
}

/** Espaços distintos citados na resposta, na ordem em que aparecem. */
export function citedSpaces(citations: { spaces?: SpaceTag[] }[]): SpaceTag[] {
  const seen = new Map<string, SpaceTag>();
  for (const citation of citations) for (const space of citation.spaces ?? []) if (!seen.has(space.id)) seen.set(space.id, space);
  return [...seen.values()];
}
/** “Fontes de: RH, Geral” só quando a resposta combina mais de um Espaço. */
export function sourcesFromLabel(citations: { spaces?: SpaceTag[] }[]): string | null {
  const spaces = citedSpaces(citations);
  return spaces.length > 1 ? `Fontes de: ${spaces.map((space) => space.name).join(", ")}` : null;
}
/** Une os selos de duas citações do mesmo arquivo (usado ao compactar citações repetidas). */
export function mergeSpaceTags(a: SpaceTag[] | undefined, b: SpaceTag[] | undefined): SpaceTag[] | undefined {
  if (!a?.length && !b?.length) return undefined;
  return citedSpaces([{ spaces: a }, { spaces: b }]);
}
