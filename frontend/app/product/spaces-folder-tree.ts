/** Modelo puro da árvore de pastas de um Espaço: pastas agrupadas por ferramenta/conexão, estado dos checkboxes e diff. */
import type { SpaceFolder } from "./spaces-api";

export type FolderGroup = { key: string; provider: string; label: string; account: string | null; folders: SpaceFolder[] };
export type CheckState = "checked" | "unchecked" | "indeterminate";

const fold = (text: string) => text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

/** Uma conexão (data source) = um grupo. Duas conexões da mesma ferramenta ficam distintas pela conta ou, sem conta visível, por "conexão N". */
export type ToolNames = { group: (provider: string | null | undefined) => string; label: (provider: string | null | undefined) => string };

export function groupFoldersByTool(folders: SpaceFolder[], names: ToolNames): FolderGroup[] {
  const { group: toolGroup, label: toolLabel } = names;
  const bySource = new Map<string, FolderGroup>();
  for (const folder of folders) {
    const provider = toolGroup(folder.source_provider) || "other";
    const key = folder.source_id ?? `${provider}:unknown`;
    const group = bySource.get(key) ?? { key, provider, label: toolLabel(provider === "other" ? null : provider), account: folder.source_account ?? null, folders: [] };
    group.folders.push(folder);
    bySource.set(key, group);
  }
  const groups = [...bySource.values()].sort((a, b) => a.label.localeCompare(b.label, "pt-BR") || (a.account ?? "").localeCompare(b.account ?? "", "pt-BR"));
  const perTool = new Map<string, number>();
  for (const group of groups) perTool.set(group.provider, (perTool.get(group.provider) ?? 0) + 1);
  const seen = new Map<string, number>();
  for (const group of groups) {
    group.folders.sort((a, b) => a.name.localeCompare(b.name, "pt-BR"));
    if (!group.account && (perTool.get(group.provider) ?? 0) > 1) { const n = (seen.get(group.provider) ?? 0) + 1; seen.set(group.provider, n); group.account = `conexão ${n}`; }
  }
  return groups;
}

export const groupState = (group: Pick<FolderGroup, "folders">, selected: ReadonlySet<string>): CheckState => {
  const chosen = group.folders.filter((folder) => selected.has(folder.id)).length;
  return chosen === 0 ? "unchecked" : chosen === group.folders.length ? "checked" : "indeterminate";
};

/** Marcar a ferramenta inteira marca todas as pastas dela; se já está inteira, desmarca todas. */
export function toggleGroup(group: Pick<FolderGroup, "folders">, selected: ReadonlySet<string>): Set<string> {
  const next = new Set(selected);
  const all = group.folders.every((folder) => next.has(folder.id));
  for (const folder of group.folders) { if (all) next.delete(folder.id); else next.add(folder.id); }
  return next;
}
export function toggleFolder(id: string, selected: ReadonlySet<string>): Set<string> {
  const next = new Set(selected);
  if (!next.delete(id)) next.add(id);
  return next;
}

/** Busca por nome da pasta, da ferramenta ou da conta; grupos sem resultado somem. */
export function filterGroups(groups: FolderGroup[], term: string): FolderGroup[] {
  const needle = fold(term.trim());
  if (!needle) return groups;
  return groups.flatMap((group) => {
    const groupHit = fold(`${group.label} ${group.account ?? ""}`).includes(needle);
    const folders = groupHit ? group.folders : group.folders.filter((folder) => fold(folder.name).includes(needle));
    return folders.length ? [{ ...group, folders }] : [];
  });
}

/** Diff entre o que o Espaço já tem e o que está marcado. */
export function folderDiff(initial: ReadonlySet<string>, selected: ReadonlySet<string>): { grant: string[]; revoke: string[] } {
  return { grant: [...selected].filter((id) => !initial.has(id)), revoke: [...initial].filter((id) => !selected.has(id)) };
}

export const selectedCountLabel = (n: number) => `${n} ${n === 1 ? "pasta selecionada" : "pastas selecionadas"}`;
