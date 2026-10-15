import test from 'node:test';
import assert from 'node:assert/strict';
import { Engine, normalize, chooseChats } from '../src/core.mjs';

const msg = (overrides = {}) => ({ id: { _serialized: 'false_group@g.us_A' }, from: 'group@g.us',
  to: 'me@c.us', fromMe: false, body: 'texto sintético', timestamp: 1_760_000_000,
  type: 'chat', ...overrides });
const engine = () => new Engine({ mode: 'simulated', selected: ['group@g.us'] });

test('selection is explicit, rejects empty/invalid and deduplicates', () => {
  const chats = [{ id: 'a' }, { id: 'b' }];
  assert.deepEqual(chooseChats('2, 2', chats), ['b']);
  for (const input of ['', '0', '3', '1x', 'all', '1,,2']) assert.throws(() => chooseChats(input, chats));
});
test('normalizes incoming/outgoing without relying on author for chat identity', () => {
  assert.equal(normalize(msg()).chatId, 'group@g.us');
  assert.equal(normalize(msg({ fromMe: true, from: 'me@c.us', to: 'group@g.us' })).chatId, 'group@g.us');
  assert.equal(normalize(msg({ author: 'participant@lid' })).chatId, 'group@g.us');
});
test('invalid payloads, status, broadcasts, media, ephemeral and view-once are omitted', () => {
  for (const raw of [null, {}, msg({ timestamp: NaN }), msg({ type: 'image' }),
    msg({ from: 'status@broadcast' }), msg({ isEphemeral: true }), msg({ isViewOnce: true })]) {
    assert.equal(normalize(raw), null);
  }
});
test('no ingestion before selection and no unselected content persists', () => {
  const e = new Engine({ mode: 'simulated' });
  assert.equal(e.apply('new', normalize(msg())), false);
  e.select(['group@g.us']);
  assert.equal(e.apply('new', normalize(msg({ from: 'other@c.us', body: 'PRIVATE_UNSELECTED' }))), false);
  assert.ok(!JSON.stringify(e.state).includes('PRIVATE_UNSELECTED'));
});
test('history/new replay is idempotent and stale history never overrides live edit', () => {
  const e = engine(), m = normalize(msg());
  e.apply('history', m); e.apply('new', m); e.apply('edit', { ...m, text: 'novo' });
  e.apply('history', m); e.apply('new', m);
  assert.equal(e.library()[0].blocks[0].text, 'novo');
  assert.equal(Object.keys(e.state.messages).length, 1);
  assert.equal(e.report().events.edit, 1);
});
test('deletion purges text and author, including deletion before history', () => {
  for (const kind of ['delete_everyone', 'delete_me']) {
    const e = engine(), m = normalize(msg());
    e.apply('history', m); e.apply(kind, m); e.apply('history', m); e.apply('edit', m);
    assert.equal(e.library().length, 0);
    assert.ok(!JSON.stringify(e.state.messages).includes('texto sintético'));
    assert.equal(Object.values(e.state.messages)[0].deleted, true);
    const e2 = engine(); e2.apply(kind, m); e2.apply('history', m);
    assert.equal(e2.library().length, 0);
  }
});
test('edit can arrive before backfill', () => {
  const e = engine(), m = normalize(msg());
  e.apply('edit', { ...m, text: 'edited first' }); e.apply('history', m);
  assert.equal(e.library()[0].blocks[0].text, 'edited first');
});
test('snapshot restart retains tombstones and prunes deselected chats', () => {
  const e = engine(), m = normalize(msg()); e.apply('delete_everyone', m);
  const resumed = new Engine({ snapshot: JSON.parse(JSON.stringify(e.state)), mode: 'simulated' });
  resumed.apply('history', m); assert.equal(resumed.library().length, 0);
  resumed.select(['other@c.us']); assert.equal(Object.keys(resumed.state.messages).length, 0);
});
test('library uses daily documents, pseudonyms, provenance and untrusted blocks', () => {
  const e = engine(); e.apply('history', normalize(msg()));
  const [doc] = e.library();
  assert.match(doc.source_url, /^arquivio-poc:\/\/whatsapp\/chat-1\//);
  assert.equal(doc.untrusted, true); assert.equal(doc.blocks[0].untrusted, true);
  assert.ok(!JSON.stringify(doc).includes('group@g.us'));
});
test('public report contains counts only, no identifiers/text/session salt', () => {
  const e = engine(); e.apply('new', normalize(msg()));
  e.historyResult('group@g.us', { requested: 50, returned: 1, durationMs: 4, ok: true });
  const report = e.report(), json = JSON.stringify(report);
  for (const privateValue of ['group@g.us', 'texto sintético', e.state.salt]) assert.ok(!json.includes(privateValue));
  assert.equal(report.validation, 'simulated'); assert.equal(report.realIntegrationValidated, false);
  assert.equal(report.history[0].complete, false);
});
test('real mode still has no automatic claim of validation', () => {
  const e = new Engine({ mode: 'real', selected: ['group@g.us'] });
  e.apply('new', normalize(msg()));
  assert.equal(e.report().realIntegrationValidated, false);
});

test('evidence survives empty selection, reordering and restart with run/selection identity', () => {
  const e = engine();
  e.beginRun({ durationMinutes: 90 }); e.select(['group@g.us', 'other@c.us']);
  e.historyResult('group@g.us', { requested: 200, returned: 1, ok: true });
  e.observe('history', 'pass');
  const original = structuredClone(e.report());
  e.select([]); e.select(['other@c.us', 'group@g.us']);
  e.historyResult('group@g.us', { requested: 500, returned: 1, ok: true });
  assert.deepEqual(e.report().history[0], original.history[0]);
  assert.deepEqual(e.report().observations, original.observations);
  assert.equal(e.report().history[1].chat, original.history[0].chat);
  assert.notEqual(e.report().history[1].selectionId, original.history[0].selectionId);
  e.endRun('STOPPED');
  const resumed = new Engine({ mode: 'simulated', snapshot: structuredClone(e.state) });
  resumed.beginRun({ durationMinutes: 90 });
  assert.equal(resumed.apply('new', normalize(msg())), false);
  assert.equal(resumed.report().history.length, 2);
  resumed.select(['group@g.us']); resumed.observe('restart', 'pass');
  assert.notEqual(resumed.report().observations[1].runId, original.observations[0].runId);
  assert.equal(resumed.report().runs.length, 2);
  for (const value of ['group@g.us', 'other@c.us']) assert.ok(!JSON.stringify(resumed.report()).includes(value));
});

test('legacy evidence is retained with explicit legacy provenance on migration', () => {
  const e = engine(); e.historyResult('group@g.us', { requested: 200 }); e.observe('history', 'pass');
  const snapshot = structuredClone(e.state);
  delete snapshot.runs; delete snapshot.selections; delete snapshot.chatAliases;
  for (const row of [...snapshot.history, ...snapshot.observations]) { delete row.runId; delete row.selectionId; }
  const migrated = new Engine({ mode: 'simulated', snapshot });
  migrated.beginRun({ durationMinutes: 60 }); migrated.select(['other@c.us']);
  assert.equal(migrated.report().history[0].runId, 'legacy');
  assert.equal(migrated.report().observations[0].selectionId, 'legacy');
});
