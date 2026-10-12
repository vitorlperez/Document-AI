import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");

test("lane 1: toast da casca usa os primitives, mantém erro persistente e não usa next/link", () => {
  const shell = read("product/shell.tsx");
  assert.match(shell, /from "\.\.\/ui"/);
  assert.match(shell, /duration=\{error \? null : 6000\}/);
  assert.doesNotMatch(shell, /next\/link|<Link/);
  assert.doesNotMatch(shell, /rose-|emerald-|violet-/);
});

test("lane 1: abas têm indicador deslizante só com transform e menus saem animados", () => {
  const css = read("product/shell-motion.css");
  assert.match(css, /\.primary-tab-indicator/);
  assert.match(css, /scaleX\(var\(--tab-w/);
  assert.doesNotMatch(css, /\d+ms|cubic-bezier/);
  assert.doesNotMatch(css, /transition:[^;]*\b(width|height|left|top)\b/);
  for (const file of ["product/account-menu.tsx", "product/notification-bell.tsx"]) assert.match(read(file), /<Transition show=\{open\}/);
});

test("lane 1: sino tem skeleton, estado vazio e estados de espera acessíveis", () => {
  const bell = read("product/notification-bell.tsx");
  assert.match(bell, /<LoadingBlock/);
  assert.match(bell, /<EmptyState/);
  assert.match(bell, /<Spinner/);
});

test("lane 1: contratos preservados (data-tour, PENDING_NOTICE_KEY fora da casca)", () => {
  assert.match(read("product/shell.tsx"), /data-tour="navigation"/);
  assert.match(read("mobile-nav.tsx"), /data-tour="new-conversation"/);
  assert.match(read("product/account-menu.tsx"), /data-tour="account"/);
  assert.match(read("product/notification-bell.tsx"), /data-tour="notifications"/);
});
