import assert from "node:assert/strict";
import test from "node:test";

import { chatMentionPath, libraryFocusPath, locateQuery, parseChatBridge, parseLibraryFocus, withoutChatBridge } from "../app/nav-bridges.ts";

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";

test("chatMentionPath carries the node and the Space filter, and parses back", () => {
  const path = chatMentionPath("org-1", A, [B]);
  assert.equal(path, `/companies/org-1?mention=${A}&spaces=${B}`);
  const [, search] = path.split("?");
  assert.deepEqual(parseChatBridge(search), { mentionNodeIds: [A], spaceIds: [B] });
});

test("no Space filter means no spaces param; invalid ids never get into the URL", () => {
  assert.equal(chatMentionPath("org-1", A), `/companies/org-1?mention=${A}`);
  assert.equal(chatMentionPath("org-1", "not-an-id"), "/companies/org-1");
  assert.equal(chatMentionPath("org-1", A, ["x", B, B]), `/companies/org-1?mention=${A}&spaces=${B}`);
});

test("parseChatBridge drops invalid and duplicate ids", () => {
  assert.deepEqual(parseChatBridge(`?mention=${A}&mention=zzz&spaces=${B},${B},bad`), { mentionNodeIds: [A], spaceIds: [B] });
  assert.deepEqual(parseChatBridge(""), { mentionNodeIds: [], spaceIds: [] });
});

test("withoutChatBridge removes only the mention", () => {
  assert.equal(withoutChatBridge(`?mention=${A}&spaces=${B}`), `?spaces=${B}`);
  assert.equal(withoutChatBridge(`?mention=${A}`), "");
});

test("libraryFocusPath prefers the node, falls back to the cited document, refuses garbage", () => {
  assert.equal(libraryFocusPath("org-1", { nodeId: A, documentId: B }, [B]), `/companies/org-1/library?focus=${A}&spaces=${B}`);
  assert.equal(libraryFocusPath("org-1", { documentId: B }), `/companies/org-1/library?focusDoc=${B}`);
  assert.equal(libraryFocusPath("org-1", { documentId: "nope" }), null);
  assert.equal(libraryFocusPath("org-1", {}), null);
});

test("parseLibraryFocus round-trips and ignores invalid values", () => {
  assert.deepEqual(parseLibraryFocus(`?focus=${A}&focusDoc=${B}`), { nodeId: A, documentId: null });
  assert.deepEqual(parseLibraryFocus(`?focusDoc=${B}`), { nodeId: null, documentId: B });
  assert.equal(parseLibraryFocus("?focus=bad"), null);
  assert.equal(parseLibraryFocus(`?source=${A}`), null);
});

test("locateQuery builds the backend query with space_ids", () => {
  assert.equal(locateQuery("org-1", { nodeId: A, documentId: null }, [B]), `organization_id=org-1&node_id=${A}&space_ids=${B}`);
  assert.equal(locateQuery("org-1", { nodeId: null, documentId: B }), `organization_id=org-1&document_id=${B}`);
});

test("library list view (the default) also carries the Perguntar bridge and the focus marker", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("../app/product/library-screen.tsx", import.meta.url), "utf8");
  const row = source.slice(source.indexOf('className="library-file-row'));
  assert.match(source, /<li key=\{entry\.key\}[^>]*data-node-id=\{item\.id\}[^>]*data-focus=/, "list rows expose data-node-id/data-focus for the citation highlight");
  assert.match(row, /library-card-ask"[\s\S]{0,120}chatMentionPath\(company\.id, item\.id/, "list rows have the Perguntar button that opens the chat with the mention");
});

test("Perguntar is a compact icon action (grid: icon beside ⋯ plus menu item; list: icon button) with an accessible name and no visible label", async () => {
  const { readFile } = await import("node:fs/promises");
  const grid = await readFile(new URL("../app/product/library-grid.tsx", import.meta.url), "utf8");
  const screen = await readFile(new URL("../app/product/library-screen.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../app/library-view.css", import.meta.url), "utf8");
  assert.match(grid, /"Perguntar sobre esta pasta" : "Perguntar sobre este arquivo"/, "labels distinguish folder from file");
  assert.match(grid, /actions\.push\(\{ key: "ask"/, "grid menu carries the Perguntar item");
  assert.match(grid, /className="library-card-ask"[\s\S]{0,80}title=\{askLabel\} aria-label=\{`\$\{askLabel\}: \$\{item\.name\}`\}><MessageSquare size=\{16\} aria-hidden="true" \/><\/button>/, "grid icon button has tooltip + aria-label and no text");
  assert.match(screen, /library-card-ask"\)[\s\S]{0,260}title=\{isFolder \? "Perguntar sobre esta pasta"[\s\S]{0,300}<MessageSquare size=\{16\} aria-hidden="true" \/><\/button>/, "list icon button has tooltip + aria-label and no text");
  assert.match(css, /\.library-card \.library-card-ask \{ position: absolute;/, "grid action is absolutely placed, adding no height to the card");
  assert.doesNotMatch(css, /library-card-ask \{ display: inline-flex/, "the old pill style is gone");
});
