// Runs with: node --import tsx --test tests/answer-markdown.test.mjs
import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { AnswerMarkdown } from "../app/answer-markdown.tsx";

const render = (text, fileNames = [], onCite = () => {}) => renderToStaticMarkup(createElement(AnswerMarkdown, { text, fileNames, onCite }));

test("file card: chip as header, summary and details inside the card body, no bullet on the chip", () => {
  const html = render("Resumo geral (fonte 1).\n\n::: file Profile.pdf\nCurrículo (fonte 1).\n- Python\n:::", ["Profile.pdf"]);
  assert.match(html, /<section class="answer-file-card" aria-label="Arquivo Profile.pdf"><h4 class="answer-file-card-header"><span class="answer-file-name">/);
  assert.match(html, /<p class="answer-file-summary">Currículo/);
  assert.match(html, /class="answer-file-card-body"/);
  assert.doesNotMatch(html, /<li><span class="answer-file-(chip|name)">/);
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
  assert.match(css, /\.answer-fields\s*\{[^}]*grid-template-columns:\s*minmax\(6rem, max-content\) minmax\(0, 1fr\)/);
  assert.match(css, /\.answer-field\s*\{\s*display:\s*contents/);
});

test("tag values render as discrete tags followed by their citation", () => {
  const html = render("**Habilidades:** Grafana | LLM (fonte 1)", ["Profile.pdf"]);
  assert.match(html, /<span class="answer-tags"><span class="answer-tag">Grafana<\/span><span class="answer-tag">LLM<\/span><\/span>/);
  assert.match(html, /class="answer-cite"/);
});

const card = (name) => `::: file ${name}\nResumo de ${name} (fonte 1).\n- Detalhe\n:::`;

test("file cards: details open with 1-2 cards, collapsed from the 3rd card on, with an accessible toggle", () => {
  const two = render([card("A.pdf"), card("B.pdf")].join("\n\n"), ["A.pdf", "B.pdf"]);
  assert.equal((two.match(/aria-expanded="true"/g) ?? []).length, 2);
  assert.doesNotMatch(two, /answer-file-card-body" hidden/);
  const three = render(["A.pdf", "B.pdf", "C.pdf"].map(card).join("\n\n"), ["A.pdf", "B.pdf", "C.pdf"]);
  assert.equal((three.match(/<button type="button" class="answer-file-toggle" aria-expanded="false" aria-controls="/g) ?? []).length, 3);
  assert.equal((three.match(/class="answer-file-card-body" hidden/g) ?? []).length, 3);
  assert.match(three, /Ver mais/);
  // Summaries stay visible even when the details are collapsed.
  assert.match(three, /Resumo de C\.pdf/);
});

test("fluid prose with inline citations renders without file cards", () => {
  const html = render("A e B tratam do mesmo projeto (fontes 1 e 2).", ["A.pdf", "B.pdf"]);
  assert.doesNotMatch(html, /answer-file-card/);
  assert.equal((html.match(/class="answer-cite"/g) ?? []).length, 2);
});

test("css: compact answer density", async () => {
  const { readFileSync } = await import("node:fs");
  const css = readFileSync(new URL("../app/chat-workspace.css", import.meta.url), "utf8");
  assert.match(css, /\.answer-body\s*\{[^}]*font-size:\s*0\.8125rem[^}]*line-height:\s*1\.45/);
  assert.match(css, /\.answer-file-card-body\[hidden\]\s*\{\s*display:\s*none/);
});
