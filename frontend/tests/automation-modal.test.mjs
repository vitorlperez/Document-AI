import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AutomationEditor } from "../app/product/automation-editor.tsx";
import { AutomationSourceIcon } from "../app/product/automation-folder-picker.tsx";
import { newAutomationDraft } from "../app/product/automations-model.ts";
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const props = { fetchJson: async () => ({ items: [] }), organizationId: "org", initial: newAutomationDraft(), folders: [], loadRecipients: async () => [], canChooseRecipients: false, saving: false, serverError: null, onSave() {}, onCancel() {} };
test("criação e edição são diálogos nomeados com quatro etapas", () => {
  for (const editing of [false, true]) {
    const html = renderToStaticMarkup(createElement(AutomationEditor, { ...props, editing }));
    assert.match(html, /<dialog[^>]*role="dialog"[^>]*aria-modal="true"/);
    assert.ok(html.includes(editing ? "Editar automação" : "Criar automação"));
    assert.match(html, /Fechar automação/);
    assert.match(html, /Próximo/);
    assert.match(html, /Etapa 1 de 4/);
  }
});
test("modal reutiliza dismiss e saída da fundação, confirma alterações e restaura foco", () => {
  const source = read("../app/product/automation-editor.tsx");
  assert.match(source, /useDialogBackdropClose/);
  assert.match(source, /\.showModal\(/);
  assert.match(source, /onKeyDown=\{trapFocus\}/);
  assert.match(source, /event.key !== "Tab"/);
  assert.match(source, /onCancel=.*preventDefault\(\)/);
  assert.match(source, /window\.confirm\(/);
  assert.match(source, /JSON\.stringify\(draft\) !== JSON\.stringify\(initial\)/);
  assert.match(source, /closeDialogAnimated\(/);
  assert.match(source, /trigger\?\.isConnected/);
  assert.match(source, /trigger\.focus/);
  assert.match(read("../app/product/automations-screen.tsx"), /origin: event.currentTarget/);
  assert.doesNotMatch(read("../app/product/automations-screen.tsx"), /createButton\.current\?\.focus/);
});
test("superfície overlay usa tokens de motion e versão mobile em tela cheia", () => {
  const css = read("../app/product/automation-modal.css");
  for (const token of ["surface-overlay", "elev-3", "edge-strong", "motion-base", "ease-out", "ease-in", "scrim"]) assert.ok(css.includes(`var(--${token})`), token);
  assert.match(css, /@media.*max-width/);
  assert.match(css, /100dvh/);
  assert.doesNotMatch(css, /\d+ms|cubic-bezier/);
});
test("raízes reutilizam ProviderLogo da biblioteca e conversa com metadados e fallback", () => {
  for (const provider of ["google_drive", "onedrive", "sharepoint", "notion", "clickup"]) {
    const html = renderToStaticMarkup(createElement(AutomationSourceIcon, { node: { name: "Conta conectada", source_provider: provider } }));
    assert.ok(html.includes(`provider-logo-${provider === "google_drive" ? "google" : provider}`));
    assert.match(html, /aria-hidden="true"/);
  }
  assert.match(renderToStaticMarkup(createElement(AutomationSourceIcon, { node: { name: "Google Drive" } })), /provider-logo-google/);
  assert.match(renderToStaticMarkup(createElement(AutomationSourceIcon, { node: { name: "Fonte desconhecida", source_provider: "unknown" } })), /hard-drive/);
  assert.match(read("../app/product/automation-folder-picker.tsx"), /<AutomationSourceIcon node=\{node\}/);
});
