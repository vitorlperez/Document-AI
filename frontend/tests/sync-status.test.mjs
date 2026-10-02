import assert from "node:assert/strict";
import test from "node:test";

import { anyQueryable, anySyncing, bannerCopy, countLabel, errorMessage, normalizeSyncItems, onboardingSyncPresentation, errorReason, percent, pollInterval, progressView, shortLabel, stageLabel, summarize, summaryProgress, stepOf } from "../app/sync-status-logic.ts";

const item = (over = {}) => normalizeSyncItems([{ source_id: "s", provider: "notion", state: "syncing", stage: "indexing", processed: 3, total: 10, failed: 0, queryable: false, ...over }])[0];

test("normalize maps snake_case and tolerates junk", () => {
  const t = normalizeSyncItems([{ source_id: "a", provider: "x", state: "weird", stage: "nope", processed: -2, total: null }])[0];
  assert.deepEqual([t.state, t.stage, t.processed, t.total, t.libraryNodeId], ["idle", null, 0, 0, null]);
  assert.deepEqual(normalizeSyncItems(undefined), []);
});
test("percent, count and indeterminate", () => {
  assert.equal(percent(item()), 30);
  assert.equal(percent(item({ total: 0 })), null);
  assert.equal(percent(item({ state: "ready" })), 100);
  assert.equal(percent(item({ processed: 99 })), 100);
  assert.equal(countLabel(item()), "3 de 10 documentos");
  assert.equal(countLabel(item({ total: 0 })), null);
});
test("stage labels", () => {
  assert.equal(stageLabel(item({ stage: "discovering" })), "Lendo arquivos");
  assert.equal(stageLabel(item({ stage: null })), "Lendo arquivos");
  assert.equal(stageLabel(item({ stage: "indexing" })), "Preparando para o chat");
  assert.equal(stageLabel(item({ stage: "embedding" })), "Preparando para o chat");
  assert.equal(stageLabel(item({ state: "ready", queryable: true })), "Pronto para o chat");
});
test("aggregates", () => {
  const tools = [item({ queryable: true }), item({ source_id: "b", state: "ready", queryable: true })];
  assert.equal(anySyncing(tools), true);
  assert.equal(anyQueryable(tools), true);
  assert.equal(anySyncing([item({ state: "ready" })]), false);
  const s = summarize([item(), item({ processed: 5, total: 10 })]);
  assert.deepEqual([s.processed, s.total, s.percent, s.known], [8, 20, 40, true]);
  assert.equal(summarize([item(), item({ total: 0 })]).known, false);
  assert.equal(summarize([item({ state: "ready", queryable: true })]).allReady, true);
  assert.equal(summarize([item({ state: "ready", queryable: false })]).allReady, false);
});
test("banner copy", () => {
  assert.doesNotMatch(bannerCopy(summarize([item()])), /documentos/);
  assert.equal(bannerCopy(summarize([item({ state: "ready" })])), null);
});
test("errors and polling", () => {
  assert.match(errorMessage(item({ state: "failed" })), /falhou/);
  assert.match(errorMessage(item({ state: "partial_failure", failed: 2 })), /2 arquivos não puderam/);
  assert.match(errorMessage(item({ state: "ready", error_code: "usage_limit_exceeded" })), /limite de uso/);
  assert.equal(errorMessage(item({ state: "ready" })), null);
  assert.equal(pollInterval(true), 3000);
  assert.equal(pollInterval(false), 5000);
});

import { stageIndex } from "../app/sync-status-logic.ts";
test("stageIndex", () => {
  assert.deepEqual([item({ stage: null }), item({ stage: "indexing" }), item({ stage: "embedding" }), item({ state: "ready", stage: null })].map(stageIndex), [0, 1, 1, 2]);
});


