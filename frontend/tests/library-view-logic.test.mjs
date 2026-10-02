import assert from "node:assert/strict";
import test from "node:test";

import { DEFAULT_LIBRARY_VIEW, fileKind, parseLibraryView, serializeLibraryView } from "../app/library-view-logic.ts";

test("fileKind maps extensions to icon families", () => {
  assert.equal(fileKind("Contrato.PDF", null), "pdf");
  assert.equal(fileKind("ata.docx", null), "doc");
  assert.equal(fileKind("orcamento.xlsx", null), "sheet");
  assert.equal(fileKind("dados.csv", "text/plain"), "sheet");
  assert.equal(fileKind("pitch.pptx", null), "slides");
  assert.equal(fileKind("foto.jpeg", null), "image");
  assert.equal(fileKind("sem-extensao", null), "generic");
});

test("fileKind falls back to the mime type", () => {
  assert.equal(fileKind("arquivo", "application/pdf"), "pdf");
  assert.equal(fileKind("arquivo", "image/png"), "image");
  assert.equal(fileKind("a", "application/vnd.google-apps.spreadsheet"), "sheet");
  assert.equal(fileKind("a", "application/vnd.openxmlformats-officedocument.presentationml.presentation"), "slides");
  assert.equal(fileKind("a", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"), "doc");
  assert.equal(fileKind("a", "application/octet-stream"), "generic");
  assert.equal(fileKind(null, undefined), "generic");
});

test("parseLibraryView validates the stored preference", () => {
  assert.deepEqual(parseLibraryView(null), DEFAULT_LIBRARY_VIEW);
  assert.deepEqual(parseLibraryView("not json"), DEFAULT_LIBRARY_VIEW);
  assert.deepEqual(parseLibraryView("42"), DEFAULT_LIBRARY_VIEW);
  assert.deepEqual(parseLibraryView('{"mode":"grid","size":"l"}'), { mode: "grid", size: "l" });
  assert.deepEqual(parseLibraryView('{"mode":"grid","size":"xl"}'), { mode: "grid", size: "m" });
  assert.deepEqual(parseLibraryView('{"mode":"cards","size":"s"}'), { mode: "list", size: "s" });
});

test("serializeLibraryView round-trips", () => {
  const view = { mode: "grid", size: "s" };
  assert.deepEqual(parseLibraryView(serializeLibraryView(view)), view);
});
