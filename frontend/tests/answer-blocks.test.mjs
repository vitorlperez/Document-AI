import assert from "node:assert/strict";
import test from "node:test";

import { parseAnswerBlocks } from "../app/answer-blocks.ts";

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
