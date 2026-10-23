import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const grid = read("product/library-grid.tsx");
const css = read("library-view.css");
const motion = read("ui/motion-tokens.css");
const cardMenu = grid.slice(grid.indexOf("function CardMenu"), grid.indexOf("export type LibraryGridProps"));

test("the ⋯ menu is portalled to document.body: .mo-stagger-item keeps a transform (a containing block for position: fixed) and .library-grid is a scroll container, so an inline fixed menu is offset and clipped", () => {
  assert.match(grid, /import \{ createPortal \} from "react-dom"/);
  assert.match(cardMenu, /createPortal\(\s*<div ref=\{menu\} role="menu"[\s\S]*?document\.body\s*\)/);
  // The root cause is still in place (the card animates with fill-mode both), which is why the portal is mandatory.
  assert.match(motion, /\.mo-stagger-item \{[^}]*animation: mo-slide-in[^}]* both;/);
});

test("the portalled menu stays above page content and below toasts and modals", () => {
  const menuZ = Number(css.match(/\.library-card-menu \{[^}]*z-index: (\d+)/)?.[1]);
  const toastZ = Number(motion.match(/\.mo-toast-viewport \{[^}]*z-index: (\d+)/)?.[1]);
  assert.ok(menuZ >= 50, "above the sticky header (z-40) and slide-overs");
  assert.ok(menuZ < toastZ, `menu z-${menuZ} must stay below toasts z-${toastZ}`);
});

test("keyboard: Esc closes and returns focus to the ⋯ button, ArrowDown opens it, focus enters the menu", () => {
  assert.match(cardMenu, /event\.key === "Escape"[^\n]*close\(true\)/);
  assert.match(cardMenu, /trigger\.current\?\.focus\(/);
  assert.match(cardMenu, /event\.key === "ArrowDown" && !open/);
  assert.match(cardMenu, /\[role="menuitem"\]:not\(\[disabled\]\)'\)\?\.focus/);
});

test("the menu flips above / left of the trigger when it does not fit in the viewport", () => {
  assert.match(cardMenu, /window\.innerHeight - 8 \? Math\.max\(8, anchor\.top - box\.height - 4\)/);
  assert.match(cardMenu, /window\.innerWidth - box\.width - 8/);
});
