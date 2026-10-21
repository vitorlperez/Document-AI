import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync(new URL("../app/product/spaces-screen.tsx", import.meta.url), "utf8");
const bar = source.match(/className="(sticky [^"]*)" data-testid="folders-save-bar"/)?.[1] ?? "";

test("a barra de salvar das pastas existe e e fixa no rodape do painel", () => {
  assert.ok(bar, "folders-save-bar must be marked with data-testid");
  assert.match(bar, /\bsticky\b/);
});

test("a barra de salvar nao usa margem negativa (o padding do painel e sobrescrito por CSS global)", () => {
  assert.doesNotMatch(bar, /(^|\s)(sm:|md:|lg:)?-m[xlr]-/, "negative margins make the bar wider than the card");
});

test("a barra de salvar tem borda propria arredondada, alinhada ao conteudo", () => {
  assert.match(bar, /\brounded-lg\b/);
  assert.match(bar, /\bborder\b/);
});

test("a superficie da pagina corta com overflow: clip, senao o sticky da barra nunca gruda no viewport", () => {
  const css = readFileSync(new URL("../app/product-layout.css", import.meta.url), "utf8");
  const rule = css.match(/\.product-app \.page-surface \{([^}]*)\}/)?.[1] ?? "";
  assert.match(rule, /overflow:\s*clip/);
});
