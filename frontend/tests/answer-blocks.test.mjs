import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

import { CITATION_MARKER, citationNumbers, parseAnswerBlocks } from "../app/answer-blocks.ts";

const experienceFixture = JSON.parse(readFileSync(new URL("../../artifacts/chat-answer-format/fixture.json", import.meta.url)));

test("screenshot: blank lines keep all four cited experiences in one ordered list", () => {
  for (const text of [experienceFixture.raw, experienceFixture.answer, experienceFixture.answer.replace(/^\d+\./gm, "1.")]) {
    const blocks = parseAnswerBlocks(text);
    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].ordered, true);
    assert.equal(blocks[0].items.length, 4);
    assert.match(blocks[0].items[2].text, /Estoca/);
    assert.match(blocks[0].items[3].text, /Allstacks/);
  }
});

test("loose lists preserve an initial start and indented paragraphs and subitems", () => {
  const [list] = parseAnswerBlocks("3. Empresa — cargo\n   período (fonte 1).\n\n   Destaque curto (fonte 2).\n\n   - Detalhe\n\n4. Outra empresa (fonte 3).");
  assert.equal(list.start, 3);
  assert.equal(list.items.length, 2);
  assert.equal(list.items[0].text, "Empresa — cargo período (fonte 1).");
  assert.deepEqual(list.items[0].paragraphs, ["Destaque curto (fonte 2)."]);
  assert.deepEqual(list.items[0].sub, ["Detalhe"]);
});

test("lists stop at prose, headings and a changed marker type; explicit new sections restart", () => {
  const blocks = parseAnswerBlocks("1. A\n\n2. B\n\nObservação independente.\n\n## Outra lista\n1. C\n- D");
  assert.deepEqual(blocks.map(b => b.kind), ["list", "paragraph", "heading", "list", "list"]);
  assert.deepEqual(blocks.filter(b => b.kind === "list").map(b => b.items.length), [2, 1, 1]);
});

test("renders the prompt's answer shape: lead summary, short sections, lists and tables", () => {
  const answer = [
    "O catálogo tem **2 arquivos**: um texto religioso e um currículo [1][2].",
    "",
    "## Arquivos",
    "- A Gravidade do pecado de impuresa: sermão sobre pureza [1].",
    "- Profile.pdf: currículo de engenheiro de software [2].",
    "",
    "## Comparação",
    "| Arquivo | Tipo |",
    "| --- | --- |",
    "| Profile.pdf | Currículo |",
  ].join("\n");
  const blocks = parseAnswerBlocks(answer);
  assert.deepEqual(blocks.map((block) => block.kind), ["paragraph", "heading", "list", "heading", "table"]);
  assert.equal(blocks[2].items.length, 2);
  assert.deepEqual(blocks[4].rows, [["Profile.pdf", "Currículo"]]);
});

test("keeps each catalog row as its own list item instead of one run-on paragraph", () => {
  const blocks = parseAnswerBlocks([
    "Arquivos no catálogo autorizado:",
    "- A Gravidade.pdf: Síntese extrativa do conteúdo indexado: trecho curto…",
    "- Profile.pdf: Síntese extrativa do conteúdo indexado: outro trecho…",
  ].join("\n"));
  assert.equal(blocks[0].kind, "paragraph");
  assert.equal(blocks[1].kind, "list");
  assert.equal(blocks[1].items.length, 2);
});

const SCREENSHOT = [
  "Há dois arquivos na pasta; abaixo seguem os nomes e um resumo de cada um.",
  "",
  "## Arquivos e resumos",
  "",
  "::: file A Gravidade do pecado de impuresa (fonte 1)",
  "Só o título está indexado; não há conteúdo suficiente para resumir.",
  ":::",
  "",
  "::: file Profile.pdf",
  "Currículo de engenheiro de software full stack (fonte 2).",
  "- **Contato:** e-mail e LinkedIn (fonte 2)",
  "- Competências: Grafana, LLM e Generative AI (fonte 2)",
  "  - Certificações em Python e MySQL",
  ":::",
  "",
  "Posso detalhar qualquer um deles.",
].join("\n");

