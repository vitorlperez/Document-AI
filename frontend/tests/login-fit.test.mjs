import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../app/custom-login.css", import.meta.url), "utf8");
const rule = (selector, source = css) => {
  const start = source.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `regra ${selector} ausente`);
  return source.slice(start, source.indexOf("}", start));
};
const mobile = css.slice(css.indexOf("@media (max-width: 767px)"), css.indexOf("}\n", css.indexOf("@media (max-width: 767px)") + 400));

test("login ocupa exatamente a altura da viewport no desktop (100vh com fallback para 100dvh)", () => {
  const page = rule(".login-page");
  assert.match(page, /height: 100vh; height: 100dvh;/);
  assert.match(page, /grid-template-rows: minmax\(0, 1fr\)/);
  assert.doesNotMatch(page, /(^|[^-])min-height: 100(dv)?h/);
});
test("a coluna da história não estica a página e o formulário só rola como último recurso", () => {
  assert.match(rule(".login-story"), /min-height: 0/);
  const side = rule(".login-form-side");
  assert.match(side, /min-height: 0/);
  assert.match(side, /overflow-y: auto/);
  assert.match(rule(".login-form-container"), /margin-block: auto/);
});
test("no mobile a página cresce com o conteúdo em vez de cortar o formulário", () => {
  assert.match(mobile, /\.login-page \{[^}]*height: auto; min-height: 100vh; min-height: 100dvh;/);
  assert.match(mobile, /\.login-form-side \{[^}]*min-height: 100dvh; overflow-y: visible;/);
});
test("espaçamentos verticais escalam com a altura (clamp com vh) e não há alturas fixas grandes", () => {
  for (const selector of [".login-story-content", ".login-form", ".login-divider", ".login-switch", ".login-security", ".login-preview"]) assert.match(rule(selector), /clamp\([^)]*vh/, selector);
  assert.doesNotMatch(rule(".login-story-content"), /padding-block: 70px/);
  assert.doesNotMatch(rule(".login-form-side"), /padding: 48px/);
});
test("alturas baixas compactam elementos secundários", () => {
  assert.match(css, /@media \(max-height: 820px\)[^}]*\.login-security \{ display: none; \}/s);
  assert.match(css, /@media \(max-height: 720px\)[^}]*\.login-preview \{ display: none; \}/s);
});
test("motion tokens e foco continuam em uso", () => {
  assert.match(css, /var\(--motion-fast\) var\(--ease-out\)/);
  assert.match(css, /outline: 3px solid var\(--focus-ring\)/);
});
