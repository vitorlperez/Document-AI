import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AutomationEditor } from "../app/product/automation-editor.tsx";
import { newAutomationDraft } from "../app/product/automations-model.ts";
const render = (initial) => renderToStaticMarkup(createElement(AutomationEditor, { initial, folders: [], loadRecipients: async () => [], canChooseRecipients: false, saving: false, serverError: null, onSave() {}, onCancel() {} }));
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