const terminal = (over = {}) => item({ state: "ready", stage: "done", queryable: false, ...over });
for (const [state, tools, queryable, syncing] of [
  ["empty", [], false, false],
  ["idle", [item({ state: "idle" })], false, false],
  ["syncing-nothing-ready", [item({ state: "queued" })], false, true],
  ["syncing-partial-ready", [item(), terminal({ queryable: true })], true, true],
  ["done-ready", [terminal({ queryable: true })], true, false],
  ["done-empty", [terminal()], false, false],
  ["done-with-errors", [terminal({ queryable: true }), terminal({ state: "failed" })], true, false],
  ["done-with-errors", [terminal({ state: "partial_failure", failed: 2 })], false, false],
  ["all-failed", [terminal({ state: "failed" }), terminal({ state: "failed" })], false, false],
]) {
  test(`explicit onboarding state: ${state} (queryable=${queryable})`, () => {
    const summary = summarize(tools);
    assert.equal(summary.state, state);
    assert.equal(summary.queryable, queryable);
    assert.equal(summary.syncing, syncing);
  });
}
test("active work takes precedence over errors; old queryable content survives a failed resync", () => {
  assert.equal(summarize([item(), terminal({ state: "failed" })]).state, "syncing-nothing-ready");
  assert.equal(summarize([terminal({ state: "failed", queryable: true })]).state, "done-with-errors");
  assert.equal(summarize([terminal({ queryable: true, error_code: "usage_limit_exceeded" })]).allReady, false);
});
test("counts include units and clamp inconsistent counters", () => {
  assert.equal(countLabel(item({ processed: 80, total: 120 })), "80 de 120 documentos");
  assert.equal(countLabel(item({ processed: 20, total: 10 })), "10 de 10 documentos");
  assert.equal(countLabel(terminal({ total: 1 })), "1 de 1 documento");
});

test("onboarding presentation derives the next action from every explicit state", () => {
  for (const [tools, action, cta] of [
    [[], "connect", "Escolher conteúdo"],
    [[item({ state: "idle" })], "connect", "Escolher conteúdo"],
    [[item()], "background", "Continuar em segundo plano"],
    [[item({ queryable: true })], "chat", "Começar a conversar"],
    [[terminal({ queryable: true })], "chat", "Começar a conversar"],
    [[terminal()], "connect", "Escolher outra pasta"],
    [[terminal({ state: "partial_failure" })], "connect", "Voltar para conectar"],
    [[terminal({ queryable: true }), terminal({ state: "failed" })], "chat", "Começar a conversar"],
    [[terminal({ state: "failed" })], "connect", "Voltar para conectar"],
  ]) {
    const summary = summarize(tools);
    const view = onboardingSyncPresentation(summary);
    assert.equal(view.action, action);
    assert.equal(view.cta, cta);
    if (!summary.syncing) {
      assert.doesNotMatch(view.title + view.callout, /Estamos preparando|continua sendo preparado|segundo plano/);
    }
    if (action === "chat") assert.equal(summary.queryable, true);
  }
});
test("finished empty and partial states do not promise queryable content", () => {
  const empty = terminal();
  assert.match(stageLabel(empty), /sem conteúdo/);
  assert.match(onboardingSyncPresentation(summarize([empty])).title, /terminou sem conteúdo/);
  const partial = terminal({ state: "partial_failure", failed: 2 });
  assert.doesNotMatch(errorMessage(partial), /restante já está disponível/);
  assert.match(errorMessage(partial), /Ainda não há conteúdo/);
});

