/**
 * Seleção de pastas de um Espaço no nível das pastas: sincronização inteira (`scopes`) ou pasta da biblioteca com tudo o que
 * há abaixo (`nodes`, qualquer profundidade). Modelo puro, sem React: o tri-estado e a conversão ficam testáveis em node.
 *
 * Regras: marcar uma pasta marca tudo abaixo dela; desmarcar uma pasta coberta por um ancestral marcado converte o ancestral
 * nas pastas irmãs de cada nível do caminho (o pai fica indeterminado); a pasta marcada isoladamente só desmarca a si mesma.
 */
import type { TreeFolder } from "./spaces-api";
import type { CheckState } from "./spaces-folder-tree";

export type Selection = { scopes: ReadonlySet<string>; nodes: ReadonlySet<string> };
/** nó marcado → ele e seus ancestrais (basta a pertinência; usado para o estado indeterminado). */
export type Chains = ReadonlyMap<string, readonly string[]>;
/** Onde a pasta aparece: a sincronização e o caminho de ids da raiz da sincronização até ela (ela por último). */
export type NodeContext = { scopeId: string; path: readonly string[] };
/** Pastas já carregadas de um nível: `null` = as raízes da sincronização; um id = os filhos desse nó. */
export type Levels = (parentId: string | null) => readonly TreeFolder[] | undefined;

export const emptySelection = (): Selection => ({ scopes: new Set(), nodes: new Set() });
export const selectionSize = (selection: Selection) => selection.scopes.size + selection.nodes.size;

export function nodeState(ctx: NodeContext, selection: Selection, chains: Chains): CheckState {
  if (selection.scopes.has(ctx.scopeId) || ctx.path.some((id) => selection.nodes.has(id))) return "checked";
  const id = ctx.path[ctx.path.length - 1];
  for (const [selectedId, chain] of chains) if (selection.nodes.has(selectedId) && selectedId !== id && chain.includes(id)) return "indeterminate";
  return "unchecked";
}

/** Sincronização: marcada inteira, indeterminada (alguma pasta dela marcada) ou desmarcada. */
export function scopeState(scopeId: string, rootIds: readonly string[], selection: Selection, chains: Chains): CheckState {
  if (selection.scopes.has(scopeId)) return "checked";
  for (const [selectedId, chain] of chains) if (selection.nodes.has(selectedId) && rootIds.some((root) => chain.includes(root))) return "indeterminate";
  return "unchecked";
}

export function toggleScope(scopeId: string, selection: Selection): Selection {
  const scopes = new Set(selection.scopes);
  if (!scopes.delete(scopeId)) scopes.add(scopeId);
  return { scopes, nodes: selection.nodes };
}

/** Quem cobre a pasta, de cima para baixo: -1 = a sincronização inteira; i ≥ 0 = o ancestral `path[i]` (a própria pasta incluída). */
function coverers(ctx: NodeContext, selection: Selection): number[] {
  const found = ctx.path.flatMap((id, index) => selection.nodes.has(id) ? [index] : []);
  return selection.scopes.has(ctx.scopeId) ? [-1, ...found] : found;
}

/**
 * Alterna uma pasta. Devolve `null` quando o ancestral marcado precisaria ser convertido mas as pastas irmãs do caminho ainda
 * não foram carregadas (nunca acontece pela interface: o caminho só existe depois de expandido).
 */
export function toggleNode(ctx: NodeContext, selection: Selection, chains: Chains, levels: Levels): { selection: Selection; chains: Map<string, readonly string[]> } | null {
  const target = ctx.path[ctx.path.length - 1];
  const nextChains = new Map(chains);
  const nodes = new Set(selection.nodes);
  const covering = coverers(ctx, selection);
  const ancestors = covering.filter((index) => index < ctx.path.length - 1);
  if (ancestors.length === 0) {
    if (nodes.delete(target)) nextChains.delete(target); else { nodes.add(target); nextChains.set(target, [...ctx.path]); }
    return { selection: { scopes: selection.scopes, nodes }, chains: nextChains };
  }
  const top = ancestors[0];
  const scopes = new Set(selection.scopes);
  scopes.delete(ctx.scopeId);
  for (const index of ancestors) if (index >= 0) { nodes.delete(ctx.path[index]); nextChains.delete(ctx.path[index]); }
  nodes.delete(target); nextChains.delete(target);
  for (let depth = top + 1; depth < ctx.path.length; depth += 1) {
    const siblings = levels(depth === 0 ? null : ctx.path[depth - 1]);
    if (!siblings) return null;
    for (const sibling of siblings) {
      if (sibling.id === ctx.path[depth] || nodes.has(sibling.id)) continue;
      nodes.add(sibling.id); nextChains.set(sibling.id, [...ctx.path.slice(0, depth), sibling.id]);
    }
  }
  return { selection: { scopes, nodes }, chains: nextChains };
}

export type SelectionDiff = { grant: string[]; revoke: string[]; grantNodes: string[]; revokeNodes: string[] };
export function selectionDiff(initial: Selection, selected: Selection): SelectionDiff {
  const added = (before: ReadonlySet<string>, after: ReadonlySet<string>) => [...after].filter((id) => !before.has(id));
  return {
    grant: added(initial.scopes, selected.scopes), revoke: added(selected.scopes, initial.scopes),
    grantNodes: added(initial.nodes, selected.nodes), revokeNodes: added(selected.nodes, initial.nodes),
  };
}
export const diffSize = (diff: SelectionDiff) => diff.grant.length + diff.revoke.length + diff.grantNodes.length + diff.revokeNodes.length;

/** Cadeias das pastas já concedidas (servidor): a própria pasta + pai … raiz. */
export function chainsFromGrants(grants: readonly { node_id: string | null; ancestor_ids: readonly string[] }[]): Map<string, string[]> {
  return new Map(grants.flatMap((grant) => grant.node_id ? [[grant.node_id, [grant.node_id, ...grant.ancestor_ids]] as [string, string[]]] : []));
}

/** Grants órfãos: a pasta saiu do catálogo, então não há caixa para desmarcar; só se removem pelo id do grant. */
export const orphanGrants = <T extends { node_id: string | null }>(grants: readonly T[]): T[] => grants.filter((grant) => grant.node_id === null);
export const ORPHAN_LABEL = "Pasta não encontrada";

/** A pasta aparece marcada por um ancestral (ou pela sincronização inteira): desmarcá-la converte o ancestral em pastas irmãs. */
export const coveredByAncestor = (ctx: NodeContext, selection: Selection): boolean => coverers(ctx, selection).some((index) => index < ctx.path.length - 1);

export const selectedFoldersLabel = (n: number) => `${n} ${n === 1 ? "pasta selecionada" : "pastas selecionadas"}`;
