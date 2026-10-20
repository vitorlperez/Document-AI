import assert from "node:assert/strict";
import test from "node:test";
import { citedSpaces, contextsInSpaces, lookingInLabel, mergeSpaceTags, payloadSpaceIds, sourcesFromLabel } from "../app/question-spaces.ts";

const G = { id: "g", name: "Geral" }, R = { id: "r", name: "RH" }, D = { id: "d", name: "Diretoria" };
const contexts = [{ id: "1", spaces: [G] }, { id: "2", spaces: [G, R] }, { id: "3", spaces: [D] }, { id: "4" }];

test("empty filter is the union of every Space; a filter narrows the contexts", () => {
  assert.equal(contextsInSpaces(contexts, []).length, 4);
  assert.deepEqual(contextsInSpaces(contexts, ["r"]).map((c) => c.id), ["2"]);
  assert.deepEqual(contextsInSpaces(contexts, ["g", "d"]).map((c) => c.id), ["1", "2", "3"]);
});

test("the question payload only carries space_ids when filtered", () => {
  assert.equal(payloadSpaceIds([]), undefined);
  assert.deepEqual(payloadSpaceIds(["r"]), ["r"]);
});

test("the Looking-in band never asks to pick a Space", () => {
  assert.equal(lookingInLabel([], [G, R, D]), "todos os meus Espaços (3)");
  assert.equal(lookingInLabel(["r", "g"], [G, R, D]), "RH, Geral");
  assert.equal(lookingInLabel(["r", "g", "d"], [G, R, D]), "todos os meus Espaços (3)");
  assert.equal(lookingInLabel([], [G]), "Geral");
  assert.equal(lookingInLabel(["d"], [G, R, D, { id: "x", name: "X" }]), "Diretoria");
});

test("citations: combined Spaces get a sources label; merged duplicates accumulate badges", () => {
  assert.equal(sourcesFromLabel([{ spaces: [R] }, { spaces: [G] }, { spaces: [R] }]), "Fontes de: RH, Geral");
  assert.equal(sourcesFromLabel([{ spaces: [R] }, {}]), null);
  assert.equal(sourcesFromLabel([]), null);
  assert.deepEqual(citedSpaces([{ spaces: [G] }, { spaces: [G, R] }]), [G, R]);
  assert.deepEqual(mergeSpaceTags([G], [R, G]), [G, R]);
  assert.equal(mergeSpaceTags(undefined, undefined), undefined);
});
