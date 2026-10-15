/** Ferramenta ("tool group") que o usuário enxerga. `google_drive` (OAuth) e `google_drive_sa` (pasta compartilhada)
 * continuam providers distintos no backend, mas são UMA ferramenta: "Google Drive". */
const GOOGLE_ALIASES = new Set(["google", "google_drive", "google_drive_sa"]);

export const toolGroup = (provider: string | null | undefined): string => GOOGLE_ALIASES.has(provider ?? "") ? "google_drive" : provider ?? "";
export const sameTool = (a: string | null | undefined, b: string | null | undefined): boolean => Boolean(a) && toolGroup(a) === toolGroup(b);
/** Chave usada nos filtros do chat (o backend aceita "google" como alias de google_drive + google_drive_sa). */
export const providerKey = (provider: string): string => toolGroup(provider) === "google_drive" ? "google" : provider;
export const toolLabel = (provider?: string | null): string => ({
  google: "Google Drive", google_drive: "Google Drive", google_drive_sa: "Google Drive", onedrive: "OneDrive",
  github: "GitHub", github_markdown: "GitHub Markdown", notion: "Notion", clickup: "ClickUp", slack: "Slack", teams: "Microsoft Teams",
} as Record<string, string>)[provider ?? ""] ?? (provider ? provider.replaceAll("_", " ") : "Fonte indexada");

type RootLike = { id: string; kind?: string; name: string; source_id?: string; source_provider?: string | null };
/** Raízes de biblioteca da mesma ferramenta viram uma só (a primeira); `merged_*` guarda todas as conexões agrupadas. */
export function mergeToolRoots<T extends RootLike>(roots: T[]): (T & { merged_source_ids?: string[]; merged_root_ids?: string[] })[] {
  const out: (T & { merged_source_ids?: string[]; merged_root_ids?: string[] })[] = [];
  const byGroup = new Map<string, number>();
  for (const root of roots) {
    const group = root.kind === "source" && root.source_provider ? toolGroup(root.source_provider) : null;
    if (group === "google_drive") {
      const label = toolLabel(group);
      const index = byGroup.get(group);
      if (index === undefined) { byGroup.set(group, out.length); out.push({ ...root, name: label, merged_source_ids: [root.source_id ?? ""], merged_root_ids: [root.id] }); }
      else { out[index].merged_source_ids!.push(root.source_id ?? ""); out[index].merged_root_ids!.push(root.id); }
    } else out.push(root);
  }
  return out;
}

type MergedRoot = RootLike & { merged_source_ids?: string[]; merged_root_ids?: string[] };
type ToolRef = { libraryNodeId?: string | null; sourceId: string };
/** A raiz (possivelmente agrupada) cobre a sincronização dessa conexão. */
export const rootCoversTool = (root: MergedRoot, tool: ToolRef): boolean =>
  root.id === tool.libraryNodeId || root.source_id === tool.sourceId
  || Boolean(root.merged_source_ids?.includes(tool.sourceId)) || Boolean(tool.libraryNodeId && root.merged_root_ids?.includes(tool.libraryNodeId));
/** Prefere a sincronização ativa quando a ferramenta agrupa mais de uma conexão. */
export function pickTool<T extends ToolRef & { state?: string }>(tools: T[], root: MergedRoot): T | undefined {
  const matches = tools.filter((tool) => rootCoversTool(root, tool));
  return matches.find((tool) => tool.state === "queued" || tool.state === "syncing") ?? matches[0];
}
