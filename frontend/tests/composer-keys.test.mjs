import assert from "node:assert/strict";
import test from "node:test";

import { shouldSubmitOnEnter } from "../app/composer-keys.ts";

const enter = (extra = {}) => ({ key: "Enter", shiftKey: false, keyCode: 13, nativeEvent: { isComposing: false }, ...extra });

test("Enter sends a non-empty question", () => assert.equal(shouldSubmitOnEnter(enter(), "oi", false), true));
test("Shift+Enter inserts a line break", () => assert.equal(shouldSubmitOnEnter(enter({ shiftKey: true }), "oi", false), false));
test("IME composition never sends", () => {
  assert.equal(shouldSubmitOnEnter(enter({ nativeEvent: { isComposing: true } }), "oi", false), false);
  assert.equal(shouldSubmitOnEnter(enter({ keyCode: 229 }), "oi", false), false);
});
test("blank text or busy composer never sends", () => {
  assert.equal(shouldSubmitOnEnter(enter(), "  \n ", false), false);
  assert.equal(shouldSubmitOnEnter(enter(), "oi", true), false);
});
test("other keys never send", () => assert.equal(shouldSubmitOnEnter(enter({ key: "a" }), "oi", false), false));
