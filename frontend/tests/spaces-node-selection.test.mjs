import assert from "node:assert/strict";
import test from "node:test";
import { chainsFromGrants, coveredByAncestor, diffSize, emptySelection, nodeState, scopeState, selectionDiff, toggleNode, toggleScope } from "../app/product/spaces-node-selection.ts";

// sincronização S: raízes R1 (Contratos) e R2 (Financeiro); Contratos → 2025, 2026; 2026 → T1, T2
const tree = { null: [{ id: "R1" }, { id: "R2" }], R1: [{ id: "A25" }, { id: "A26" }], A26: [{ id: "T1" }, { id: "T2" }] };
const levels = (parent) => tree[parent === null ? "null" : parent];
const ctx = (...path) => ({ scopeId: "S", path });
const sel = (scopes = [], nodes = []) => ({ scopes: new Set(scopes), nodes: new Set(nodes) });

test("marcar uma subpasta deixa os ancestrais e a sincronização indeterminados", () => {
  const out = toggleNode(ctx("R1", "A26", "T1"), emptySelection(), new Map(), levels);
  assert.deepEqual([...out.selection.nodes], ["T1"]);
  assert.equal(nodeState(ctx("R1", "A26", "T1"), out.selection, out.chains), "checked");
  assert.equal(nodeState(ctx("R1", "A26"), out.selection, out.chains), "indeterminate");
  assert.equal(nodeState(ctx("R1"), out.selection, out.chains), "indeterminate");
  assert.equal(nodeState(ctx("R2"), out.selection, out.chains), "unchecked");
  assert.equal(nodeState(ctx("R1", "A26", "T2"), out.selection, out.chains), "unchecked");
  assert.equal(scopeState("S", ["R1", "R2"], out.selection, out.chains), "indeterminate");
  assert.equal(scopeState("OUTRA", ["X"], out.selection, out.chains), "unchecked");
});

test("marcar a pasta marca tudo abaixo; marcar a sincronização inteira marca todas as pastas", () => {
  const folder = toggleNode(ctx("R1"), emptySelection(), new Map(), levels);
  for (const path of [["R1"], ["R1", "A26"], ["R1", "A26", "T2"]]) assert.equal(nodeState(ctx(...path), folder.selection, folder.chains), "checked");
  assert.equal(nodeState(ctx("R2"), folder.selection, folder.chains), "unchecked");
  const whole = toggleScope("S", emptySelection());
  assert.equal(scopeState("S", ["R1", "R2"], whole, new Map()), "checked");
  assert.equal(nodeState(ctx("R2"), whole, new Map()), "checked");
  assert.equal(nodeState(ctx("R1", "A26", "T1"), whole, new Map()), "checked");
  assert.equal(toggleScope("S", whole).scopes.size, 0);
});

test("desmarcar um filho da sincronização inteira converte em irmãs e deixa o pai indeterminado", () => {
  const out = toggleNode(ctx("R1", "A26", "T1"), sel(["S"]), new Map(), levels);
  assert.equal(out.selection.scopes.size, 0);
  assert.deepEqual([...out.selection.nodes].sort(), ["A25", "R2", "T2"]);
  assert.equal(nodeState(ctx("R1", "A26", "T1"), out.selection, out.chains), "unchecked");
  assert.equal(nodeState(ctx("R1", "A26", "T2"), out.selection, out.chains), "checked");
  assert.equal(nodeState(ctx("R1", "A25"), out.selection, out.chains), "checked");
  assert.equal(nodeState(ctx("R2"), out.selection, out.chains), "checked");
  assert.equal(nodeState(ctx("R1", "A26"), out.selection, out.chains), "indeterminate");
  assert.equal(nodeState(ctx("R1"), out.selection, out.chains), "indeterminate");
  assert.equal(scopeState("S", ["R1", "R2"], out.selection, out.chains), "indeterminate");
});

test("desmarcar um filho de uma pasta marcada converte só a partir dessa pasta", () => {
  const start = sel([], ["R1"]);
  assert.equal(coveredByAncestor(ctx("R1", "A26", "T1"), start), true);
  const out = toggleNode(ctx("R1", "A26", "T1"), start, new Map([["R1", ["R1"]]]), levels);
  assert.deepEqual([...out.selection.nodes].sort(), ["A25", "T2"]);
  assert.equal(nodeState(ctx("R1"), out.selection, out.chains), "indeterminate");
  assert.equal(nodeState(ctx("R1", "A26", "T1"), out.selection, out.chains), "unchecked");
});

test("pasta marcada sem ancestral só desmarca a si mesma, e remarcar volta ao estado anterior", () => {
  const first = toggleNode(ctx("R1", "A26"), emptySelection(), new Map(), levels);
  assert.equal(coveredByAncestor(ctx("R1", "A26"), first.selection), false);
  const off = toggleNode(ctx("R1", "A26"), first.selection, first.chains, levels);
  assert.equal(off.selection.nodes.size, 0);
  assert.equal(nodeState(ctx("R1"), off.selection, off.chains), "unchecked");
});

test("sem as pastas irmãs carregadas a conversão não adivinha", () => {
  assert.equal(toggleNode(ctx("R1", "A26", "T1"), sel(["S"]), new Map(), (parent) => parent === "A26" ? undefined : levels(parent)), null);
});

test("estado inicial vem das pastas concedidas (cadeia do servidor) e o diff separa sincronização de pasta", () => {
  const grants = [{ node_id: "T2", ancestor_ids: ["A26", "R1", "SRC"] }, { node_id: null, ancestor_ids: [] }];
  const chains = chainsFromGrants(grants);
  const initial = sel(["W"], ["T2"]);
  assert.equal(nodeState(ctx("R1"), initial, chains), "indeterminate");
  assert.equal(nodeState(ctx("R2"), initial, chains), "unchecked");
  const out = toggleNode(ctx("R2"), initial, chains, levels);
  const diff = selectionDiff(initial, { scopes: new Set(), nodes: out.selection.nodes });
  assert.deepEqual(diff, { grant: [], revoke: ["W"], grantNodes: ["R2"], revokeNodes: [] });
  assert.equal(diffSize(diff), 2);
  assert.equal(diffSize(selectionDiff(initial, initial)), 0);
});
