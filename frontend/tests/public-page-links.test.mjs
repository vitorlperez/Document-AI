import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import test from "node:test";

// Public, server-rendered pages. vinext's production bundle tree-shakes the navigation
// exports that <Link> loads lazily (navigateClientSide, getPrefetchCache...), so a click on
// a next/link throws "e is not a function" and the browser never navigates. Plain <a> works.
const pages = ["app/docs/api/page.tsx", "app/legal-layout.tsx"];

for (const file of pages) {
  const source = readFileSync(new URL(`../${file}`, import.meta.url), "utf8");

  test(`${file} navigates with plain anchors, not next/link`, () => {
    assert.doesNotMatch(source, /from\s+["']next\/link["']/);
    assert.doesNotMatch(source, /<Link[\s>]/);
  });

  test(`${file} only links to routes that exist`, () => {
    const hrefs = [...source.matchAll(/href="(\/[^"#?]*)/g)].map((match) => match[1]);
    assert.ok(hrefs.length > 0);
    for (const href of hrefs) {
      if (href.startsWith("/api/")) continue; // proxied backend contract, not an app route
      const route = href === "/" ? "app/page.tsx" : `app${href}/page.tsx`;
      assert.ok(existsSync(new URL(`../${route}`, import.meta.url)), `${href} has no ${route}`);
    }
  });
}
