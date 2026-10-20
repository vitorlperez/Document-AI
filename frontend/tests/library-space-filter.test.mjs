import assert from "node:assert/strict";
import test from "node:test";
import { buildLibraryQuery, parseLibraryView, serializeLibraryView, withSpaceHeadings } from "../app/library-view-logic.ts";

test("groupBySpace survives the round trip and rejects invalid values", () => {
  const view = { mode: "grid", size: "s", groupBySpace: true };
  assert.deepEqual(parseLibraryView(serializeLibraryView(view)), view);
  assert.equal(parseLibraryView('{"groupBySpace":"yes"}').groupBySpace, false);
  assert.equal(parseLibraryView('{"mode":"grid"}').groupBySpace, false);
});

test("the Space filter adds space_ids only when something is selected", () => {
  assert.equal(buildLibraryQuery({ spaces: [] }), "");
  assert.equal(buildLibraryQuery({ spaces: ["r"] }), "&space_ids=r");
  assert.equal(buildLibraryQuery({ spaces: ["r", "g"] }), "&space_ids=r&space_ids=g");
});

test("grouping by Space duplicates a shared item under each Space and keeps the unified list otherwise", () => {
  const items = [
    { id: "1", spaces: [{ id: "g", name: "Geral" }, { id: "r", name: "RH" }] },
    { id: "2", spaces: [{ id: "r", name: "RH" }] },
    { id: "3" },
  ];
  const entries = withSpaceHeadings(items, true);
  assert.deepEqual(entries.filter((e) => e.type === "heading").map((e) => [e.label, e.count]), [["Geral", 1], ["RH", 2], ["Sem Espaço informado", 1]]);
  assert.equal(new Set(entries.map((e) => e.key)).size, entries.length, "keys are unique");
  assert.equal(withSpaceHeadings(items, false).length, 3);
  assert.equal(withSpaceHeadings([{ id: "9" }], true).every((e) => e.type === "item"), true);
});
