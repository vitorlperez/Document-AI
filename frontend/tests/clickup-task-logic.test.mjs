import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { buildTaskPayload, canCreateClickUpTask, clickUpConnected, initialForm, newIdempotencyKey, parseTags, validateForm } from "../app/clickup-task-logic.ts";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const connected = { source_provider: "clickup", source_status: "connected" };

test("the button shows only for an active ClickUp source on a persisted answer", () => {
  assert.equal(clickUpConnected([]), false);
  assert.equal(clickUpConnected([{ source_provider: "notion", source_status: "connected" }]), false);
  assert.equal(clickUpConnected([{ source_provider: "clickup", source_status: "reauth_required" }]), false);
  assert.equal(clickUpConnected([{ source_provider: "clickup", source_status: "disconnected" }]), false);
  assert.equal(clickUpConnected([{ source_provider: "clickup" }]), false); // older backend without the field: hidden
  assert.equal(clickUpConnected([{ source_provider: "google_drive", source_status: "connected" }, connected]), true);
  assert.equal(canCreateClickUpTask({ contexts: [connected], persisted: true, hasConversation: true }), true);
  assert.equal(canCreateClickUpTask({ contexts: [connected], persisted: false, hasConversation: true }), false);
  assert.equal(canCreateClickUpTask({ contexts: [connected], persisted: true, hasConversation: false }), false);
  assert.equal(canCreateClickUpTask({ contexts: [], persisted: true, hasConversation: true }), false);
});

test("the form starts from the suggested list, or the first one, or empty", () => {
  const lists = [{ id: "a", name: "A", path: "A" }, { id: "b", name: "B", path: "B" }];
  const base = { lists, name: "Título", description: "Corpo", footer: "f" };
  assert.equal(initialForm({ ...base, suggested_list_id: "b" }).listId, "b");
  assert.equal(initialForm({ ...base, suggested_list_id: "zzz" }).listId, "a");
  assert.equal(initialForm({ ...base, lists: [], suggested_list_id: null }).listId, "");
  assert.deepEqual(initialForm({ ...base, suggested_list_id: "a" }), { listId: "a", name: "Título", description: "Corpo", assignee: "", dueDate: "", priority: "", tags: "" });
});

test("tags are split, trimmed and de-duplicated", () => {
  assert.deepEqual(parseTags(" juridico,  contrato ;juridico\n  prazo   curto "), ["juridico", "contrato", "prazo curto"]);
  assert.deepEqual(parseTags(" , "), []);
});

test("payload keeps assignee, due date and priority optional", () => {
  const form = { listId: "L1", name: "  Revisar  ", description: " texto ", assignee: "", dueDate: "", priority: "", tags: "" };
  assert.deepEqual(buildTaskPayload(form), { list_id: "L1", name: "Revisar", description: "texto", assignees: [], due_date: null, priority: null, tags: [] });
  assert.deepEqual(buildTaskPayload({ ...form, assignee: "42", dueDate: "2026-11-03", priority: "2", tags: "a, b" }),
    { list_id: "L1", name: "Revisar", description: "texto", assignees: [42], due_date: "2026-11-03", priority: 2, tags: ["a", "b"] });
  assert.deepEqual(buildTaskPayload({ ...form, assignee: "abc" }).assignees, []);
});

test("validation blocks an empty list/title, too many tags and a bad date", () => {
  const form = { listId: "L1", name: "x", description: "", assignee: "", dueDate: "", priority: "", tags: "" };
  assert.equal(validateForm(form), null);
  assert.match(validateForm({ ...form, listId: "" }), /lista/);
  assert.match(validateForm({ ...form, name: "  " }), /título/);
  assert.match(validateForm({ ...form, tags: Array.from({ length: 11 }, (_, i) => `t${i}`).join(",") }), /etiquetas/);
  assert.match(validateForm({ ...form, dueDate: "03/11/2026" }), /Prazo/);
});

test("each call yields a fresh key accepted by the backend format", () => {
  const first = newIdempotencyKey(), second = newIdempotencyKey();
  assert.notEqual(first, second);
  assert.match(first, /^[A-Za-z0-9_-]{16,128}$/);
});

test("wiring: the chat passes the connection state and the modal sends the Idempotency-Key header once per opening", () => {
  assert.match(read("product/chat-workspace.tsx"), /<AnswerActions [^>]*clickUpEnabled=\{clickUpConnected\(contexts\)\}/);
  const actions = read("answer-actions.tsx");
  assert.match(actions, /clickUpEnabled/);
  assert.match(actions, /Criar tarefa no ClickUp/);
  const modal = read("clickup-task-modal.tsx");
  assert.match(modal, /useState\(\(\) => newIdempotencyKey\(\)\)/);
  assert.match(modal, /"Idempotency-Key": key/);
  assert.match(modal, /O conteúdo será visível para quem acessa esta lista no ClickUp/);
  assert.match(modal, /<ModalOverlay/);
});
