import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { AutomationRecipients } from "../app/product/automation-recipients.tsx";
const items = [{ user_id: "ana", email: "ana@empresa.com", name: "ana", has_access: false, is_you: false }, { user_id: "me", email: "me@empresa.com", name: "me", has_access: true, is_you: true }];
const render = (props = {}) => renderToStaticMarkup(createElement(AutomationRecipients, { items, selected: ["ana"], loading: false, error: null, onChange() {}, onRetry() {}, ...props }));
test("destinatário sem acesso continua selecionável e apresenta aviso individual", () => {
  const html = render();
  assert.match(html, /type="search"/);
  assert.match(html, /Buscar por nome ou e-mail/);
  assert.match(html, /Sem acesso a todas as pastas: não receberá este resultado/);
  assert.match(html, /checked=""/);
  assert.doesNotMatch(html, /disabled=""/);
  assert.match(html, /me@empresa.com \(você\)/);
});
test("carregamento e erro não exibem permissões antigas; catálogo vazio é explícito", () => {
  assert.doesNotMatch(render({ loading: true }), /type="checkbox"/);
  const failed = render({ error: "Sem conexão" });
  assert.match(failed, /role="alert"/);
  assert.match(failed, /Tentar novamente/);
  assert.doesNotMatch(failed, /type="checkbox"/);
  assert.match(render({ items: [], selected: [] }), /Nenhum destinatário disponível/);
});
test("destinatários salvos fora do catálogo podem ser removidos", () => {
  assert.match(render({ selected: ["missing"] }), /Remover destinatários indisponíveis/);
  assert.doesNotMatch(render({ items: [{ ...items[0], has_access: null }], selected: [] }), /Sem acesso a todas as pastas:/);
});
