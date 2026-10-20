import assert from "node:assert/strict";
import test from "node:test";
import { defaultInviteSpaces, inviteBody, personSpacesLabel, spacesByEmail, toggleInviteSpace } from "../app/product/team-spaces.ts";

test("a coluna Espaços junta os Espaços de cada pessoa por e-mail", () => {
  const map = spacesByEmail([
    { space: { id: "g", name: "Geral" }, members: [{ email: "Ana@x.com" }, { email: "bruno@x.com" }] },
    { space: { id: "r", name: "RH" }, members: [{ email: "ana@x.com" }] },
  ]);
  assert.deepEqual(map.get("ana@x.com"), ["Geral", "RH"]);
  assert.equal(personSpacesLabel(map.get("ana@x.com")), "Geral, RH");
  assert.equal(personSpacesLabel(map.get("zz@x.com")), "Nenhum Espaço");
});

test("o convite já indica os Espaços e omite space_ids quando a lista não carregou", () => {
  const spaces = [{ id: "g", name: "Geral", is_default: true }, { id: "r", name: "RH" }];
  assert.deepEqual(defaultInviteSpaces(spaces), ["g"]);
  assert.deepEqual(toggleInviteSpace(["g"], "r"), ["g", "r"]);
  assert.deepEqual(inviteBody({ email: "a@x.com", role: "member", spaceIds: ["g", "r"], spacesKnown: true }), { email: "a@x.com", role: "member", space_ids: ["g", "r"] });
  assert.deepEqual(inviteBody({ email: "a@x.com", role: "member", spaceIds: ["g"], spacesKnown: false }), { email: "a@x.com", role: "member" });
  assert.deepEqual(inviteBody({ email: "a@x.com", role: "admin", spaceIds: [], spacesKnown: true }), { email: "a@x.com", role: "admin" });
});
