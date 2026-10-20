import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const darkBlock = css.slice(css.indexOf("\n.dark {\n  /* Botões [M56] — escuro."), css.indexOf("@theme inline"));

test("tema escuro: o fundo dos modais é o scrim neutro, não o primário menta a 40%", () => {
  assert.match(css, /:root\s*\{[^}]*--modal-backdrop:\s*color-mix\(in oklab, var\(--primary\) 40%/s);
  assert.match(darkBlock, /--modal-backdrop:\s*var\(--scrim\);/);
});

test("tema escuro: texto amber-700 (aviso de cota) é remapeado para um tom legível", () => {
  assert.match(darkBlock, /--color-amber-700:\s*#fbbf24;/);
});

test("checkbox e radio nativos herdam a cor da marca", () => {
  assert.match(css, /input\[type="checkbox"\],\s*input\[type="radio"\]\s*\{\s*accent-color:\s*var\(--btn-primary-bg\);/);
});
