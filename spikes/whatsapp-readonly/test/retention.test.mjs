import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createContext, runInContext } from 'node:vm';
import { EventEmitter } from 'node:events';
import { Engine, normalize, inspect, emptyCounters } from '../src/core.mjs';
import { ReadOnlyConnector } from '../src/connector.mjs';
import { createWebReader } from '../src/web-reader.mjs';

const require = createRequire(import.meta.url);
const { Chat, Message } = require('whatsapp-web.js');
const { LoadUtils } = require('whatsapp-web.js/src/util/Injected/Utils.js');
const chat = 'synthetic@g.us';
const wire = (n, overrides = {}) => ({ id: { $1: `synthetic-${n}`, id: `synthetic-${n}`,
  remote: chat, fromMe: false }, from: chat, to: 'synthetic-self@c.us',
  t: 1_760_000_000, type: 'chat', body: 'SYNTHETIC_TEXT', ...overrides });

// The installed getMessageModel -> CDP JSON -> Chat.fetchMessages -> Message
// path, with invented models. No browser/account/profile or copied serializers.
function upstream(rows) {
  const context = createContext({ window: { require(name) {
    if (name === 'WALinkify') return { findLinks: () => [] };
    if (name === 'WAWebChatLoadMessages') return { loadEarlierMsgs: async () => [] };
    throw Error('UNEXPECTED_MODULE');
  } } });
  runInContext(`(${LoadUtils.toString()})()`, context);
  context.rows = rows.map(row => ({ ...row, serialize: () => structuredClone(row) }));
  runInContext('window.WWebJS.getChat = async () => ({msgs: {getModelsArray: () => rows}})', context);
  const client = new EventEmitter();
  client.pupPage = { async evaluate(fn, ...args) {
    context.args = args;
    return JSON.parse(JSON.stringify(await runInContext(`(${fn.toString()})(...args)`, context)));
  } };
  client.readOnly = createWebReader(client, Chat);
  return client;
}
const sum = obj => Object.values(obj).reduce((a, b) => a + b, 0);
function balanced(c) {
  assert.equal(c.received, c.processed + c.unprocessed);
  assert.equal(c.processed, c.normalized + c.normalizationRejected);
  assert.equal(c.normalized, c.eligible + c.selectionRejected);
  assert.equal(c.eligible, c.applied + c.applicationRejected);
  assert.equal(c.applied, c.retained + c.tombstoned);
  assert.equal(c.processed, c.applied + sum(c.rejections));
  assert.equal(sum({ text: c.observed.text, media: c.observed.media,
    revoked: c.observed.revoked, other: c.observed.other }), c.processed);
}

test('installed upstream returns 38 $1-keyed text messages; POC retains all without widening selection', async () => {
  const client = upstream(Array.from({ length: 38 }, (_, i) => wire(i)));
  const raw = await client.readOnly.history(chat, 200);
  assert.equal(raw.length, 38); assert.ok(raw[0] instanceof Message);
  assert.equal(raw[0].id._serialized, undefined); // Pinned upstream leaves $1 as-is.
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  await new ReadOnlyConnector(client, e).history(chat, 200);
  assert.equal(e.report().retainedMessages, 38);
  assert.equal(e.report().documents, 1);
  assert.equal(e.report().history[0].newlyRetained, 38);
  assert.equal(e.report().realIntegrationValidated, false);
});

test('installed Message endpoint $1 is recovered only from the directed endpoint, never author/remote', async () => {
  for (const fromMe of [false, true]) {
    const row = wire(1, { id: { $1: 'synthetic-1', id: 'synthetic-1', remote: { $1: chat }, fromMe },
      from: { $1: fromMe ? 'synthetic-self@c.us' : chat },
      to: { $1: fromMe ? chat : 'synthetic-self@c.us' } });
    const client = upstream([row]);
    const [raw] = await client.readOnly.history(chat, 200);
    assert.equal(fromMe ? raw.to : raw.from, undefined);
    assert.equal(raw.id.remote, undefined); // 1.34.7 loses this field.
    assert.equal(normalize(raw)?.chatId, chat);
    const e = new Engine({ mode: 'simulated', selected: [chat] });
    await new ReadOnlyConnector(client, e).history(chat, 200);
    assert.equal(e.report().retainedMessages, 1);
  }
  const row = new Message({}, wire(2, { from: undefined, author: chat }));
  assert.equal(normalize(row), null);
});

