import assert from "node:assert/strict";
import test from "node:test";

import { newSpaceOptions } from "../app/new-space-options.ts";

const catalog = [
  { id: "tda", name: "Test Document-AI", parent_ids: ["root"] },
  { id: "edicao", name: "3° Edição", parent_ids: ["root"] },
  { id: "pratico", name: "Prático", parent_ids: ["edicao"] },
  { id: "deep", name: "Deep", parent_ids: ["pratico"] },
];

test("a folder that already is a space is never offered", () => {
  const spaces = [{ name: "Test Document-AI", selection_kind: "selected", selection_folder_ids: ["tda"] }];
  const { folders } = newSpaceOptions(catalog, spaces);
  assert.deepEqual(folders.map((item) => item.id), ["edicao", "pratico", "deep"]);
});

test("a subfolder of an existing space is offered with a warning naming the space", () => {
  const spaces = [{ name: "3° Edição", selection_kind: "selected", selection_folder_ids: ["edicao"] }];
  const { folders } = newSpaceOptions(catalog, spaces);
  assert.equal(folders.find((item) => item.id === "tda").coveredBy, null);
  assert.equal(folders.find((item) => item.id === "pratico").coveredBy, "3° Edição");
  assert.equal(folders.find((item) => item.id === "deep").coveredBy, "3° Edição");
});

test("an all-accessible space covers every folder and is not offered again", () => {
  const spaces = [{ name: "Todo o Drive acessível", selection_kind: "all_accessible", selection_folder_ids: [] }];
  const { folders, allAccessibleTaken } = newSpaceOptions(catalog, spaces);
  assert.equal(allAccessibleTaken, true);
  assert.ok(folders.every((item) => item.coveredBy === "Todo o Drive acessível"));
});

test("a folder is offered again after its space is deleted", () => {
  const { folders, allAccessibleTaken } = newSpaceOptions(catalog, []);
  assert.equal(allAccessibleTaken, false);
  assert.deepEqual(folders.map((item) => [item.id, item.coveredBy]),
    [["tda", null], ["edicao", null], ["pratico", null], ["deep", null]]);
});

test("cyclic or missing parents do not hang", () => {
  const cyclic = [{ id: "a", name: "A", parent_ids: ["b"] }, { id: "b", name: "B", parent_ids: ["a"] }, { id: "c", name: "C" }];
  const { folders } = newSpaceOptions(cyclic, [{ name: "X", selection_kind: "selected", selection_folder_ids: ["zzz"] }]);
  assert.deepEqual(folders.map((item) => item.coveredBy), [null, null, null]);
});
