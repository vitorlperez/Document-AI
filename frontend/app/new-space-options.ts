export type CatalogFolder = { id: string; name: string; selectable?: boolean; parent_ids?: string[] };
export type ExistingSpace = { name: string; selection_kind?: string; selection_folder_ids?: string[] };
export type NewSpaceFolder = CatalogFolder & { coveredBy: string | null };

/** Folders offered for a new space: never one that already is a space; a folder
 * inside an existing space (or under "all accessible") names that space. */
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
    folders: catalog.filter((folder) => !spaceByFolder.has(folder.id)).map((folder) => ({ ...folder, coveredBy: coveringSpace(folder.id) })),
    allAccessibleTaken: Boolean(allAccessible),
  };
}
