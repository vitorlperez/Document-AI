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
