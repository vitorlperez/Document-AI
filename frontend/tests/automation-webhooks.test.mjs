import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
const read = (path) => readFileSync(new URL(`../app/product/${path}`, import.meta.url), "utf8");
const screen = read("automations-screen.tsx");
const editor = read("automation-editor.tsx");
const webhooks = read("automation-webhooks.tsx");
const contract = readFileSync(new URL("../../specs/automations-api.md", import.meta.url), "utf8");
test("catálogo consulta o escopo atual e as duas superfícies exigem Owner/Admin", () => {
  assert.match(screen, /company\.role === "owner" \|\| company\.role === "admin"/);
  assert.match(screen, /\{canManage && <AutomationWebhooks/);
  assert.match(screen, /canChooseRecipients=\{canManage\}/);
  assert.match(screen, /\/automation-recipients\?\$\{query\}/);
  assert.doesNotMatch(screen, /\/members/);
  assert.match(editor, /if \(!canChooseRecipients \|\| step !== 3\) return/);
  assert.match(editor, /draft\.folderIds\.map\(\(id\) => \["workspace_folder_ids", id\]\)/);
  assert.match(contract, /GET \/automation-recipients/);
});
test("cadastro envia evento contratado e separa o secret do objeto listado", () => {
  assert.match(webhooks, /const \{ secret: value, \.\.\.item \} = await api/);
  assert.match(webhooks, /events: \["automation.completed"\], enabled: true/);
  assert.match(webhooks, /setItems\(\(current\) => \[item, \.\.\.current\]\); setSecret\(value\)/);
  assert.match(webhooks, /navigator\.clipboard\.writeText\(secret\)/);
  assert.match(webhooks, /setSecret\(null\)/);
  assert.doesNotMatch(webhooks, /localStorage|sessionStorage|console\.log/);
  assert.match(contract, /POST \/webhook-endpoints/);
});
test("desativação usa PATCH, revogação confirmada usa DELETE e histórico limita entregas", () => {
  assert.match(webhooks, /method: "PATCH", body: JSON\.stringify\(\{ enabled: !item\.enabled \}\)/);
  assert.match(webhooks, /method: "DELETE"/);
  assert.match(webhooks, /Confirmar revogação/);
  assert.match(webhooks, /\/deliveries\?limit=20/);
  assert.match(webhooks, /items\.filter\(\(item\) => !item\.revoked_at\)/);
  assert.match(contract, /DELETE \/webhook-endpoints/);
  assert.match(contract, /deliveries\?limit=20/);
});
