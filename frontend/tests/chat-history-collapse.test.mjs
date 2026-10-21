import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");

test("collapse state is remembered per membership and parsed safely", () => {
  const src = read("product/history-collapse.ts");
  assert.match(src, /arquivio:chat-history-collapsed:\$\{membershipId\}/);
  assert.match(src, /stored === "1"/);
});

test("the docked history has an accessible collapse button and the topbar a reopen button", () => {
  assert.match(read("product/conversation-history.tsx"), /aria-label="Recolher histórico" title="Recolher histórico/);
  assert.match(read("product/chat-workspace.tsx"), /aria-label="Mostrar histórico" title="Mostrar histórico/);
});

test("localStorage access is guarded with try/catch", () => {
  const src = read("product/chat-workspace.tsx");
  assert.match(src, /try \{ stored = window\.localStorage\.getItem\(collapseKey\)[^}]*\} catch/);
  assert.match(src, /try \{ window\.localStorage\.setItem\(collapseKey[^}]*\} catch/);
});

test("collapsed layout zeroes the sidebar track on desktop and honours reduced motion", () => {
  const css = read("chat-workspace.css");
  assert.match(css, /\.workspace-panels\.history-docked\.history-collapsed \{ --tools-sidebar-width: 0px; \}/);
  assert.match(css, /prefers-reduced-motion: reduce\) \{ \.history-reopen-btn \{ animation: none; \}/);
  assert.match(css, /@media \(max-width: 1023px\) \{ \.history-reopen-btn, \.history-collapse-btn \{ display: none; \}/);
});

test("the shortcut is listed in the shortcuts dialog", () => {
  assert.match(read("product/command-palette.tsx"), /Recolher ou mostrar o histórico/);
});
