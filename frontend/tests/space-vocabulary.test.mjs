import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// "Espaço" is reserved for the access-scoping concept; the legacy sync scope is a "Pasta conectada".
const files = [
  "../app/product/integrations-screen.tsx",
  "../app/product/library-screen.tsx",
  "../app/product/automation-folder-picker.tsx",
  "../app/new-space-options.ts",
];
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");

test("legacy sync scope is never called 'espaço' in user-visible text", () => {
  for (const file of files) {
    const source = read(file);
    // ClickUp's own hierarchy term ("Docs de espaços, pastas e listas") is the provider's vocabulary.
    const cleaned = source.replace("Docs de espaços, pastas e listas", "");
    assert.doesNotMatch(cleaned, /espa[çc]os?\b/i, `${file} still says "espaço"`);
  }
});

test("the connected-folder wording is present on the sync screens", () => {
  assert.match(read("../app/product/integrations-screen.tsx"), /Pasta conectada|pasta conectada|pastas conectadas/);
  assert.match(read("../app/product/library-screen.tsx"), /Pastas conectadas/);
});