test("file directive becomes a card with its summary and indented details, not sibling bullets", () => {
  const blocks = parseAnswerBlocks(SCREENSHOT);
  assert.deepEqual(blocks.map((block) => block.kind), ["paragraph", "heading", "file", "file", "paragraph"]);
  const [gravidade, profile] = [blocks[2], blocks[3]];
  assert.equal(gravidade.name, "A Gravidade do pecado de impuresa");
  assert.equal(gravidade.marker, "(fonte 1)");
  assert.deepEqual(gravidade.children.map((block) => block.kind), ["paragraph"]);
  assert.equal(profile.children[0].text, "Currículo de engenheiro de software full stack (fonte 2).");
  assert.deepEqual(profile.children[1], { kind: "fields", items: [{ label: "Contato", value: "e-mail e LinkedIn (fonte 2)" }] });
  assert.equal(profile.children[2].kind, "list");
  assert.deepEqual(profile.children[2].items[0].sub, ["Certificações em Python e MySQL"]);
});

test("highlight, steps and label/value blocks are recognized", () => {
  const blocks = parseAnswerBlocks([
    "::: highlight", "O prazo final é 30/10 (fonte 1).", ":::",
    "::: steps", "1. Abrir o contrato", "2. Assinar", ":::",
    "**Responsável:** Ana", "**Prazo:** 30/10",
  ].join("\n"));
  assert.deepEqual(blocks.map((block) => block.kind), ["highlight", "steps", "fields"]);
  assert.equal(blocks[1].items.length, 2);
  assert.equal(blocks[2].items[1].value, "30/10");
});

test("malformed output degrades to markdown and never loses text", () => {
  const unclosed = parseAnswerBlocks("::: file Profile.pdf\nResumo do currículo.\n\n## Depois\nTexto final.");
  assert.equal(unclosed[0].kind, "file");
  assert.ok(unclosed.some((block) => block.kind === "heading"));
  const unknown = parseAnswerBlocks("::: galeria\nConteúdo comum.\n:::\n:::");
  assert.deepEqual(unknown, [{ kind: "paragraph", text: "Conteúdo comum." }]);
  const noName = parseAnswerBlocks("::: file\nSem nome.\n:::");
  assert.deepEqual(noName, [{ kind: "paragraph", text: "Sem nome." }]);
  assert.deepEqual(parseAnswerBlocks(""), []);
});

test("un-directed file listings are presented as cards for the answer's own documents", () => {
  const fileNames = ["A Gravidade do pecado de impuresa", "Profile.pdf"];
  // Screenshot shape: a name-only bullet followed by its detail bullets.
  const mixed = parseAnswerBlocks([
    "- A Gravidade do pecado de impuresa",
    "- Documento identificado pelo título (fonte 1).",
    "- Profile.pdf",
    "- Currículo profissional (fonte 2).",
    "- Proficiência em inglês (fonte 2).",
  ].join("\n"), { fileNames });
  assert.deepEqual(mixed.map((block) => [block.kind, block.name]), [["file", fileNames[0]], ["file", fileNames[1]]]);
  assert.deepEqual(mixed[1].children[0], { kind: "paragraph", text: "Currículo profissional (fonte 2)." });
  assert.equal(mixed[1].children[1].items.length, 1);
  // Deterministic catalog fallback rows: "- Name: summary".
  const rows = parseAnswerBlocks("Conteúdo por arquivo:\n- Profile.pdf: Currículo.\n- A Gravidade do pecado de impuresa: não há conteúdo indexado suficiente para resumir este arquivo.", { fileNames });
  assert.deepEqual(rows.map((block) => block.kind), ["paragraph", "file", "file"]);
  assert.equal(rows[1].children[0].text, "Currículo.");
  // Lists that do not start with a known file stay lists.
  assert.equal(parseAnswerBlocks("- Prazo: 30/10\n- Profile.pdf: x", { fileNames })[0].kind, "list");
});

test("citation marker helper reads every number of a group", () => {
  assert.deepEqual(citationNumbers("(fontes 1, 2 e 3)"), [1, 2, 3]);
  assert.equal("Texto (fonte 2) e (fontes 1 e 3).".match(CITATION_MARKER).length, 2);
});

test("a label value of short '|' items becomes tags, a sentence stays text", () => {
  const blocks = parseAnswerBlocks("**Habilidades:** Grafana | LLM | Generative AI (fonte 2)\n**Resumo:** Engenheiro com 5 anos | especialista em Python e IA aplicada a produtos de documentos e busca (fonte 2)");
  const [fields] = blocks;
  assert.equal(fields.kind, "fields");
  assert.deepEqual(fields.items[0].tags, ["Grafana", "LLM", "Generative AI"]);
  assert.equal(fields.items[0].marker, "(fonte 2)");
  assert.equal(fields.items[1].tags, undefined);
});
