import assert from "node:assert/strict";
import test from "node:test";
import { filterGroups, folderDiff, groupFoldersByTool, groupState, selectedCountLabel, toggleFolder, toggleGroup } from "../app/product/spaces-folder-tree.ts";

import { toolGroup, toolLabel } from "../app/tool-groups.ts";
const names = { group: toolGroup, label: toolLabel };
const f = (id, name, source_id, source_provider, source_account = null) => ({ id, name, status: "ready", spaces: [], source_id, source_provider, source_account });
const folders = [
  f("1", "poc-main", "s1", "google_drive", "a@x.com"), f("2", "arvore-1000", "s1", "google_drive", "a@x.com"),
  f("3", "Todo o Drive acessível", "s2", "google_drive_sa", "b@x.com"), f("4", "Contratos", "s3", "onedrive"),
];

test("groups per connection with the tool label and the account; folders sorted", () => {
  const groups = groupFoldersByTool(folders, names);
  assert.deepEqual(groups.map((g) => [g.label, g.account, g.folders.map((x) => x.name)]), [
    ["Google Drive", "a@x.com", ["arvore-1000", "poc-main"]], ["Google Drive", "b@x.com", ["Todo o Drive acessível"]], ["OneDrive", null, ["Contratos"]],
  ]);
});
test("two connections of one tool without a visible account are told apart", () => {
  const groups = groupFoldersByTool([f("1", "a", "s1", "notion"), f("2", "b", "s2", "notion")], names);
  assert.deepEqual(groups.map((g) => g.account), ["conexão 1", "conexão 2"]);
});
test("tool checkbox: indeterminate when partial, checks all, unchecks all", () => {
  const [drive] = groupFoldersByTool(folders, names);
  assert.equal(groupState(drive, new Set()), "unchecked");
  assert.equal(groupState(drive, new Set(["1"])), "indeterminate");
  const all = toggleGroup(drive, new Set(["1"]));
  assert.equal(groupState(drive, all), "checked");
  assert.equal(toggleGroup(drive, all).size, 0);
  assert.deepEqual([...toggleFolder("9", new Set(["1"]))].sort(), ["1", "9"]);
});
test("search matches folder, tool or account, ignoring accents/case", () => {
  const groups = groupFoldersByTool(folders, names);
  assert.deepEqual(filterGroups(groups, "ARVORE").map((g) => g.folders.map((x) => x.id)), [["2"]]);
  assert.equal(filterGroups(groups, "onedrive")[0].folders.length, 1);
  assert.equal(filterGroups(groups, "b@x")[0].folders[0].id, "3");
  assert.equal(filterGroups(groups, "zzz").length, 0);
});
test("diff and counter", () => {
  assert.deepEqual(folderDiff(new Set(["1", "2"]), new Set(["2", "3"])), { grant: ["3"], revoke: ["1"] });
  assert.equal(selectedCountLabel(1), "1 pasta selecionada");
  assert.equal(selectedCountLabel(3), "3 pastas selecionadas");
});
