import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { AutomationFolderPicker } from "../app/product/automation-folder-picker.tsx";
import { AutomationEditor } from "../app/product/automation-editor.tsx";
import { newAutomationDraft } from "../app/product/automations-model.ts";
const render = (initial) => renderToStaticMarkup(createElement(AutomationEditor, { fetchJson: async () => ({ items: [] }), organizationId: "org", initial, folders: [], loadRecipients: async () => [], canChooseRecipients: false, saving: false, serverError: null, onSave() {}, onCancel() {} }));
test("editor apresenta quatro passos, nome rotulado e horário de hora cheia", () => {
  const html = render(newAutomationDraft());
  for (const text of ["1. Quando", "2. Onde", "3. O que fazer", "4. Entregar"]) assert.ok(html.includes(text));
  assert.match(html, /aria-current="step"/);
  assert.match(html, /Nome da automação<input/);
  assert.match(html, /type="time" step="3600"/);
  assert.match(html, /Fuso horário<input/);
});
test("mensal limita dia a 28 e gatilho de pasta remove controles de agenda", () => {
  const monthly = render({ ...newAutomationDraft(), frequency: "monthly" });
  assert.match(monthly, /type="number" min="1" max="28"/);
  const changed = render({ ...newAutomationDraft(), trigger: "folder_change" });
  assert.doesNotMatch(changed, /type="time"/);
  assert.match(changed, /após a sincronização/);
});

test("passo Onde navega a árvore de pastas indexadas e mostra o caminho completo das escolhidas", () => {
  const picker = readFileSync(new URL("../app/product/automation-folder-picker.tsx", import.meta.url), "utf8");
  assert.match(picker, /\/library\?organization_id=/);
  assert.match(picker, /\/library\/nodes\/\$\{node\.id\}\/children/);
  assert.match(picker, /\/library\/mention-candidates\?organization_id=/);
  assert.match(picker, /role="tree"/);
  const html = renderToStaticMarkup(createElement(AutomationFolderPicker, { fetchJson: async () => ({ items: [] }), organizationId: "org", selected: [{ id: "n", name: "2026", path: "Drive/Projetos/2026" }], onChange() {}, legacyNames: [] }));
  assert.ok(html.includes("Drive/Projetos/2026"));
  assert.match(html, /Remover 2026/);
  assert.match(html, /Buscar pasta/);
  assert.match(html, /qualquer pasta indexada/);
  const legacy = renderToStaticMarkup(createElement(AutomationFolderPicker, { fetchJson: async () => ({ items: [] }), organizationId: "org", selected: [], onChange() {}, legacyNames: ["Cliente A"] }));
  assert.match(legacy, /escopo anterior[^<]*Cliente A/);
});
