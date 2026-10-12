import assert from "node:assert/strict";
import test from "node:test";
import { filterRecipients, validateWebhookUrl } from "../app/product/automation-delivery-model.ts";
const recipients = [{ user_id: "a", name: "Ána Silva", email: "ana@empresa.com" }, { user_id: "b", name: null, email: "bruno@empresa.com" }];
test("busca destinatários por nome e e-mail, ignorando acentos e maiúsculas", () => {
  assert.deepEqual(filterRecipients(recipients, " ANA "), [recipients[0]]);
  assert.deepEqual(filterRecipients(recipients, "BRUNO@"), [recipients[1]]);
  assert.deepEqual(filterRecipients(recipients, ""), recipients);
  assert.deepEqual(filterRecipients(recipients, "inexistente"), []);
});
test("webhook exige HTTPS sem credenciais nem fragmentos", () => {
  assert.equal(validateWebhookUrl(" https://example.com/hook?tenant=1 "), null);
  for (const url of ["", "http://example.com", "javascript:alert(1)", "ftp://example.com", "https://u:p@example.com", "https://example.com/#secret", "https://example.com:8443", "nonsense"]) assert.ok(validateWebhookUrl(url));
});
