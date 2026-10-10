import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");

test("FollowToggle is wired next to the saved question in the chat", () => {
  const chat = read("product/chat-workspace.tsx");
  assert.match(chat, /import \{ FollowToggle \} from "\.\/follow-toggle"/);
  assert.match(chat, /<FollowToggle organizationId=\{company\.id\} savedQueryId=/);
});

test("usageLimitMessage maps the question 429 to a friendly message", () => {
  assert.match(read("product/chat-workspace.tsx"), /usageLimitMessage\(caught\) \?\? messageFor\(caught\)/);
});

test("NotificationBell is in the mobile header", () => {
  assert.match(read("mobile-nav.tsx"), /<header className="mobile-header"[\s\S]*<NotificationBell[\s\S]*<\/header>/);
});
