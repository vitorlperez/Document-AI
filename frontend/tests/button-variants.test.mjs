import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { btn } from "../app/ui/button-variants.ts";
import { canEditAutomation } from "../app/product/automations-model.ts";
import { AutomationDeleteDialog } from "../app/product/automation-delete-dialog.tsx";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const globals = read("../app/globals.css");
const buttons = read("../app/buttons.css");
const block = (start) => { const i = globals.indexOf(start); return globals.slice(i, globals.indexOf("\n}\n", i)); };
const light = block(":root {");
const dark = block(".dark {");
const token = (blk, name) => blk.match(new RegExp(`${name}: (#[0-9a-fA-F]{6})`))?.[1];
const channel = (v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
const lum = (h) => { const n = parseInt(h.slice(1), 16); return 0.2126 * channel(n >> 16) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255); };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

// [variante, fg, [fundos nos estados repouso/hover/active]]
const solid = {
  primary: ["primary-fg", ["primary-bg", "primary-hover", "primary-active"]],
  secondary: ["secondary-fg", ["secondary-bg", "secondary-hover", "secondary-active"]],
  destructive: ["destructive-fg", ["destructive-bg", "destructive-hover", "destructive-active"]],
  "danger-soft": ["danger-soft-fg", ["danger-soft-bg", "danger-soft-hover", "danger-soft-active"]],
  success: ["success-fg", ["success-bg", "success-hover", "success-active"]],
  info: ["info-fg", ["info-bg", "info-hover", "info-active"]],
};

for (const [name, blk, panels] of [["claro", light, ["#ffffff", "#efeee5", "#eaede2"]], ["escuro", dark, ["#121c17", "#1b2a24", "#080e0b", "#243730"]]]) {
  test(`variantes sólidas/tonais têm contraste AA (≥4,5:1) em repouso, hover e press no tema ${name}`, () => {
    for (const [variant, [fg, bgs]] of Object.entries(solid)) for (const bg of bgs) {
      const f = token(blk, `--btn-${fg}`), b = token(blk, `--btn-${bg}`);
      assert.ok(f && b, `${variant}: tokens ${fg}/${bg} ausentes`);
      assert.ok(ratio(f, b) >= 4.5, `${variant} ${bg}: ${ratio(f, b).toFixed(2)}:1`);
    }
  });
  test(`ghost e danger-ghost legíveis (AA) sobre as superfícies e no hover, tema ${name}`, () => {
    for (const [fg, hovers] of [["ghost-fg", ["ghost-hover", "ghost-active"]], ["danger-ghost-fg", ["danger-soft-bg", "danger-soft-hover"]]]) {
      const f = token(blk, `--btn-${fg}`);
      for (const surface of panels) assert.ok(ratio(f, surface) >= 4.5, `${fg} sobre ${surface}: ${ratio(f, surface).toFixed(2)}:1`);
      for (const h of hovers) assert.ok(ratio(f, token(blk, `--btn-${h}`)) >= 4.5, `${fg} no hover ${h}`);
    }
  });
  test(`botão primário e destrutivo se distinguem do fundo (≥3:1, WCAG 1.4.11) no tema ${name}`, () => {
    for (const key of ["primary-bg", "destructive-bg"]) for (const surface of panels) assert.ok(ratio(token(blk, `--btn-${key}`), surface) >= 3, `${key} sobre ${surface}`);
  });
  test(`todos os tokens --btn-* existem no tema ${name}`, () => {
    const used = new Set([...buttons.matchAll(/var\(--(btn-[a-z-]+)\)/g)].map((m) => m[1]));
    const locals = new Set(["btn-bg", "btn-fg", "btn-hover", "btn-active", "btn-edge"]);
    for (const name of used) if (!locals.has(name)) assert.ok(token(blk, `--${name}`), `--${name}`);
  });
}

test("btn() compõe classes por variante e tamanho", () => {
  assert.equal(btn("primary"), "btn btn-primary");
  assert.equal(btn("danger-ghost", "sm", "sm:ml-auto"), "btn btn-danger-ghost btn-sm sm:ml-auto");
  assert.equal(btn("ghost", "icon"), "btn btn-ghost btn-icon");
});

