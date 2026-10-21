import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { landingCtaMode, landingOrganizationName, shouldAutoEnterOrganization } from "../app/landing-session.mjs";

test("CTA mode: loading is neutral, signed-in goes to the app, failure counts as signed-out", () => {
  assert.equal(landingCtaMode({ status: "loading" }), "loading");
  assert.equal(landingCtaMode({ status: "authenticated", email: "a@b.co" }), "app");
  assert.equal(landingCtaMode({ status: "anonymous" }), "anonymous");
  assert.equal(landingCtaMode(undefined), "anonymous");
});

test("signed-in users stay on the landing at / but /login still enters the organization", () => {
  const base = { screen: "home", membershipCount: 1, hasResetToken: false };
  assert.equal(shouldAutoEnterOrganization({ ...base, pathname: "/" }), false);
  assert.equal(shouldAutoEnterOrganization({ ...base, pathname: "/login" }), true);
  assert.equal(shouldAutoEnterOrganization({ ...base, pathname: "/login", membershipCount: 2 }), false);
  assert.equal(shouldAutoEnterOrganization({ ...base, pathname: "/login", hasResetToken: true }), false);
});

test("organization label prefers the last entered, else the only one", () => {
  const companies = [{ id: "a", name: "Aurora" }, { id: "b", name: "Beta" }];
  assert.equal(landingOrganizationName(companies, "b"), "Beta");
  assert.equal(landingOrganizationName(companies, null), null);
  assert.equal(landingOrganizationName([companies[0]], null), "Aurora");
  assert.equal(landingOrganizationName([], "a"), null);
});

test("backend sends fresh logins to /login, not the public landing", () => {
  const source = readFileSync(new URL("../../backend/app/api/auth.py", import.meta.url), "utf8");
  assert.ok(!/else settings\.public_app_url\n/.test(source), "no default destination equal to the landing");
  assert.equal((source.match(/else f"\{settings\.public_app_url\.rstrip\('\/'\)\}\/login"/g) ?? []).length, 2);
});
