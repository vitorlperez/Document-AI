import assert from "node:assert/strict";
import test from "node:test";
import { automationPayload, automationToDraft, newAutomationDraft, scopeNames, triggerLabel, validateAutomationStep } from "../app/product/automations-model.ts";
const valid = () => ({ ...newAutomationDraft(), name: "Relatório", prompt: "Resuma os arquivos", scopeFolders: [{ id: "folder", name: "2026", path: "Drive/Projetos/2026" }], timezone: "America/Sao_Paulo" });
test("agenda converte domingo/segunda para os índices da API e mantém fuso", () => {
  assert.deepEqual(automationPayload(valid()).trigger_config, { frequency: "weekly", hour: 8, timezone: "America/Sao_Paulo", weekday: 0 });
  assert.equal(automationPayload({ ...valid(), weekday: 0 }).trigger_config.weekday, 6);
  assert.equal(automationPayload({ ...valid(), frequency: "monthly", monthDay: 28 }).trigger_config.day, 28);
  assert.equal("weekday" in automationPayload({ ...valid(), frequency: "daily" }).trigger_config, false);
});
test("gatilho de pasta envia configuração vazia e escopo por pastas indexadas (node_ids)", () => {
  const payload = automationPayload({ ...valid(), trigger: "folder_change", recipientIds: ["user-id"], email: true });
  assert.equal(payload.trigger_kind, "folder_changed");
  assert.deepEqual(payload.trigger_config, {});
  assert.deepEqual(payload.scope, { node_ids: ["folder"] });
  assert.deepEqual(payload.recipient_user_ids, ["user-id"]);
  assert.deepEqual(payload.output_formats, ["email", "pdf"]);
});
test("validação bloqueia horário fracionado, fuso inválido, escopo vazio e prompt longo", () => {
  for (let step = 0; step < 4; step++) assert.equal(validateAutomationStep(valid(), step), null);
  assert.match(validateAutomationStep({ ...valid(), time: "08:30" }, 0), /hora cheia/);
  assert.match(validateAutomationStep({ ...valid(), timezone: "Mars/City" }, 0), /fuso/);
  assert.match(validateAutomationStep({ ...valid(), frequency: "monthly", monthDay: 29 }, 0), /28/);
  assert.match(validateAutomationStep({ ...valid(), scopeFolders: [] }, 1), /pastas/);
  assert.match(validateAutomationStep({ ...valid(), scopeFolders: Array(21).fill({ id: "id", name: "a", path: "a" }) }, 1), /20/);
  assert.match(validateAutomationStep({ ...valid(), prompt: "a".repeat(1001) }, 2), /1000/);
  assert.equal(validateAutomationStep({ ...valid(), prompt: "a".repeat(1000) }, 2), null);
  assert.match(validateAutomationStep({ ...valid(), name: " " }, 0), /nome/);
});
test("edição mantém destinatários extras e exclui o criador da entrada", () => {
  const source = { name: "Relatório", trigger_kind: "schedule", trigger_config: { frequency: "weekly", hour: 8, weekday: 6, timezone: "America/Sao_Paulo" }, scope: { workspace_folder_ids: ["folder"] }, prompt: "Pergunta", template: "alert", output_formats: ["pdf"], recipients: [{ user_id: "creator", email: "a@x.com" }, { user_id: "other", email: "b@x.com" }], created_by_user_id: "creator" };
  const draft = automationToDraft(source);
  assert.equal(draft.weekday, 0);
  assert.equal(draft.template, "alert");
  assert.deepEqual(draft.recipientIds, ["other"]);
  assert.equal(draft.email, false);
  assert.equal(automationPayload(draft).trigger_config.weekday, 6);
});
test("gatilhos são descritos em português", () => {
  assert.equal(triggerLabel(valid()), "Toda segunda às 08h");
  assert.equal(triggerLabel({ ...valid(), trigger: "folder_change" }, ["Contratos"]), "Quando arquivos novos chegarem na pasta Contratos");
});

test("mudança de pasta não depende de parâmetros de agenda ocultos", () => {
  assert.equal(validateAutomationStep({ ...valid(), trigger: "folder_change", timezone: "bad", time: "bad", frequency: "monthly", monthDay: 31 }, 0), null);
});

test("edição lê pastas por caminho; pasta removida e escopo legado são preservados", () => {
  const base = { name: "R", trigger_kind: "folder_changed", trigger_config: {}, prompt: "P", template: "summary", output_formats: ["pdf"], recipients: [], created_by_user_id: "me" };
  const node = automationToDraft({ ...base, scope: { node_ids: ["a", "b"], folders: [{ node_id: "a", name: "2026", path: "Drive/Projetos/2026" }] } });
  assert.deepEqual(node.scopeFolders, [{ id: "a", name: "2026", path: "Drive/Projetos/2026" }, { id: "b", name: "Pasta indisponível", path: "Pasta indisponível" }]);
  assert.deepEqual(scopeNames(node), ["2026", "Pasta indisponível"]);
  assert.deepEqual(automationPayload(node).scope, { node_ids: ["a", "b"] });
  const legacy = automationToDraft({ ...base, scope: { workspace_folder_ids: ["w"] } });
  assert.equal(validateAutomationStep(legacy, 1), null);
  assert.deepEqual(automationPayload(legacy).scope, { workspace_folder_ids: ["w"] });
  assert.deepEqual(scopeNames(legacy, ["Cliente A"]), ["Cliente A"]);
  assert.equal(triggerLabel(node, ["2026"]), "Quando arquivos novos chegarem na pasta 2026");
});
