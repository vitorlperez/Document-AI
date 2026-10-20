import assert from "node:assert/strict";
import test from "node:test";
import { canManageMembers, impactSentence, parseSpaceFilter, scopeSummary, serializeSpaceFilter, spaceBadges } from "../app/spaces-model.ts";

const all = [{ id: "g", name: "Geral" }, { id: "r", name: "RH" }, { id: "d", name: "Diretoria" }];

test("filter parsing drops ids the user does not belong to", () => {
  assert.deepEqual(parseSpaceFilter("?spaces=r,zzz,d", all), ["r", "d"]);
  assert.deepEqual(parseSpaceFilter("", all), []);
  assert.equal(serializeSpaceFilter(["r", "d"]), "r,d");
});

test("badges collapse after the limit", () => {
  assert.deepEqual(spaceBadges(all, 2), { visible: ["Geral", "RH"], hiddenCount: 1 });
  assert.deepEqual(spaceBadges([], 2), { visible: [], hiddenCount: 0 });
});

test("scope summary never asks the user to pick a Space", () => {
  assert.equal(scopeSummary([], all), "Todos os meus Espaços (3)");
  assert.equal(scopeSummary(["r"], all), "RH");
  assert.equal(scopeSummary(["r", "d", "g"], all), "Todos os meus Espaços (3)");
});

test("who can manage members", () => {
  assert.equal(canManageMembers("admin", null), true);
  assert.equal(canManageMembers("member", "manager"), true);
  assert.equal(canManageMembers("member", "member"), false);
  assert.equal(canManageMembers("member", null), false);
});

test("impact sentence is plain Portuguese", () => {
  assert.equal(
    impactSentence("Bruno", { documents_lost: 214, conversations_hidden: 3, automations_paused: 1 }),
    "Bruno deixará de ver 214 documentos. 3 conversas terão trechos ocultados. 1 automação será pausada.");
  assert.equal(
    impactSentence("Ana", { documents_lost: 1, conversations_hidden: 0, automations_paused: 0 }),
    "Ana deixará de ver 1 documento.");
});
