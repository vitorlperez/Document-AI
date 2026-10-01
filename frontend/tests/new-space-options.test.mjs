import assert from "node:assert/strict";
import test from "node:test";

import { catalogItemPath, newSpaceOptions } from "../app/new-space-options.ts";

const catalog = [
  { id: "tda", name: "Test Document-AI", parent_ids: ["root"] },
  { id: "edicao", name: "3° Edição", parent_ids: ["root"] },
  { id: "pratico", name: "Prático", parent_ids: ["edicao"] },
  { id: "deep", name: "Deep", parent_ids: ["pratico"] },
];

test("a folder that already is a space is offered flagged as a complete re-sync", () => {
  const spaces = [{ name: "Test Document-AI", selection_kind: "selected", selection_folder_ids: ["tda"] }];
  const { folders } = newSpaceOptions(catalog, spaces);
  assert.deepEqual(folders.map((item) => item.id), ["tda", "edicao", "pratico", "deep"]);
  assert.equal(folders.find((item) => item.id === "tda").existingSpace, "Test Document-AI");
  assert.equal(folders.find((item) => item.id === "edicao").existingSpace, null);
});

test("a subfolder of an existing space is offered with a warning naming the space", () => {
  const spaces = [{ name: "3° Edição", selection_kind: "selected", selection_folder_ids: ["edicao"] }];
  const { folders } = newSpaceOptions(catalog, spaces);
  assert.equal(folders.find((item) => item.id === "tda").coveredBy, null);
  assert.equal(folders.find((item) => item.id === "pratico").coveredBy, "3° Edição");
  assert.equal(folders.find((item) => item.id === "deep").coveredBy, "3° Edição");
});

test("an all-accessible space covers every folder and is flagged as existing", () => {
  const spaces = [{ name: "Todo o Drive acessível", selection_kind: "all_accessible", selection_folder_ids: [] }];
  const { folders, allAccessibleTaken } = newSpaceOptions(catalog, spaces);
  assert.equal(allAccessibleTaken, true);
  assert.ok(folders.every((item) => item.coveredBy === "Todo o Drive acessível"));
});

test("a folder that is not a space is a plain first sync", () => {
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

test("Notion page paths disambiguate equal titles and preserve item types", () => {
  const pages = [
    { id: "a", name: "Operations", kind: "page" },
    { id: "b", name: "Sales", kind: "page" },
    { id: "x", name: "Runbook", kind: "page", parent_ids: ["a"] },
    { id: "y", name: "Runbook", kind: "page", parent_ids: ["b"] },
    { id: "db", name: "Tasks", kind: "database", parent_ids: ["a"] },
  ];
  assert.equal(catalogItemPath(pages[2], pages), "Operations / Runbook");
  assert.equal(catalogItemPath(pages[3], pages), "Sales / Runbook");
  assert.equal(newSpaceOptions(pages, []).folders[4].kind, "database");
  assert.equal(catalogItemPath({ id: "c", name: "C", parent_ids: ["c"] }, pages), "C");
});

test("Notion management offers only accessible roots, including standalone databases", () => {
  const pages = [
    { id: "parent", name: "Parent", kind: "page" },
    { id: "child", name: "Child", kind: "page", parent_ids: ["parent"] },
    { id: "grandchild", name: "Grandchild", kind: "page", parent_ids: ["child"] },
    { id: "nested-db", name: "Nested database", kind: "database", parent_ids: ["parent"] },
    { id: "collection", name: "Collection", kind: "data_source", parent_ids: ["nested-db"] },
    { id: "row", name: "Row", kind: "page", parent_ids: ["collection"] },
    { id: "db", name: "Standalone database", kind: "database" },
    { id: "shared", name: "Shared page", kind: "page", parent_ids: ["inaccessible"] },
  ];
  const spaces = [{ name: "Parent space", selection_kind: "selected", selection_folder_ids: ["parent"] }];
  const { folders } = newSpaceOptions(pages, spaces, "notion");
  assert.deepEqual(folders.map((item) => item.id), ["parent", "db", "shared"]);
  assert.equal(folders[0].existingSpace, "Parent space");
  assert.equal(folders[1].kind, "database");
  assert.equal(pages.length, 8);
  for (const provider of [undefined, "google_drive", "onedrive", "sharepoint"]) {
    assert.equal(newSpaceOptions(pages, spaces, provider).folders.length, 8);
  }
});

test("Notion root options retain all-content coverage and do not promote legacy child selections", () => {
  const spaces = [{ name: "Legacy child", selection_kind: "selected", selection_folder_ids: ["pratico"] }];
  const { folders } = newSpaceOptions(catalog, spaces, "notion");
  assert.deepEqual(folders.map((item) => item.id), ["tda", "edicao"]);
  assert.ok(folders.every((item) => item.existingSpace === null));
  const all = newSpaceOptions(catalog, [{ name: "Everything", selection_kind: "all_accessible" }], "notion");
  assert.equal(all.allAccessibleTaken, true);
  assert.ok(all.folders.every((item) => item.coveredBy === "Everything"));
});