test('history stages distinguish media, ephemeral, view-once, empty and PN/LID mismatch with balanced counts', async () => {
  const rows = [wire(1), wire(1), wire(2, { type: 'image', directPath: '/synthetic', caption: 'synthetic caption' }),
    wire(3, { isEphemeral: true }), wire(4, { isViewOnce: true }), wire(5, { body: '' }),
    wire(6, { type: 'notification_template' }), wire(7, { t: 0 }), wire(8, { body: 'x'.repeat(64_001) }),
    wire(9, { id: { id: 'missing' } }),
    wire(10, { from: 'synthetic-pn@c.us', id: { $1: 'mismatch', remote: 'synthetic-pn@c.us', fromMe: false } })];
  const client = upstream(rows), e = new Engine({ mode: 'simulated', selected: [chat] });
  const adapter = new ReadOnlyConnector(client, e);
  await adapter.history(chat, 200);
  const report = e.report(), c = report.history[0].ingestion;
  balanced(c); assert.deepEqual(c, report.ingestion.history);
  assert.equal(c.received, 11); assert.equal(c.retained, 1);
  for (const reason of ['unsupported_media', 'unsupported_type', 'ephemeral', 'view_once', 'empty_body',
    'invalid_timestamp', 'body_too_large', 'invalid_message_id', 'unselected_chat', 'duplicate']) {
    assert.equal(c.rejections[reason], 1, reason);
  }
  assert.equal(report.history[0].newlyRetained, c.retained);
  assert.equal(report.events.history, c.retained);
  assert.ok(!JSON.stringify(report).includes('SYNTHETIC_TEXT'));
  assert.ok(!JSON.stringify(report).includes('synthetic-'));
  assert.ok(!JSON.stringify(report).includes('@'));
  // Exact namespace mismatch is observed without inferring equivalence.
  const pn = 'synthetic-pn@c.us', lid = 'synthetic-lid@lid';
  const individual = new Engine({ mode: 'simulated', selected: [lid] });
  const c2 = upstream([wire(11, { from: pn, id: { $1: 'pn', id: 'pn', remote: pn, fromMe: false } })]);
  await new ReadOnlyConnector(c2, individual).history(lid, 200);
  assert.equal(individual.report().retainedMessages, 0);
  assert.equal(individual.report().ingestion.history.rejections.unselected_chat, 1);
  assert.equal(individual.report().ingestion.history.observed.pnLidSelectionMismatch, 1);
});

test('identity conflicts and unselected sender/author never authorize a chat', async () => {
  const rows = [wire(1, { from: 'other@g.us', author: chat }),
    wire(2, { id: { _serialized: 'one', $1: 'two', id: 'two', remote: chat } }),
    wire(3, { id: { $1: 'three', id: 'three', remote: 'other@g.us' } }),
    wire(4, { from: { _serialized: 'other@g.us', $1: chat } })];
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  await new ReadOnlyConnector(upstream(rows), e).history(chat, 200);
  assert.equal(e.report().retainedMessages, 0);
  const c = e.report().ingestion.history;
  balanced(c); assert.equal(c.rejections.identity_conflict, 4);
});

test('live event diagnostics survive replay, edits, deletes, restart and gates without private fields', () => {
  const client = upstream([]), e = new Engine({ mode: 'simulated', selected: [chat] });
  const adapter = new ReadOnlyConnector(client, e);
  const m = new Message({}, wire(1));
  client.emit('message_create', m); client.emit('message_create', m);
  client.emit('message_edit', m, 'edited'); client.emit('message_edit', m, 'edited');
  client.emit('message_revoke_everyone', new Message({}, wire(2, {
    protocolMessageKey: { $1: 'synthetic-1', remote: { $1: chat } } })));
  client.emit('message_create', m);
  assert.equal(e.report().retainedMessages, 0); assert.equal(e.report().tombstones, 1);
  for (const c of Object.values(e.report().ingestion)) balanced(c);
  assert.equal(e.report().ingestion.new.rejections.duplicate, 1);
  assert.equal(e.report().ingestion.new.rejections.already_deleted, 1);
  assert.equal(e.report().ingestion.edit.rejections.unchanged_edit, 1);
  const resumed = new Engine({ mode: 'simulated', snapshot: structuredClone(e.state) });
  assert.deepEqual(resumed.report().ingestion, e.report().ingestion);
  e.beginRun({ durationMinutes: 90 });
  const counts = structuredClone(e.report().ingestion);
  client.emit('message_create', { get id() { assert.fail('no inspection before gate'); } });
  assert.deepEqual(e.report().ingestion, counts); adapter.dispose();
});

test('legacy history remains explicitly unmeasured instead of receiving invented reasons', () => {
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  e.historyResult(chat, { returned: 38, newlyRetained: 0, ok: true });
  const snapshot = structuredClone(e.state); delete snapshot.ingestion;
  const resumed = new Engine({ mode: 'simulated', snapshot });
  assert.equal(resumed.report().history[0].ingestion, undefined);
  assert.deepEqual(resumed.report().ingestionCoverage, { historyMeasured: 0, historyUnmeasured: 1 });
  balanced(resumed.report().ingestion.history);
});