test("percent shown is exactly round(processed/total*100) of the current step, in text, short and bar", () => {
  for (const [stage, processed, total] of [["discovering", 79, 167], ["discovering", 0, 167], ["embedding", 40, 167], ["indexing", 166, 167], ["discovering", 167, 167], ["embedding", 1, 3]]) {
    const t = item({ stage, processed, total });
    const v = progressView(t);
    const expected = Math.round(processed / total * 100);
    assert.equal(v.percent, expected);
    assert.equal(percent(t), expected);
    assert.equal(v.short, `${expected}%`);
    assert.ok(v.text.endsWith(`(${expected}%)`), v.text);
    assert.ok(v.compact.includes(`${processed}/${total} · ${expected}%`), v.compact);
    assert.ok(v.speech.includes(`${expected}%`));
    assert.equal(summaryProgress([t]).percent, expected);
    assert.equal(summarize([t]).percent, expected);
  }
});
test("step labels and exact text format", () => {
  assert.equal(progressView(item({ stage: "discovering", processed: 79, total: 167 })).text, "Etapa 1 de 2 · Lendo arquivos — 79 de 167 (47%)");
  assert.equal(progressView(item({ stage: "discovering", processed: 79, total: 167 })).compact, "Etapa 1 de 2 · Lendo arquivos 79/167 · 47%");
  assert.equal(progressView(item({ stage: "embedding", processed: 40, total: 167 })).text, "Etapa 2 de 2 · Preparando para o chat — 40 de 167 (24%)");
  assert.equal(progressView(item({ stage: "indexing", processed: 40, total: 167 })).text, "Etapa 2 de 2 · Preparando para o chat — 40 de 167 (24%)");
  assert.deepEqual([stepOf(item({ stage: null })), stepOf(item({ stage: "indexing" })), stepOf(item({ state: "queued" })), stepOf(item({ state: "ready" }))], [1, 2, null, null]);
  assert.equal(progressView(item({ state: "queued", total: 0 })).text, "Na fila");
});
test("unknown total: indeterminate, no percent anywhere", () => {
  const v = progressView(item({ total: 0, stage: "discovering" }));
  assert.equal(v.percent, null); assert.equal(v.short, null);
  assert.equal(v.text, "Etapa 1 de 2 · Lendo arquivos…");
  assert.doesNotMatch(v.compact + v.speech, /%/);
  assert.equal(summaryProgress([item({ total: 0 })]).percent, null);
});
test("the bar restarts at a step change and the percent follows the new step's count (no floor, no weighting)", () => {
  const a = progressView(item({ stage: "discovering", processed: 167, total: 167 }));
  const b = progressView(item({ stage: "embedding", processed: 0, total: 167 }));
  assert.equal(a.percent, 100); assert.equal(b.percent, 0);
  assert.equal(b.step, 2);
});
test("aggregate: sums only the earliest running step; percent == sum/sum", () => {
  const same = summaryProgress([item({ processed: 10, total: 50 }), item({ source_id: "b", processed: 20, total: 50 })]);
  assert.equal(same.text, "Etapa 2 de 2 · Preparando para o chat — 30 de 100 (30%) · 2 ferramentas");
  const mixed = summaryProgress([item({ stage: "embedding", processed: 40, total: 100 }), item({ source_id: "b", stage: "discovering", processed: 10, total: 40 })]);
  assert.equal(mixed.step, 1); assert.equal(mixed.percent, 25);
  assert.match(mixed.text, /^Etapa 1 de 2 · Lendo arquivos — 10 de 40 \(25%\)/);
  assert.equal(summaryProgress([item({ state: "ready" })]), null);
  assert.equal(summaryProgress([item({ state: "queued", total: 0 })]).text, "Na fila");
});
test("friendly error reasons, never raw codes", () => {
  assert.match(errorMessage(item({ state: "partial_failure", error_code: "provider_error", failed: 2, queryable: true })), /ferramenta conectada/);
  assert.doesNotMatch(errorMessage(item({ state: "failed", error_code: "provider_error" })), /provider_error/);
  assert.match(errorMessage(item({ state: "failed", error_code: "weird_code" })), /erro inesperado/);
  assert.equal(errorReason(null), null);
});
test("skipped is optional (default 0) and never counts as a failure", () => {
  assert.equal(item().skipped, 0);
  const t = item({ state: "ready", queryable: true, skipped: 3 });
  assert.equal(t.skipped, 3);
  assert.equal(errorMessage(t), null);
  assert.equal(summarize([t]).errors.length, 0);
  assert.equal(summarize([t]).state, "done-ready");
});

test("shortLabel is the same short text everywhere (QF-06)", () => {
  assert.equal(shortLabel(item({ state: "queued", total: 0 })), "Fila");
  assert.equal(shortLabel(item({ state: "syncing", total: 0 })), "…");
  assert.equal(shortLabel(item()), "30%");
});
