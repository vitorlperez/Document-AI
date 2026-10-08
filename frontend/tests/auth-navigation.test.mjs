import assert from "node:assert/strict";
import test from "node:test";
import { hostedLoginQuery, safeInvitationReturnTo } from "../app/product/auth-navigation.mjs";

test("hosted fallback preserves the invitation from /login return_to", () => {
  const path = "/invitations/" + "a".repeat(43);
  const query = new URLSearchParams(hostedLoginQuery("sign-in", path));
  assert.equal(query.get("return_to"), path);
});

test("neither password login nor hosted fallback accepts an external return", () => {
  for (const unsafe of ["//evil.test", "https://evil.test", "/invitations/" + "a".repeat(43) + "?x=1", "/invitations/x", "/invitations/" + "a".repeat(43) + "\n"]) {
    assert.equal(safeInvitationReturnTo(unsafe), undefined);
    assert.equal(new URLSearchParams(hostedLoginQuery("sign-in", unsafe)).has("return_to"), false);
  }
});
