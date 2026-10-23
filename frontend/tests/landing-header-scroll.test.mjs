import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { HEADER_SCROLL_DELTA, nextHeaderState } from "../app/landing-header-scroll.mjs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const start = { hidden: false, lastY: 0 };

test("header stays visible near the top", () => {
  assert.deepEqual(nextHeaderState(start, 10), { hidden: false, lastY: 10 });
  assert.equal(nextHeaderState({ hidden: true, lastY: 500 }, 0).hidden, false);
  assert.equal(nextHeaderState({ hidden: true, lastY: 500 }, -40).lastY, 0);
});

test("scrolling down past the header hides it, scrolling up shows it", () => {
  const down = nextHeaderState({ hidden: false, lastY: 300 }, 340);
  assert.deepEqual(down, { hidden: true, lastY: 340 });
  assert.deepEqual(nextHeaderState(down, 320), { hidden: false, lastY: 320 });
});

test("movements under the threshold are ignored and accumulate", () => {
  const s = { hidden: false, lastY: 300 };
  assert.equal(nextHeaderState(s, 300 + HEADER_SCROLL_DELTA - 1), s);
  assert.equal(nextHeaderState(s, 300 - HEADER_SCROLL_DELTA + 1), s);
  assert.equal(nextHeaderState(s, 300 + HEADER_SCROLL_DELTA).hidden, true);
});

test("pinned (menu open / focus inside) always shows the header", () => {
  assert.deepEqual(nextHeaderState({ hidden: true, lastY: 300 }, 600, { pinned: true }), { hidden: false, lastY: 600 });
});

test("both landing pages share the single header with the model switch", () => {
  const shared = read("../app/landing-shared.tsx");
  const css = read("../app/landing.css");
  assert.match(shared, /useHidingHeader/);
  assert.match(shared, /aria-current=\{current === "pessoal" \? "page"/);
  assert.match(css, /\.landing-header-bar[^{]*\{[^}]*position: sticky/);
  assert.match(css, /scroll-margin-top/);
  for (const f of ["../app/landing-page.tsx", "../app/business-landing.tsx"]) assert.match(read(f), /current="(pessoal|empresa)"/);
});
