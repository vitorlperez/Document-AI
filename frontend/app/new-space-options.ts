export type CatalogFolder = { id: string; name: string; selectable?: boolean; parent_ids?: string[]; kind?: "folder" | "page" | "database" | "data_source" };
export type ExistingSpace = { name: string; selection_kind?: string; selection_folder_ids?: string[] };
/** `existingSpace` names the space that already is this folder: choosing it re-syncs that space completely. */
export type NewSpaceFolder = CatalogFolder & { coveredBy: string | null; existingSpace: string | null };

/** Remote ancestors are display metadata, not additional synchronization selections. */
export function catalogItemPath(item: CatalogFolder, catalog: CatalogFolder[]): string {
  const byId = new Map(catalog.map((entry) => [entry.id, entry]));
  const parts = [item.name];
  const seen = new Set([item.id]);
  let parentId = item.parent_ids?.[0];
  while (parentId && !seen.has(parentId)) {
    seen.add(parentId);
    const parent = byId.get(parentId);
    if (!parent) break;
    parts.unshift(parent.name);
    parentId = parent.parent_ids?.[0];
  }
  return parts.join(" / ");
}

/** Folders offered for a space. One that already is a space is flagged (`existingSpace`) because
 * selecting it is a complete re-sync; a folder inside an existing space (or under "all accessible")
 * names that space in `coveredBy`. `allAccessibleTaken` flags that "all accessible" already exists. */
export function newSpaceOptions(catalog: CatalogFolder[], spaces: ExistingSpace[]): { folders: NewSpaceFolder[]; allAccessibleTaken: boolean } {
  const allAccessible = spaces.find((space) => space.selection_kind === "all_accessible");
  const spaceByFolder = new Map<string, string>();
  for (const space of spaces) for (const id of space.selection_folder_ids ?? []) spaceByFolder.set(id, space.name);
  const parents = new Map(catalog.map((folder) => [folder.id, folder.parent_ids ?? []]));
  function coveringSpace(id: string): string | null {
    const seen = new Set<string>([id]);
    let pending = [...(parents.get(id) ?? [])];
    while (pending.length) {
      const next: string[] = [];
      for (const parent of pending) {
        if (seen.has(parent)) continue;
        seen.add(parent);
        const name = spaceByFolder.get(parent);
        if (name) return name;
        next.push(...(parents.get(parent) ?? []));
      }
      pending = next;
    }
    return allAccessible?.name ?? null;
  }
  return {
    folders: catalog.map((folder) => { const existingSpace = spaceByFolder.get(folder.id) ?? null; return { ...folder, existingSpace, coveredBy: existingSpace ? null : coveringSpace(folder.id) }; }),
    allAccessibleTaken: Boolean(allAccessible),
  };
}
