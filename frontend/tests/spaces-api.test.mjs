import assert from "node:assert/strict";
import test from "node:test";
import { addableCandidates, adminWithoutSpacesWarning, canEnterSpace, createSpacesApi, reachSentence, SpacesError, toSpacesError } from "../app/product/spaces-api.ts";

function recorder(reply = {}) {
  const calls = [];
  const api = createSpacesApi(async (path, init = {}) => { calls.push({ method: init.method ?? "GET", path, body: init.body ? JSON.parse(init.body) : undefined }); if (reply instanceof Error) throw reply; return reply; });
  return { api, calls };
}

test("each call builds the exact method, path and body", async () => {
  const { api, calls } = recorder();
  await api.listSpaces("o");
  await api.createSpace("o", { name: "RH" });
  await api.renameSpace("o", "s", { name: "Pessoas" });
  await api.archiveSpace("o", "s");
  await api.members("o", "s");
  await api.addMember("o", "s", "u", "manager");
  await api.setRole("o", "s", "u", "member");
  await api.removeMember("o", "s", "u");
  await api.impact("o", "s", "u");
  await api.grant("o", "s", "f");
  await api.revoke("o", "s", "f");
  await api.enter("o", "s");
  assert.deepEqual(calls.map((c) => `${c.method} ${c.path}`), [
    "GET /organizations/o/spaces", "POST /organizations/o/spaces", "PATCH /organizations/o/spaces/s", "DELETE /organizations/o/spaces/s",
    "GET /organizations/o/spaces/s/members", "POST /organizations/o/spaces/s/members", "PATCH /organizations/o/spaces/s/members/u",
    "DELETE /organizations/o/spaces/s/members/u", "GET /organizations/o/spaces/s/members/u/impact",
    "POST /organizations/o/spaces/s/folders/f", "DELETE /organizations/o/spaces/s/folders/f", "POST /organizations/o/spaces/s/enter",
  ]);
  assert.deepEqual(calls[5].body, { user_id: "u", role: "manager" });
  assert.deepEqual(calls[6].body, { role: "member" });
  assert.ok(calls[9].body.disclosure.text_version);
});

test("folders lists the organization's folders through the real route GET /workspace-folders?organization_id=", async () => {
  // Regressão: a aba "Pastas" chamava /organizations/{id}/workspace-folders, rota que não existe (404 em prd e local).
  const { api, calls } = recorder([]);
  await api.folders("o-1");
  assert.deepEqual(calls.map((c) => `${c.method} ${c.path}`), ["GET /workspace-folders?organization_id=o-1"]);
});

test("404/403/409/422 become typed errors", async () => {
  for (const [status, code] of [[404, "not_found"], [403, "forbidden"], [409, "conflict"], [422, "invalid"], [500, "unknown"]]) {
    const { api } = recorder(Object.assign(new Error("x"), { status }));
    await assert.rejects(api.listSpaces("o"), (e) => e instanceof SpacesError && e.code === code);
  }
  assert.equal(toSpacesError(new TypeError("net")).code, "unknown");
});

test("key reach sentences", () => {
  assert.equal(reachSentence({ spaces: ["RH", "Geral"], documents: 214 }), "Esta chave alcançará 214 documentos em: RH, Geral.");
  assert.equal(reachSentence({ spaces: ["Geral"], documents: 1 }), "Esta chave alcançará 1 documento em: Geral.");
  assert.equal(reachSentence({ spaces: [], documents: 0 }), "Esta chave não lerá nenhum documento: quem a criou não participa de nenhum Espaço.");
  assert.equal(reachSentence(undefined), null);
  assert.ok(adminWithoutSpacesWarning("admin", 0));
  assert.equal(adminWithoutSpacesWarning("admin", 2), null);
  assert.equal(adminWithoutSpacesWarning("member", 0), null);
  assert.equal(adminWithoutSpacesWarning("owner", null), null);
});

test("enter button only for admins who are not members; candidates skip current members", () => {
  assert.equal(canEnterSpace("admin", { my_role: null }), true);
  assert.equal(canEnterSpace("admin", { my_role: "member" }), false);
  assert.equal(canEnterSpace("member", { my_role: null }), false);
  const people = [{ user_id: "a", membership_id: "1", email: "Ána@x.com", role: "member" }, { user_id: "b", membership_id: "2", email: "bruno@x.com", role: "member" }, { user_id: null, membership_id: "3", email: "c@x.com", role: "member" }];
  assert.deepEqual(addableCandidates(people, [{ user_id: "b" }], "ana").map((p) => p.user_id), ["a"]);
  assert.deepEqual(addableCandidates(people, [], "").map((p) => p.user_id), ["a", "b"]);
});

test("only Spaces the person belongs to can filter reads", async () => {
  const { memberSpaces } = await import("../app/product/spaces-api.ts");
  assert.deepEqual(memberSpaces([{ id: "a", name: "Geral", my_role: "member" }, { id: "b", name: "Diretoria", my_role: null }, { id: "c", name: "RH", my_role: "manager" }]), [{ id: "a", name: "Geral" }, { id: "c", name: "RH" }]);
});

test("creator hint lists the creator's Spaces and is silent when there are none", async () => {
  const { creatorReachHint } = await import("../app/product/spaces-api.ts");
  assert.equal(creatorReachHint(["RH", "Geral"]), "Esta chave lerá apenas o que está nos seus Espaços: RH, Geral.");
  assert.equal(creatorReachHint([]), null);
});

test("changeFolders sends one PUT with the diff and the disclosure only when granting", async () => {
  const { api, calls } = recorder({ granted: [], revoked: [] });
  await api.changeFolders("o", "s", { grant: ["a"], revoke: ["b"] });
  await api.changeFolders("o", "s", { grant: [], revoke: ["b"] });
  assert.equal(`${calls[0].method} ${calls[0].path}`, "PUT /organizations/o/spaces/s/folders");
  assert.deepEqual([calls[0].body.grant, calls[0].body.revoke], [["a"], ["b"]]);
  assert.ok(calls[0].body.disclosure.text_version);
  assert.equal(calls[1].body.disclosure, undefined);
});
