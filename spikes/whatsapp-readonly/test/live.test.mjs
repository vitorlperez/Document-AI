import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, realpathSync, rmSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Engine, normalize } from '../src/core.mjs';
import { Store } from '../src/store.mjs';
import { runLive, durationMinutes } from '../src/live.mjs';

const message = (id, chat = 'demo@g.us') => ({ id: { _serialized: id }, from: chat,
  timestamp: 1_760_000_000, type: 'chat', body: `synthetic-${id}` });
function setup(t) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'wa-live-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const store = new Store(join(root, 'real'));
  const e = new Engine({ mode: 'real', selected: ['demo@g.us'] });
  e.beginRun({ durationMinutes: 60 }); e.select(['demo@g.us']);
  e.apply('new', normalize(message('retained'))); e.apply('delete_me', normalize(message('deleted')));
  e.historyResult('demo@g.us', { requested: 200, returned: 1 }); e.observe('history', 'pass'); e.endRun('STOPPED');
  store.lock(); store.save(e); store.unlock();
  return { store, original: structuredClone(e.state) };
}
function harness(store, answers, onQuestion = () => {}, lines = ['check restart pass', 'quit']) {
  const calls = [], logs = [], signals = new EventEmitter();
  let client, index = 0, timerMs, timerCallback;
  const prompt = { close() {}, async question(text, { signal } = {}) {
    assert.equal(signal?.aborted ?? false, false);
    await onQuestion(index, client, calls, text);
    return answers[index++];
  }, async *[Symbol.asyncIterator]() { yield* lines; } };
  class Client extends EventEmitter {
    readOnly = {
      catalog: async () => (await this.getChats()).map(c => ({ id: c.id._serialized, name: c.name, isGroup: c.isGroup })),
      history: async (id, limit) => (await this.getChatById(id)).fetchMessages({ limit })
    };
    async initialize() { calls.push('initialize'); this.emit('message_create', message('before-ready')); this.emit('ready'); }
    async getChats() { calls.push('list'); this.emit('message_create', message('before-selection'));
      return ['demo@g.us', 'other@c.us'].map(id => ({ id: { _serialized: id }, name: 'synthetic', isGroup: id.endsWith('g.us') })); }
    async getChatById(id) { calls.push(`fetch:${id}`); return { fetchMessages: async () => {
      this.emit('message_create', message('authorized', id));
      this.emit('message_create', message('control', 'control@c.us'));
      return [message('retained'), message('deleted')];
    } }; }
    async destroy() { calls.push('destroy'); }
    sendMessage() { assert.fail('send forbidden'); }
  }
  return { calls, logs, get timerMs() { return timerMs; }, expire() { timerCallback(); },
    options: { args: ['--consent', '--duration-minutes', '90'], input: { isTTY: true }, output: { isTTY: true },
      createPrompt: () => prompt, createStore: () => { calls.push('store'); return store; }, signals,
      makeClient: async () => { calls.push('client'); return client = new Client(); },
      log: text => logs.push(text), setTimer: (fn, ms) => { timerMs = ms; timerCallback = fn; return 1; },
      clearTimer: () => calls.push('clearTimer') } };
}

test('duration is bounded explicitly and rejects malformed/ambiguous options', () => {
  assert.equal(durationMinutes([]), 60);
  assert.equal(durationMinutes(['--consent', '--duration-minutes', '120']), 120);
  for (const args of [['--duration-minutes'], ['--duration-minutes', '0'], ['--duration-minutes', '121'],
    ['--duration-minutes', '1.5'], ['--duration-minutes', 'NaN'], ['--duration-minutes', '2', '--duration-minutes', '3'], ['--unknown']]) {
    assert.throws(() => durationMinutes(args), /INVALID_DURATION_OPTIONS/);
  }
});

test('live gates reject consent/TTY before prompt, storage or client; linking refusal opens nothing', async t => {
  const { store } = setup(t);
  for (const patch of [{ args: [] }, { input: { isTTY: false } }, { output: { isTTY: false } }]) {
    const h = harness(store, []);
    await assert.rejects(runLive({ ...h.options, ...patch, createPrompt: () => assert.fail('no prompt') }), /LIVE_REQUIRES_TTY_AND_CONSENT/);
    assert.deepEqual(h.calls, []);
  }
  const h = harness(store, ['cancel']); assert.equal(await runLive(h.options), 'CANCELLED');
  assert.deepEqual(h.calls, []);
});

