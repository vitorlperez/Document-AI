import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  CHAT_MIN_WIDTH, DOCX_MIME, PDF_MIME, VIEWER_MIN_WIDTH, VIEWER_WIDTH_KEY, citationTarget, clampViewerWidth, defaultViewerWidth, fallsBackToText, fileErrorMessage,
  groupByPage, highlightAnnouncement, httpFileErrorCode, renderFailureCode, isHighlighted, locateInSpans, nextHighlight, parseRowTable, parseStoredWidth, readStoredWidth, splitHighlight, storeWidth, viewerFor, widthAfterDrag,
} from "../app/file-viewer-logic.ts";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");
const SHEET = "application/vnd.google-apps.spreadsheet";
const SLIDES = "application/vnd.google-apps.presentation";

test("viewerFor maps file type to the renderer", () => {
  assert.equal(viewerFor({ mime_type: PDF_MIME, file_available: true, file_content_type: PDF_MIME }), "pdf");
  assert.equal(viewerFor({ mime_type: "application/vnd.google-apps.document", file_available: true, file_content_type: PDF_MIME }), "pdf");
  assert.equal(viewerFor({ mime_type: DOCX_MIME, file_available: true, file_content_type: DOCX_MIME }), "docx");
  // spreadsheets, slides, csv and Notion/ClickUp use the extracted text; the backend may still offer a PDF export for Google natives
  assert.equal(viewerFor({ mime_type: SHEET, file_available: true, file_content_type: PDF_MIME }), "text");
  assert.equal(viewerFor({ mime_type: SLIDES, file_available: true, file_content_type: PDF_MIME }), "text");
  assert.equal(viewerFor({ mime_type: "text/csv", file_available: false, file_content_type: null }), "text");
  assert.equal(viewerFor({ mime_type: PDF_MIME, file_available: false, file_content_type: null }), "text"); // e.g. a Notion export
});

test("file errors map to friendly copy and know when text is a good fallback", () => {
  assert.match(fileErrorMessage("source_access_denied"), /Reconecte/);
  assert.match(fileErrorMessage("source_file_missing"), /não foi encontrado/);
  assert.match(fileErrorMessage("whatever"), /Não foi possível carregar/);
  assert.match(fileErrorMessage(null), /Não foi possível carregar/);
  assert.equal(fallsBackToText("file_too_large"), true);
  assert.equal(fallsBackToText("viewer_not_supported"), true);
  assert.equal(fallsBackToText("source_access_denied"), false);
});

test("the viewer width keeps both the viewer readable and the chat usable", () => {
  assert.equal(clampViewerWidth(100, 1200), VIEWER_MIN_WIDTH);
  assert.equal(clampViewerWidth(5000, 1200), 1200 - CHAT_MIN_WIDTH);
  assert.equal(clampViewerWidth(600, 1200), 600);
  assert.equal(clampViewerWidth(Number.NaN, 1200), VIEWER_MIN_WIDTH);
  assert.equal(clampViewerWidth(500, 400), VIEWER_MIN_WIDTH); // tiny window: never below the minimum
  assert.equal(defaultViewerWidth(1200), 552);
  assert.equal(widthAfterDrag(500, 800, 700, 1200), 600); // dragging the handle left widens the viewer
  assert.equal(widthAfterDrag(500, 800, 900, 1200), 400);
});

test("the remembered width tolerates garbage and blocked storage", () => {
  assert.equal(parseStoredWidth("520"), 520);
  assert.equal(parseStoredWidth("abc"), null);
  assert.equal(parseStoredWidth("20"), null);
  assert.equal(parseStoredWidth(null), null);
  assert.equal(readStoredWidth({ getItem: (key) => (key === VIEWER_WIDTH_KEY ? "480" : null) }), 480);
  assert.equal(readStoredWidth({ getItem: () => { throw new Error("blocked"); } }), null);
  const saved = [];
  storeWidth(480.4, { setItem: (key, value) => saved.push([key, value]) });
  assert.deepEqual(saved, [[VIEWER_WIDTH_KEY, "480"]]);
  assert.doesNotThrow(() => storeWidth(480, { setItem: () => { throw new Error("quota"); } }));
});

test("a [N] click highlights the matching source and a new click replaces it", () => {
  assert.equal(citationTarget(2, 3), 2);
  assert.equal(citationTarget(0, 3), null);
  assert.equal(citationTarget(4, 3), null);
  assert.equal(citationTarget(1.5, 3), null);
  const first = nextHighlight(null, 2);
  assert.deepEqual(first, { number: 2, nonce: 1 });
  assert.equal(isHighlighted(first, 2), true);
  assert.equal(isHighlighted(first, 1), false);
  assert.equal(isHighlighted(null, 1), false);
  const again = nextHighlight(first, 2); // same number clicked again must still re-announce
  assert.equal(again.nonce, 2);
  assert.match(highlightAnnouncement(2, "Plano.pdf"), /Fonte 2 destacada.*Plano\.pdf/);
});

test("the cited passage is located in the pdf text layer across span and line breaks", () => {
  const spans = ["Cláusula 4 — O prazo de entrega é de ", "30 dias corridos", " após a assinatura do contrato.", "Rodapé"];
  assert.deepEqual(locateInSpans(spans, "O prazo de entrega é de 30 dias corridos após a assinatura"), { from: 0, to: 2 });
  assert.deepEqual(locateInSpans(spans, "prazo de entrega é de 30 dias…"), { from: 0, to: 1 });
  assert.equal(locateInSpans(spans, "texto que não existe nesta página"), null);
  assert.equal(locateInSpans(spans, "curto"), null);
  assert.deepEqual(locateInSpans(["a  b\n c", "quarta   parcela vence em março"], "quarta parcela vence em março de 2026 conforme anexo"), { from: 1, to: 1 }); // opening-only fallback
});