test('active run states zero documents with numeric reasons only', async () => {
  const { retentionSummary } = await import('../src/live.mjs');
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  await new ReadOnlyConnector(upstream([wire(1, { type: 'image', directPath: '/synthetic' }), wire(2, { body: '' })]), e)
    .history(chat, 200);
  const line = retentionSummary(e);
  assert.match(line, /^ZERO_DOCUMENTS/); assert.match(line, /unsupported_media=1, empty_body=1/);
  assert.ok(!line.includes('synthetic') && !line.includes('@'));
  await new ReadOnlyConnector(upstream([wire(3)]), e).history(chat, 200);
  assert.doesNotMatch(retentionSummary(e), /ZERO_DOCUMENTS/);
});

test('capacity failure stays balanced and counts fetched-but-unprocessed messages', async () => {
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  e.state.messages = Object.fromEntries(Array.from({ length: 50_000 }, (_, i) => [`k${i}`, { chatId: chat, deleted: true }]));
  await assert.rejects(new ReadOnlyConnector(upstream([wire(1), wire(2), wire(3)]), e).history(chat, 200));
  const c = e.report().history[0].ingestion;
  balanced(c); assert.equal(c.rejections.capacity_reached, 1); assert.equal(c.unprocessed, 2);
  assert.equal(e.report().history[0].ok, false);
});

test('review h-st: revoke target wins over a mismatched notice envelope; repeat revoke is already_deleted', () => {
  const pn = 'synthetic-pn@c.us', e = new Engine({ mode: 'simulated', selected: [pn] });
  const client = upstream([]); new ReadOnlyConnector(client, e);
  client.emit('message_create', new Message({}, wire(1, { from: pn, id: { $1: 'synthetic-1', remote: pn, fromMe: false } })));
  const revoke = new Message({}, wire(2, { from: 'synthetic-l@lid', id: { $1: 'synthetic-2', remote: pn },
    protocolMessageKey: { $1: 'synthetic-1', remote: pn } }));
  client.emit('message_revoke_everyone', revoke); client.emit('message_revoke_everyone', revoke);
  assert.equal(e.report().retainedMessages, 0); assert.equal(e.report().tombstones, 1);
  const c = e.report().ingestion.delete_everyone;
  balanced(c); assert.equal(c.tombstoned, 1); assert.equal(c.rejections.already_deleted, 1);
});

test('review h-st: closed gate is never counted and never yields NaN', () => {
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  e.ingestionEnabled = false;
  assert.equal(e.ingest('history', new Message({}, wire(1))).reason, 'ingestion_disabled');
  for (const c of Object.values(e.report().ingestion)) { balanced(c); assert.equal(c.received, 0); }
});

test('review h-st: live activity of unselected chats leaves no counters', () => {
  const e = new Engine({ mode: 'simulated', selected: [chat] }), client = upstream([]);
  new ReadOnlyConnector(client, e);
  client.emit('message_create', new Message({}, wire(1, { type: 'image', from: 'other@g.us',
    id: { $1: 'x', remote: 'other@g.us' } })));
  client.emit('message_create', new Message({}, wire(2, { from: 'status@broadcast', id: { $1: 'y', remote: 'status@broadcast' } })));
  assert.deepEqual(e.report().ingestion.new, emptyCounters());
});

test('review h-st: remote embedded in the serialized id vetoes a different endpoint', () => {
  assert.equal(inspect({ id: { _serialized: 'false_other@g.us_ID' }, from: chat, type: 'chat', body: 'x',
    timestamp: 1 }).reason, 'identity_conflict');
  assert.equal(normalize({ id: { $1: `true_${chat}_ID` }, fromMe: true, to: chat, type: 'chat', body: 'x',
    timestamp: 1 })?.chatId, chat);
});

test('review h-st: summary reflects only the current run', async () => {
  const { retentionSummary } = await import('../src/live.mjs');
  const e = new Engine({ mode: 'simulated', selected: [chat] });
  e.beginRun({ durationMinutes: 1 }); e.select([chat]);
  await new ReadOnlyConnector(upstream([wire(1, { type: 'image' })]), e).history(chat, 200);
  const resumed = new Engine({ mode: 'simulated', snapshot: structuredClone(e.state) });
  resumed.beginRun({ durationMinutes: 1 }); resumed.select([chat]);
  await new ReadOnlyConnector(upstream([wire(2, { body: '' })]), resumed).history(chat, 200);
  const line = retentionSummary(resumed);
  assert.match(line, /recebidas 1,/); assert.match(line, /empty_body=1/); assert.doesNotMatch(line, /unsupported_media/);
});
