export type MentionLabelItem = { kind: "file" | "folder"; name?: string | null };

/**
 * "Arquivo: a.pdf · Pasta: Contratos" under the user's message. Conversations saved before the
 * name was persisted have mentions without one: they collapse to a count instead of "undefined".
 */
export function mentionSummary(mentions: MentionLabelItem[]): string {
  const named = mentions.filter((item) => item.name?.trim());
  const parts = named.map((item) => `${item.kind === "file" ? "Arquivo" : "Pasta"}: ${item.name!.trim()}`);
  for (const kind of ["file", "folder"] as const) {
    const count = mentions.filter((item) => item.kind === kind && !item.name?.trim()).length;
    if (count) parts.push(kind === "file" ? (count === 1 ? "1 arquivo mencionado" : `${count} arquivos mencionados`) : (count === 1 ? "1 pasta mencionada" : `${count} pastas mencionadas`));
  }
  return parts.join(" · ");
}
