import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");
const screen = read("app/product/developer-screen.tsx");
const layout = read("app/product-layout.css");

// `.product-app .page-surface h1` (specificity 0,2,1) forces 17px and beats Tailwind's
// `text-2xl` utility, so the page title rendered smaller than the 20px section titles.
test("the Developer h1 has a rule that outranks the page-surface h1 override", () => {
  assert.match(screen, /<h1 className="[^"]*\bdeveloper-title\b/);
  const rule = layout.match(/\.product-app \.page-surface h1\.developer-title\s*\{[^}]*font-size:\s*(\d+)px/);
  assert.ok(rule, "missing .product-app .page-surface h1.developer-title { font-size }");
  const sectionTitle = 20; // Tailwind text-xl on the section h2 titles
  assert.ok(Number(rule[1]) >= sectionTitle + 4, `h1 is ${rule[1]}px, section h2 is ${sectionTitle}px`);
});

test("section titles stay as h2 at text-xl or smaller", () => {
  for (const file of ["app/product/developer-screen.tsx", "app/access-settings.tsx"]) {
    for (const [tag] of read(file).matchAll(/<h2 [^>]*>/g)) assert.match(tag, /text-(xl|lg|base)\b/, tag);
  }
});
