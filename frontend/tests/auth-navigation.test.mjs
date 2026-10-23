import assert from "node:assert/strict";
import test from "node:test";
import { authCallbackMessage, hostedLoginQuery, safeInvitationReturnTo } from "../app/product/auth-navigation.mjs";

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

import { authErrorMessage } from "../app/product/auth-navigation.mjs";

test("auth errors never say 'sem permissão' and map to specific copy", () => {
  const err = (status, message = "") => Object.assign(new Error(message), { status });
  assert.match(authErrorMessage(err(403, "untrusted authentication proxy context")), /validar este acesso/);
  assert.match(authErrorMessage(err(403, "origin not allowed")), /validar este acesso/);
  assert.match(authErrorMessage(err(422)), /Confira os dados/);
  assert.match(authErrorMessage(err(429)), /Muitas tentativas/);
  assert.match(authErrorMessage(err(503, "authentication unavailable")), /temporariamente indisponível/);
  assert.match(authErrorMessage(err(502)), /temporariamente indisponível/);
  assert.equal(authErrorMessage(err(400, "Não foi possível iniciar o cadastro. Tente novamente ou entre na sua conta.")), "Não foi possível iniciar o cadastro. Tente novamente ou entre na sua conta.");
  assert.match(authErrorMessage(new TypeError("fetch failed")), /conectar/);
  for (const status of [400, 401, 403, 404, 409, 422, 429, 500, 503]) {
    assert.doesNotMatch(authErrorMessage(err(status)), /permiss/i);
  }
});

test("sign-up screen shows neutral copy with sign-in and forgot-password shortcuts", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("../app/product/custom-login.tsx", import.meta.url), "utf8");
  assert.match(source, /Se este e-mail ainda não tiver conta/);
  assert.match(source, /changeMode\("sign-in"\)[^]*Esqueci minha senha/);
  assert.doesNotMatch(source, /messageFor/);
});

test("a failed OAuth callback is explained by reason, never as raw JSON or a permission error", () => {
  for (const reason of ["state", "denied", "missing_code", "rejected", "unavailable", "rate_limited", "verification_required", "additional_step"]) {
    const message = authCallbackMessage(reason);
    assert.ok(message && message.length > 20, reason);
    assert.doesNotMatch(message, /authentication failed|permiss|\{|detail/i);
  }
  assert.match(authCallbackMessage("unknown-reason"), /Entre novamente/);
  assert.match(authCallbackMessage("__proto__"), /Entre novamente/);
  assert.equal(authCallbackMessage(null), undefined);
  assert.equal(authCallbackMessage(""), undefined);
});