test("CSS cobre variantes e estados hover/press/focus/disabled/loading só com tokens", () => {
  for (const v of ["primary", "secondary", "ghost", "destructive", "danger-soft", "danger-ghost", "success", "info"]) assert.match(buttons, new RegExp(`\\.btn-${v}\\b`), v);
  assert.match(buttons, /\.btn:not\(:disabled[^)]*\):hover/);
  assert.match(buttons, /:active/);
  assert.match(buttons, /\.btn:focus-visible/);
  assert.match(buttons, /\.btn:disabled/);
  assert.match(buttons, /aria-busy="true"/);
  assert.match(buttons, /var\(--motion-loop-spin\)/);
  assert.doesNotMatch(buttons, /\d+ms|cubic-bezier/);
  assert.match(globals, /@import "\.\/buttons\.css"/);
});

test("telas não usam mais botões neutros soltos: automação, integrações, biblioteca e equipe usam btn()", () => {
  assert.doesNotMatch(read("../app/product/automation-editor.tsx"), /automationButton/);
  for (const file of ["automations-screen", "automation-history", "automation-webhooks", "automation-report-view", "integrations-screen", "library-screen", "team-staff"]) assert.match(read(`../app/product/${file}.tsx`), /btn\("/, file);
  const screen = read("../app/product/automations-screen.tsx");
  assert.match(screen, /btn\("primary"\)\} aria-label=\{`Executar agora/);
  assert.match(screen, /btn\("secondary"\)\} aria-label=\{`Editar/);
  assert.match(screen, /btn\("ghost"\)\} aria-label=\{`Ver histórico/);
  assert.match(screen, /btn\("danger-ghost"[^)]*\)\}[^>]*aria-label=\{`Excluir automação/);
});

test("excluir: só criador, Owner e Admin", () => {
  assert.equal(canEditAutomation("owner", "u1", "u2"), true);
  assert.equal(canEditAutomation("admin", "u1", "u2"), true);
  assert.equal(canEditAutomation("member", "u1", "u1"), true);
  assert.equal(canEditAutomation("member", "u1", "u2"), false);
  assert.equal(canEditAutomation("member", "u1", null), false);
  assert.match(read("../app/product/automations-screen.tsx"), /canEditAutomation\(company\.role, item\.created_by_user_id, currentUserId\)/);
  assert.match(read("../app/product-app.tsx"), /currentUserId=\{user\?\.id\}/);
});

test("modal de exclusão: alertdialog com nome, aviso do histórico/PDFs e botão Excluir destrutivo", () => {
  const html = renderToStaticMarkup(createElement(AutomationDeleteDialog, { name: "Resumo semanal", busy: false, error: null, onConfirm() {}, onCancel() {} }));
  assert.match(html, /<dialog[^>]*role="alertdialog"[^>]*aria-modal="true"[^>]*aria-labelledby=/);
  assert.match(html, /aria-describedby=/);
  assert.ok(html.includes("Resumo semanal"));
  assert.match(html, /histórico de execuções e os PDFs/);
  assert.match(html, /btn btn-destructive[^>]*>Excluir</);
  assert.match(html, /btn btn-ghost[^>]*>Cancelar</);
  const busy = renderToStaticMarkup(createElement(AutomationDeleteDialog, { name: "A", busy: true, error: "falhou", onConfirm() {}, onCancel() {} }));
  assert.match(busy, /aria-busy="true"[^>]*>Excluindo…/);
  assert.match(busy, /role="alert"[^>]*>falhou/);
  const source = read("../app/product/automation-delete-dialog.tsx");
  for (const re of [/useDialogBackdropClose/, /\.showModal\(/, /closeDialogAnimated\(/, /trigger\?\.isConnected/, /onCancel=.*preventDefault\(\)/]) assert.match(source, re);
});

test("fluxo de exclusão: DELETE, toast de sucesso/erro e remoção animada com tokens", () => {
  const screen = read("../app/product/automations-screen.tsx");
  assert.match(screen, /method: "DELETE"/);
  assert.match(screen, /showToast\("success"/);
  assert.match(screen, /showToast\("error"/);
  assert.match(screen, /automation-card-leaving/);
  assert.match(screen, /exitDelayMs\(/);
  const css = read("../app/product/automation-modal.css");
  assert.match(css, /\.automation-card\.automation-card-leaving[^}]*var\(--motion-base\)/);
  assert.doesNotMatch(css, /\d+ms|cubic-bezier/);
});
