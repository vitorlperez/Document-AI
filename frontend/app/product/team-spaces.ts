/** Lógica pura da Equipe com Espaços (T-F7): coluna "Espaços" por pessoa e corpo do convite. */

export type SpaceMembers = { space: { id: string; name: string }; members: { email: string }[] };

/** E-mail (minúsculo) → nomes dos Espaços em que a pessoa está, na ordem em que os Espaços chegam. */
export function spacesByEmail(entries: SpaceMembers[]): Map<string, string[]> {
  const result = new Map<string, string[]>();
  for (const { space, members } of entries) {
    for (const member of members) {
      const key = member.email.trim().toLowerCase();
      result.set(key, [...(result.get(key) ?? []), space.name]);
    }
  }
  return result;
}
export const personSpacesLabel = (names: string[] | undefined) => names?.length ? names.join(", ") : "Nenhum Espaço";

export type InviteDraft = { email: string; role: "admin" | "member"; spaceIds: string[]; spacesKnown: boolean };
/** `space_ids` só vai quando a lista de Espaços carregou; vazio nunca é enviado (o servidor usa o Espaço padrão). */
export function inviteBody({ email, role, spaceIds, spacesKnown }: InviteDraft) {
  return { email, role, ...(spacesKnown && spaceIds.length ? { space_ids: spaceIds } : {}) };
}
/** Já indica o Espaço padrão (ou o único Espaço); com vários e sem padrão, a pessoa escolhe. */
export function defaultInviteSpaces(spaces: { id: string; is_default?: boolean }[]): string[] {
  const preset = spaces.filter((space) => space.is_default).map((space) => space.id);
  return preset.length ? preset : spaces.length === 1 ? [spaces[0].id] : [];
}
export const toggleInviteSpace = (selected: string[], id: string) => selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id];
