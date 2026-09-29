import assert from "node:assert/strict";
import test from "node:test";

import { mentionSummary } from "../app/mention-label.ts";

test("named mentions read as kind: name", () => {
  assert.equal(mentionSummary([{ kind: "folder", name: "Contratos" }, { kind: "file", name: "a.pdf" }]), "Pasta: Contratos · Arquivo: a.pdf");
});

test("restored mentions without a name never print 'undefined'", () => {
  const text = mentionSummary([{ kind: "folder" }, { kind: "folder", name: " " }, { kind: "file", name: undefined }]);
  assert.doesNotMatch(text, /undefined/);
  assert.equal(text, "1 arquivo mencionado · 2 pastas mencionadas");
});