test("splitHighlight ignores a trailing ellipsis and short needles", () => {
  assert.deepEqual(splitHighlight("O prazo é de 30 dias.", "prazo é de 30…"), ["O ", "prazo é de 30", " dias."]);
  assert.equal(splitHighlight("abc", "ab"), null);
});

test("spreadsheet-like chunks become tables, prose does not", () => {
  const table = parseRowTable("Nome: Ana | Valor: 10\nNome: Bia | Valor: 20");
  assert.deepEqual(table, { headers: ["Nome", "Valor"], rows: [["Ana", "10"], ["Bia", "20"]] });
  assert.equal(parseRowTable("Um parágrafo qualquer: com dois pontos e texto.\nOutra linha sem formato"), null);
  assert.equal(parseRowTable(""), null);
});

test("chunks are grouped by consecutive page/slide", () => {
  const chunk = (id, page) => ({ id, position: 0, page_number: page, text: id });
  const groups = groupByPage([chunk("a", 1), chunk("b", 1), chunk("c", 2), chunk("d", null), chunk("e", null)]);
  assert.deepEqual(groups.map((group) => [group.page, group.chunks.map((item) => item.id)]), [[1, ["a", "b"]], [2, ["c"]], [null, ["d", "e"]]]);
});

test("wiring: [N] only highlights; the source row opens the viewer; the old panel is gone", () => {
  const chat = read("product/chat-workspace.tsx");
  assert.doesNotMatch(chat, /SourceEvidencePanel/);
  assert.match(chat, /onCite=\{answer\.citations\.length > 0 \? pointToSource : undefined\}/);
  assert.match(chat, /const pointToSource = [\s\S]*setHighlight\(\(current\) => nextHighlight\(current, number\)\)/);
  assert.doesNotMatch(chat.slice(chat.indexOf("const pointToSource"), chat.indexOf("const settle")), /onOpenFile|setViewerTarget/);
  assert.match(chat, /onClick=\{\(\) => onOpen\(number\)\} aria-label=\{`Visualizar arquivo/);
  assert.match(chat, /<FileViewerHost organizationId=\{company\.id\} target=\{viewerTarget\} panelsRef=\{panelsRef\}/);
  // the external-tool link stays a sibling of the row button, never nested in it
  assert.match(chat, /<\/button>\s*\{item\.source_url && <a href=\{item\.source_url\} target="_blank"/);
});

test("wiring: viewer closes on Esc, restores focus, loads renderers lazily", () => {
  const viewer = read("file-viewer.tsx");
  assert.match(viewer, /event\.key !== "Escape"/);
  assert.match(viewer, /lazy\(\(\) => import\("\.\/pdf-viewer"\)/);
  assert.match(viewer, /lazy\(\(\) => import\("\.\/docx-viewer"\)/);
  assert.match(viewer, /role=\{narrow \? "dialog" : "complementary"\}/);
  assert.match(viewer, /role="separator"/);
  assert.match(read("pdf-viewer.tsx"), /await import\("pdfjs-dist"\)/);
  assert.doesNotMatch(read("product/chat-workspace.tsx"), /from "pdfjs-dist"|from "docx-preview"/);
});

test("pdf.js worker is resolved through the bundler's ?url import, never new URL(..., import.meta.url)", () => {
  // Regression: the production build rewrote `new URL("pdfjs-dist/...", import.meta.url)` to `file:///ROOT/...`, so the worker
  // never loaded and every PDF fell back to extracted text ("Não foi possível exibir o arquivo original aqui").
  const source = read("pdf-viewer.tsx");
  assert.match(source, /import pdfWorkerUrl from "pdfjs-dist\/build\/pdf\.worker\.min\.mjs\?url"/);
  assert.match(source, /workerSrc = pdfWorkerUrl/);
  assert.doesNotMatch(source, /import\.meta\.url/);
});

test("a production build, when present, never points assets at a file:// URL", async () => {
  const { existsSync, readdirSync } = await import("node:fs");
  const dir = new URL("../dist/client/_next/static/chunks/", import.meta.url);
  if (!existsSync(dir)) return;
  for (const name of readdirSync(dir).filter((file) => file.startsWith("pdf-viewer"))) {
    assert.doesNotMatch(readFileSync(new URL(name, dir), "utf8"), /file:\/\/\//, `${name} references a file:/// URL`);
  }
});

test("renderFailureCode and httpFileErrorCode explain why a file could not be shown", () => {
  assert.equal(renderFailureCode({ name: "PasswordException" }), "render_password");
  assert.equal(renderFailureCode({ name: "InvalidPDFException", message: "Invalid PDF structure." }), "render_invalid");
  assert.equal(renderFailureCode(new Error("Setting up fake worker failed: \"Failed to fetch dynamically imported module\".")), "render_viewer_unavailable");
  assert.equal(renderFailureCode(new Error("Not allowed to load local resource: file:///x.mjs")), "render_viewer_unavailable");
  assert.equal(renderFailureCode(new Error("boom")), "render_failed");
  assert.equal(httpFileErrorCode(401), "session_expired");
  assert.equal(httpFileErrorCode(403), "forbidden");
  assert.equal(httpFileErrorCode(404), "source_file_missing");
  assert.equal(httpFileErrorCode(502), "http_502");
  for (const code of ["render_password", "render_invalid", "render_viewer_unavailable", "render_failed", "session_expired", "forbidden", "network_error"]) {
    assert.notEqual(fileErrorMessage(code), fileErrorMessage("unknown_code"), code);
  }
  assert.match(fileErrorMessage("source_access_denied"), /Reconecte/);
});
