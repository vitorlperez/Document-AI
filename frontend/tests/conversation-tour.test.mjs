import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const tour = read("conversation-tour.tsx");
const targets = [...tour.matchAll(/target: "([^"]+)"/g)].map((match) => match[1]);
const sources = ["product/chat-workspace.tsx", "product/shell.tsx", "product/account-menu.tsx", "product/notification-bell.tsx", "product/shared-ui.tsx", "product/org-menu.tsx", "mobile-nav.tsx", "product/conversation-history.tsx"].map(read).join("\n");

test("every tour step anchors on a data-tour attribute that still exists", () => {
  assert.ok(targets.length >= 8);
  for (const target of new Set(targets)) assert.ok(sources.includes(`data-tour="${target}"`), `missing data-tour="${target}"`);
});

test("tour covers only what exists in the empty chat of a first-time user", () => {
  for (const target of ["composer", "tools", "history", "new-conversation", "org", "notifications", "account", "navigation"]) assert.ok(targets.includes(target), target);
  assert.equal(targets.length, 8);
  // Steps for elements that only appear after the first answer must not come back.
  for (const target of ["suggestions", "sources", "answer-actions"]) assert.ok(!targets.includes(target), `step absent from the first-access empty chat: ${target}`);
  assert.doesNotMatch(tour, /DOCX|ClickUp|ao lado da conversa|primeira resposta/);
});

test("post-answer elements no longer carry orphan data-tour anchors", () => {
  assert.doesNotMatch(read("answer-actions.tsx"), /data-tour=/);
  assert.doesNotMatch(read("product/chat-workspace.tsx"), /data-tour="(sources|suggestions)"/);
});

test("desktop-only anchors fall back to the tab bar on mobile and a missing target never throws", () => {
  assert.match(tour, /mobileFallback = new Set\(\["history"\]\)/);
  assert.match(tour, /rect \? "" : "tour-highlight-fallback"/);
});

test("avatar carries a gear badge and an accessible account label", () => {
  const menu = read("product/account-menu.tsx");
  assert.match(menu, /Settings/);
  assert.match(menu, /<AvatarWithGear user=\{user\} \/>/);
  assert.match(menu, /Conta e configurações de/);
  assert.match(menu, /aria-haspopup="menu"/);
});
