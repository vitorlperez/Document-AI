import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");

test("the chat topbar history button is addressable so the mobile drawer can open it", () => {
  assert.match(read("product/chat-workspace.tsx"), /<button type="button" data-tour="history" onClick=\{\(\) => setHistoryOpen/);
});

test("the mobile drawer has a Conversas entry that opens the history", () => {
  const nav = read("mobile-nav.tsx");
  assert.match(nav, /\[data-tour="history"\]/);
  assert.match(nav, /onClick=\{showHistory\}><History[^>]*\/>Conversas/);
});

test("mobile history is a full-width sheet with 44px touch targets", () => {
  const css = read("mobile-chat.css");
  assert.match(css, /\.conversation-panel > \.conversation-history \{ inset: 0; width: 100%;/);
  assert.match(css, /\.conversation-history li > button[^{]*\{ min-height: 44px; min-width: 44px; \}/);
});
