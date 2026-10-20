import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const zOf = (source, pattern) => Number(source.match(pattern)?.[1]);

test("the desktop header paints above the chat slide-over so org/avatar/bell menus never sit under the history panel", () => {
  const header = read("product/shell.tsx").match(/<header className="([^"]*product-header[^"]*)"/)?.[1] ?? "";
  assert.match(header, /(^|\s)relative(\s|$)/, "z-index only applies to a positioned header outside a flex column");
  const headerZ = zOf(header, /(?:^|\s)z-(\d+)(?:\s|$)/);
  const slideOverZ = zOf(read("chat-workspace.css"), /\.conversation-history-presence \{[^}]*z-index: (\d+)/);
  assert.ok(headerZ > slideOverZ, `header z-${headerZ} must exceed slide-over z-${slideOverZ}`);
});

test("shell popovers are opaque raised surfaces above the page", () => {
  for (const file of ["org-menu.tsx", "account-menu.tsx", "notification-bell.tsx"]) {
    const source = read(`product/${file}`);
    assert.match(source, /shell-popover absolute [^"]*z-50/, file);
    assert.match(source, /bg-\[var\(--surface-raised\)\]/, file);
  }
});
