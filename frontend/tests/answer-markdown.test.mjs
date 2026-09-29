// Runs with: node --import tsx --test tests/answer-markdown.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AnswerMarkdown } from "../app/answer-markdown.tsx";

const render = (text, fileNames = [], onCite = () => {}) => renderToStaticMarkup(createElement(AnswerMarkdown, { text, fileNames, onCite }));

test("file card: chip as header, summary and details inside the card body, no bullet on the chip", () => {
  const html = render("Resumo geral (fonte 1).\n\n::: file Profile.pdf\nCurrículo (fonte 1).\n- Python\n:::", ["Profile.pdf"]);
  assert.match(html, /<section class="answer-file-card" aria-label="Arquivo Profile.pdf"><h4 class="answer-file-card-header"><span class="answer-file-chip">/);
  assert.match(html, /answer-file-card-body"><p class="answer-file-summary">Currículo/);
  assert.doesNotMatch(html, /<li><span class="answer-file-chip">/);
  assert.match(html, /answer-file-group/);
});

test("(fonte N) becomes a small clickable number for known sources only", () => {
  const html = render("Fato (fonte 1). Outro (fontes 1 e 2). Fora (fonte 7).", ["A.pdf", "B.pdf"]);
  assert.equal((html.match(/<button type="button" class="answer-cite"/g) ?? []).length, 3);
  assert.match(html, /aria-label="Fonte 2: B.pdf"/);
  assert.match(html, /Fora \(fonte 7\)/);
  // Without sources to link to, the marker stays plain text.
  assert.match(renderToStaticMarkup(createElement(AnswerMarkdown, { text: "Fato (fonte 1)." })), /Fato \(fonte 1\)\./);
});

test("plain or malformed output still renders as markdown", () => {
  const html = render("Resposta direta.\n\n::: desconhecido\n- item\n\n::: file\ntexto", []);
  assert.match(html, /Resposta direta\./);
  assert.match(html, /<li>item<\/li>/);
  assert.match(html, /texto/);
});

test("css: citation pills stay compact despite the global 44px button minimum, and kv rows share one label column", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../app/chat-workspace.css", import.meta.url), "utf8");
  const cite = css.match(/\.product-app \.answer-cite[^{]*\{([^}]*)\}/)?.[1] ?? "";
  assert.match(cite, /min-height:\s*0/);
  assert.match(cite, /vertical-align:\s*super/);
  assert.match(cite, /line-height:\s*1\.\d+/);
  assert.match(css, /\.answer-fields\s*\{[^}]*grid-template-columns:\s*minmax\(8rem, max-content\) minmax\(0, 1fr\)/);
  assert.match(css, /\.answer-field\s*\{\s*display:\s*contents/);
});
