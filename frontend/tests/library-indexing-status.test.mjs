import assert from "node:assert/strict";
import test from "node:test";
import { libraryIndexingPresentation } from "../app/library-indexing-status.ts";

const node = (state, error_code = null) => ({ indexing: { state, error_code, document_id: null, workspace_folder_id: null, indexed_at: null } });

test("explicit state takes precedence over legacy document references", () => {
  assert.equal(libraryIndexingPresentation({ ...node("failed", "file_encrypted"), workspace_documents: [{}] }).label, "PDF protegido por senha");
  assert.equal(libraryIndexingPresentation(node("indexed")).label, "Indexado");
  assert.equal(libraryIndexingPresentation(node("pending")).label, "Aguardando indexação");
});

test("failure reasons have actionable Portuguese descriptions for all terminal states", () => {
  const reasons = {
    unsupported_file_type: "Formato não suportado",
    empty_extracted_text: "PDF escaneado (sem texto)",
    file_too_large: "Arquivo grande demais",
    file_encrypted: "PDF protegido por senha",
    empty_content: "Arquivo vazio",
    source_file_unavailable: "Falha ao ler o arquivo",
    plan_limit_exceeded: "Limite do plano atingido",
  };
  for (const state of ["failed", "ignored", "skipped"]) {
    for (const [reason, label] of Object.entries(reasons)) {
      const result = libraryIndexingPresentation(node(state, reason));
      assert.equal(result.label, label);
      assert.ok(result.description.length > 30);
      assert.notEqual(result.tone, "success");
    }
  }
});

test("missing source and unknown errors never look pending or indexed", () => {
  assert.equal(libraryIndexingPresentation(node("not_found_in_source")).label, "Não encontrado na fonte");
  assert.equal(libraryIndexingPresentation(node("failed", "new_backend_error")).label, "Falha na indexação");
  for (const code of ["constructor", "__proto__", "toString"]) {
    assert.equal(libraryIndexingPresentation(node("failed", code)).label, "Falha na indexação");
  }
  assert.equal(libraryIndexingPresentation(node("ignored")).label, "Arquivo ignorado");
  assert.equal(libraryIndexingPresentation(node("skipped")).label, "Indexação não realizada");
});

test("older payloads distinguish indexed from unknown; formats do not invent failures", () => {
  assert.equal(libraryIndexingPresentation({ workspace_documents: [{}] }).label, "Indexado");
  assert.equal(libraryIndexingPresentation({}).label, "Ainda não processado");
  for (const name of ["dados.xlsx", "slides.pptx"]) {
    assert.equal(libraryIndexingPresentation({ ...node("pending"), name }).label, "Aguardando indexação");
    assert.equal(libraryIndexingPresentation({ ...node("indexed"), name }).label, "Indexado");
  }
});

test("v1 unknown states use pending even with legacy references", () => {
  assert.equal(libraryIndexingPresentation({ ...node("future_state"), workspace_documents: [{}] }).label, "Aguardando indexação");
});
