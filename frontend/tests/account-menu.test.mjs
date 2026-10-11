import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { accountMenuItems, avatarInitial, displayNameFromEmail } from "../app/product/account-helpers.ts";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");

test("avatarInitial prefers the name, falls back to the e-mail, then to ?", () => {
  assert.equal(avatarInitial("ana souza", "x@y.z"), "A");
  assert.equal(avatarInitial("", "vitor@x.com"), "V");
  assert.equal(avatarInitial(null, "  émerson@x.com"), "É");
  assert.equal(avatarInitial("", ""), "?");
  assert.equal(avatarInitial(undefined, undefined), "?");
});

test("displayNameFromEmail humanises the local part", () => {
  assert.equal(displayNameFromEmail("maria.silva@x.com"), "Maria Silva");
  assert.equal(displayNameFromEmail(""), "");
});

test("Administração and Desenvolvedor stay owner/admin only", () => {
  assert.deepEqual(accountMenuItems("member").map((item) => item.key), ["profile"]);
  assert.deepEqual(accountMenuItems("owner").map((item) => item.key), ["profile", "team", "admin", "developer"]);
  assert.deepEqual(accountMenuItems("admin").map((item) => item.key), ["profile", "admin", "developer"]);
});

test("header and mobile nav no longer carry admin/developer tabs or a loose logout", () => {
  for (const file of ["product/shell.tsx", "mobile-nav.tsx"]) {
    const source = read(file);
    assert.doesNotMatch(source, /label: "Administração"|label: "Desenvolvedor"|label: "Equipe"/);
    assert.doesNotMatch(source, /LogOut/);
    assert.match(source, /<AccountMenu /);
  }
});
