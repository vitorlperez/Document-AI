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

async function pagerHarness() {
  const { LibraryPager } = await import('../app/library-view-logic.ts');
  const calls = [];
  const pager = new LibraryPager((page, signal) => new Promise((resolve, reject) => calls.push({ page, signal, resolve, reject })), () => {});
  return { pager, calls };
}

test('progressive library accumulates unique items and stops at the last page', async () => {
  const { pager, calls } = await pagerHarness();
  const first = pager.load();
  assert.equal(pager.state.loading, true);
  assert.equal(await pager.load(), undefined);
  assert.equal(calls.length, 1);
  calls[0].resolve({ items: [{ id: 'folder' }, { id: 'file' }], page: 1, pages: 2 });
  await first;
  const next = pager.load();
  assert.equal(calls[1].page, 2);
  calls[1].resolve({ items: [{ id: 'file' }, { id: 'new' }, { id: 'new' }], page: 2, pages: 2 });
  await next;
  assert.deepEqual(pager.state.items.map(item => item.id), ['folder', 'file', 'new']);
  assert.equal(pager.state.hasMore, false);
  await pager.load();
  assert.equal(calls.length, 2);
});

test('next-page error preserves items and retries the same page', async () => {
  const { pager, calls } = await pagerHarness();
  const first = pager.load();
  calls[0].resolve({ items: [{ id: 'one' }], page: 1, pages: 2 });
  await first;
  const next = pager.load();
  calls[1].reject(new Error('offline'));
  await next;
  assert.equal(pager.state.error.message, 'offline');
  assert.equal(pager.state.items.length, 1);
  const retry = pager.load();
  assert.equal(calls[2].page, 2);
  calls[2].resolve({ items: [], page: 2, pages: 2 });
  await retry;
  assert.equal(pager.state.error, null);
  assert.equal(pager.state.hasMore, false);
});

test('reset cancels pending requests and discards stale success and failure', async () => {
  const { pager, calls } = await pagerHarness();
  const old = pager.load();
  pager.reset();
  assert.equal(calls[0].signal.aborted, true);
  const fresh = pager.load();
  calls[0].resolve({ items: [{ id: 'stale' }], page: 1, pages: 9 });
  await old;
  assert.equal(pager.state.loading, true);
  assert.deepEqual(pager.state.items, []);
  calls[1].resolve({ items: [{ id: 'fresh' }], page: 1, pages: 1 });
  await fresh;
  pager.reset();
  const failure = pager.load();
  pager.reset();
  calls[2].reject(new Error('stale failure'));
  await failure;
  assert.equal(pager.state.error, null);
  assert.deepEqual(pager.state.items, []);
});

test('sync refresh preserves the expanded range and updates it atomically', async () => {
  const { pager, calls } = await pagerHarness();
  const first = pager.load();
  calls[0].resolve({ items: [{ id: 'old' }], pages: 3 });
  await first;
  const next = pager.load();
  calls[1].resolve({ items: [{ id: 'two' }], pages: 3 });
  await next;
  const refresh = pager.refresh();
  assert.equal(pager.state.items.length, 2);
  calls[2].resolve({ items: [{ id: 'new' }], pages: 3 });
  await Promise.resolve();
  assert.deepEqual(pager.state.items.map(item => item.id), ['old', 'two']);
  assert.equal(calls[3].page, 2);
  calls[3].resolve({ items: [{ id: 'two' }], pages: 3 });
  await refresh;
  assert.deepEqual(pager.state.items.map(item => item.id), ['new', 'two']);
  assert.equal(pager.state.nextPage, 3);
  assert.equal(pager.state.hasMore, true);
});

test('empty first batch stops and first-load failure can be retried', async () => {
  const { pager, calls } = await pagerHarness();
  const first = pager.load();
  calls[0].reject(new Error('offline'));
  await first;
  assert.equal(pager.state.loading, false);
  assert.equal(pager.state.nextPage, 1);
  const retry = pager.load();
  calls[1].resolve({ items: [], page: 1, pages: 1 });
  await retry;
  assert.equal(pager.state.hasMore, false);
  assert.equal(pager.state.error, null);
});

test('refresh failure at the end of a list preserves items and can be retried', async () => {
  const { pager, calls } = await pagerHarness();
  const first = pager.load();
  calls[0].resolve({ items: [{ id: 'one' }], pages: 1 });
  await first;
  const refresh = pager.refresh();
  calls[1].reject(new Error('offline'));
  await refresh;
  assert.equal(pager.state.hasMore, false);
  assert.equal(pager.state.items.length, 1);
  const retry = pager.load();
  assert.equal(calls[2].page, 1);
  calls[2].resolve({ items: [{ id: 'fresh' }], pages: 1 });
  await retry;
  assert.equal(pager.state.error, null);
  assert.deepEqual(pager.state.items.map(item => item.id), ['fresh']);
});
