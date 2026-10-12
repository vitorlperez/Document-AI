import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { LibraryIndexingBadge } from "../app/product/library-indexing-badge.tsx";

test("badge exposes file, state and action to assistive technology", () => {
  const html = renderToStaticMarkup(createElement(LibraryIndexingBadge, {
    item: { name: "contrato.pdf", indexing: { state: "failed", error_code: "file_encrypted" } },
  }));
  assert.match(html, /type="button"/);
  assert.match(html, /aria-label="contrato.pdf: PDF protegido por senha/);
  assert.match(html, /aria-haspopup="dialog"/);
  const descriptionId = html.match(/aria-describedby="([^"]+)"/)[1];
  assert.ok(html.includes(`id="${descriptionId}"`));
  assert.match(html, /Disponibilize uma cópia sem senha/);
  assert.match(html, /data-tone="warning"/);
  assert.match(html, /aria-hidden="true"/);
});

test("two badges have independent descriptions and preserve supported format statuses", () => {
  const html = renderToStaticMarkup(createElement("div", {},
    createElement(LibraryIndexingBadge, { item: { name: "dados.xlsx", indexing: { state: "indexed", error_code: null } } }),
    createElement(LibraryIndexingBadge, { item: { name: "slides.pptx", indexing: { state: "pending", error_code: null } } }),
  ));
  const ids = [...html.matchAll(/aria-describedby="([^"]+)"/g)].map(match => match[1]);
  assert.equal(new Set(ids).size, 2);
  assert.match(html, /dados.xlsx: Indexado/);
  assert.match(html, /slides.pptx: Aguardando indexação/);
});