test('live restart requires fresh selection AND confirmation, preserves evidence and tombstones', async t => {
  const { store, original } = setup(t);
  const h = harness(store, ['VINCULAR', '1', 'SINCRONIZAR'], (step, client, calls) => {
    if (step === 0) assert.deepEqual(calls, []);
    if (step === 1 || step === 2) {
      client.emit('message_create', message(`before-human-gate-${step}`));
      assert.ok(!calls.some(x => x.startsWith('fetch:')));
      const snapshot = store.load();
      assert.deepEqual(snapshot.messages, original.messages);
      assert.deepEqual(snapshot.history, original.history);
      assert.deepEqual(snapshot.observations, original.observations);
    }
  });
  assert.equal(await runLive(h.options), 'STOPPED');
  assert.equal(h.timerMs, 90 * 60_000);
  const snapshot = store.load(), report = JSON.parse(readFileSync(join(store.root, 'report.json')));
  assert.equal(report.history.length, 2); assert.equal(report.observations.length, 2);
  assert.deepEqual(report.history[0], original.history[0]);
  assert.equal(report.runs.length, 2); assert.equal(report.runs[1].status, 'STOPPED');
  assert.notEqual(report.history[0].runId, report.history[1].runId);
  assert.equal(report.tombstones, 1); assert.equal(report.retainedMessages, 2);
  for (const forbidden of ['synthetic-before-ready', 'synthetic-before-selection', 'synthetic-before-human-gate', 'synthetic-control', 'synthetic-deleted']) {
    assert.ok(!JSON.stringify(snapshot).includes(forbidden));
  }
  assert.equal(h.calls.filter(x => x.startsWith('fetch:')).length, 1);
  assert.ok(h.calls.includes('destroy')); assert.equal(store.ownsLock, false);
});

test('disconnect while confirming aborts the old authorization and never resumes it', async t => {
  const { store, original } = setup(t);
  const h = harness(store, ['VINCULAR', '1', 'SINCRONIZAR'], (step, client) => {
    if (step === 2) client.emit('disconnected', 'LOGOUT');
  });
  assert.equal(await runLive(h.options), 'AUTH_REQUIRED');
  assert.deepEqual(store.load().messages, original.messages);
  assert.deepEqual(store.load().history, original.history);
  assert.ok(!h.calls.some(x => x.startsWith('fetch:')));
  assert.equal(store.ownsLock, false);
});

test('empty/invalid selection or declined confirmation never resumes old selection', async t => {
  for (const tail of [[''], ['0'], ['1', 'cancel']]) {
    const { store, original } = setup(t);
    const h = harness(store, ['VINCULAR', ...tail]);
    const status = await runLive(h.options);
    assert.ok(['CANCELLED', 'LOCAL_SETUP_FAILED'].includes(status));
    const snapshot = store.load();
    assert.deepEqual(snapshot.messages, original.messages);
    assert.deepEqual(snapshot.history, original.history);
    assert.deepEqual(snapshot.observations, original.observations);
    assert.ok(!h.calls.some(x => x.startsWith('fetch:')));
    assert.equal(store.ownsLock, false); assert.ok(h.calls.includes('destroy'));
  }
});

test('configured deadline stops actual session during selection and saves earlier evidence', async t => {
  const { store, original } = setup(t);
  const h = harness(store, ['VINCULAR', '1', 'SINCRONIZAR'], step => { if (step === 1) h.expire(); });
  assert.equal(await runLive(h.options), 'RUNTIME_LIMIT');
  assert.deepEqual(store.load().messages, original.messages);
  assert.deepEqual(store.load().history, original.history);
  assert.equal(store.load().runs.at(-1).status, 'RUNTIME_LIMIT');
  assert.ok(!h.calls.some(x => x.startsWith('fetch:'))); assert.equal(store.ownsLock, false);
});

test('catalog rejection before selection reports its exact stage but no private exception', async t => {
  const { store, original } = setup(t);
  const h = harness(store, ['VINCULAR']);
  class Client extends EventEmitter {
    readOnly = { catalog: () => this.getChats() };
    async initialize() { this.emit('ready'); }
    async getChats() { throw new Error('r'); }
    async destroy() { h.calls.push('destroy'); }
  }
  assert.equal(await runLive({ ...h.options, makeClient: async () => new Client() }), 'LOCAL_SETUP_FAILED');
  const records = h.logs.filter(x => x.startsWith('SETUP_DIAGNOSTIC ')).map(x => JSON.parse(x.slice(17)));
  assert.ok(records.some(r => r.stage === 'list_chats' && r.event === 'failed' && r.error.kind === 'OPAQUE_WEB_ERROR'));
  assert.deepEqual(store.load().messages, original.messages);
  assert.ok(h.calls.includes('destroy')); assert.equal(store.ownsLock, false);
  assert.ok(!h.logs.some(x => x.includes('Use uma conta de teste')));
});
