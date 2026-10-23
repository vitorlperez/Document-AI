import assert from "node:assert/strict";
import test from "node:test";
import { apexToWwwRedirects } from "../app/canonical-host.mjs";
import { matchRedirect } from "../node_modules/vinext/dist/config/config-matchers.js";

const ctx = (host) => ({ host, cookies: {}, headers: new Headers(), query: new URLSearchParams() });
const redirect = (host, path) => matchRedirect(path, apexToWwwRedirects, ctx(host));

test("apex hosts are redirected permanently to www, preserving the path (login, API, callbacks)", () => {
  for (const path of ["/", "/login", "/api/auth/callback", "/invitations/abc"]) {
    const match = redirect("arquivio.com.br", path);
    assert.ok(match, `${path} should redirect`);
    assert.equal(match.permanent, true);
    assert.equal(match.destination, `https://www.arquivio.com.br${path === "/" ? "/" : path}`);
  }
});

test("the canonical www host and Railway's generated domain are never redirected", () => {
  assert.equal(redirect("www.arquivio.com.br", "/login"), null);
  assert.equal(redirect("frontend-production-e02d.up.railway.app", "/login"), null);
});

test("next.config wires the apex redirect and the login explains a 403 instead of the generic permission text", async () => {
  const { readFile } = await import("node:fs/promises");
  const config = await readFile(new URL("../next.config.ts", import.meta.url), "utf8");
  assert.match(config, /apexToWwwRedirects/);
  assert.match(config, /async redirects\(\)/);
  const login = await readFile(new URL("../app/product/custom-login.tsx", import.meta.url), "utf8");
  assert.match(login, /caught\.status === 403 \? "Não foi possível validar este endereço de acesso/);
});
