import assert from "node:assert/strict";
import test from "node:test";

import { cleanAnswerForDisplay } from "../app/answer-display.ts";

test("removes screenshot-shaped provider URLs and numeric citations from prose", () => {
  const answer = [
    "Resumo do projeto:",
    "- Nome: Projeto Atlas (google_drive: https://docs.google.com/document/d/abc/edit?usp=drivesdk) [1].",
    "- Prazo: setembro (google_drive: https://drive.google.com/file/d/xyz/view?usp=drivesdk) [2][3].",
    "[1].",
  ].join("\n");
  const displayed = cleanAnswerForDisplay(answer);
  assert.match(displayed, /Nome: Projeto Atlas/);
  assert.match(displayed, /Prazo: setembro/);
  assert.doesNotMatch(displayed, /https?:|google_drive|\[\d+\]|^\s*\.$/m);
});

test("retains facts and link labels while removing URLs and source-only lines", () => {
  const answer = [
    "Veja o [escopo](https://example.test/a_(b_(c))) para detalhes.",
    "Fonte: [Escopo](https://example.test/escopo)",
    "O prazo consta no documento (https://example.test/prazo).",
  ].join("\n");
  const displayed = cleanAnswerForDisplay(answer);
  assert.match(displayed, /Veja o escopo para detalhes\./);
  assert.match(displayed, /O prazo consta no documento\./);
  assert.doesNotMatch(displayed, /https?:|Fonte:|\(\)/);
  assert.equal(cleanAnswerForDisplay(null), null);
});

test("preserves numbered source prose from the current API", () => {
  const answer = "O prazo é setembro (fonte 2). As entregas constam em fontes 1 e 3.";
  assert.equal(cleanAnswerForDisplay(answer), answer);
});
