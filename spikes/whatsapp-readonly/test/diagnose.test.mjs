import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { mkdtempSync, realpathSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { runDiagnosis } from '../src/diagnose.mjs';
import { safeDiagnostic } from '../src/diagnostics.mjs';
import { realClient } from '../src/live.mjs';
import { Store } from '../src/store.mjs';

function harness(t, failure) {
  const home = mkdtempSync(join(realpathSync(tmpdir()), 'wa-diagnose-test-'));
  t.after(() => rmSync(home, { recursive: true, force: true }));
  const root = join(home, 'real');
  mkdirSync(join(root, 'auth/session-readonly-poc'), { recursive: true });
  mkdirSync(join(root, 'web-cache'));
  const preserved = ['.arquivio-wa-poc', 'library.private.json', 'report.json',
    'auth/session-readonly-poc/synthetic-auth', 'web-cache/synthetic-cache'];
  // Invalid JSON is intentional: diagnosis must never load snapshots or cached data.
  for (const path of preserved) writeFileSync(join(root, path), 'PRIVATE_SENTINEL_NOT_JSON', { mode: 0o600 });
  const logs = [], calls = [], signals = new EventEmitter();
  let client;
  class Client extends EventEmitter {
    async initialize() {
      calls.push('initialize'); this.emit('authenticated', 'PRIVATE_AUTH_PAYLOAD');
      if (failure === 'qr') { this.emit('qr', 'PRIVATE_QR'); return; }
      if (failure === 'disconnect') { this.emit('disconnected', 'PRIVATE_DISCONNECT'); return; }
      if (failure === 'initialize') throw new Error('PRIVATE_INITIALIZE');
      this.emit('ready');
    }
    async getChats() {
      calls.push('getChats'); this.emit('message_create', { get id() { assert.fail('no event payload inspection before selection'); } });
      if (failure === 'hang') return new Promise(() => {});
      if (failure === 'list') throw Object.assign(new Error('r'), { stack: 'Error: r\n at Client.getChats (/PRIVATE_PATH/Client.js:1669:23)' });
      return [{ get name() { assert.fail('diagnosis must not inspect names'); },
        get lastMessage() { assert.fail('diagnosis must not inspect content'); } }];
    }
    async destroy() { calls.push('destroy'); }
    async logout() { assert.fail('logout would delete auth'); }
    async getChatById() { assert.fail('no history or selection'); }
    async sendMessage() { assert.fail('no sending'); }
  }
  return { root, logs, calls, signals, get client() { return client; },
    options: { home, args: [], input: { isTTY: true }, output: { isTTY: true }, signals,
      makeClient: async () => { calls.push('client'); return client = new Client(); }, log: line => logs.push(line) },
    verifyPreserved() {
      for (const path of preserved) assert.equal(readFileSync(join(root, path), 'utf8'), 'PRIVATE_SENTINEL_NOT_JSON');
      assert.equal(existsSync(join(root, 'run.lock')), false);
      assert.equal(existsSync(join(root, 'run.lock.guard')), false);
      assert.ok(!logs.join('\n').includes('PRIVATE_'));
      assert.equal(signals.listenerCount('SIGINT'), 0); assert.equal(signals.listenerCount('SIGTERM'), 0);
      if (client) for (const event of client.eventNames()) assert.equal(client.listenerCount(event), 0);
    } };
}

test('diagnosis reuses only an existing profile, probes getChats and never reads or rewrites snapshots/auth/cache', async t => {
  const h = harness(t);
  assert.equal(await runDiagnosis(h.options), 'SETUP_DIAGNOSED');
  assert.deepEqual(h.calls, ['client', 'initialize', 'getChats', 'destroy']);
  assert.ok(h.logs.some(x => x.includes('"stage":"list_chats","event":"reached"')));
  assert.ok(!h.logs.some(x => /VINCULAR|SINCRONIZAR/.test(x)));
  h.verifyPreserved();
});

test('diagnosis reproduces failed list and initialization as different safe stages, without retries', async t => {
  for (const [failure, stage] of [['list', 'list_chats'], ['initialize', 'initialize']]) {
    const h = harness(t, failure);
    assert.equal(await runDiagnosis(h.options), 'LOCAL_SETUP_FAILED');
    const record = h.logs.filter(x => x.startsWith('SETUP_DIAGNOSTIC '))
      .map(x => JSON.parse(x.slice(17))).find(r => r.stage === stage && r.event === 'failed');
    assert.ok(record);
    if (failure === 'list') {
      assert.equal(record.error.kind, 'OPAQUE_WEB_ERROR'); assert.deepEqual(record.error.frames, ['Client.getChats']);
    }
    assert.equal(h.calls.filter(x => x === 'initialize').length, 1);
    h.verifyPreserved();
  }
});

test('diagnosis stops on QR/auth loss or disconnect instead of relinking or reconnecting', async t => {
  for (const failure of ['qr', 'disconnect']) {
    const h = harness(t, failure);
    assert.equal(await runDiagnosis(h.options), failure === 'qr' ? 'AUTH_REQUIRED' : 'DISCONNECTED');
    assert.deepEqual(h.calls, ['client', 'initialize', 'destroy']);
    h.verifyPreserved();
  }
});

test('diagnosis refuses missing session without creating storage/client and rejects non-TTY/unknown options', async t => {
  const h = harness(t);
  const home = join(h.root, 'absent');
  await assert.rejects(runDiagnosis({ ...h.options, home }), /EXISTING_SESSION_REQUIRED/);
  assert.equal(existsSync(home), false); assert.deepEqual(h.calls, []);
  await assert.rejects(runDiagnosis({ ...h.options, input: { isTTY: false } }), /DIAGNOSIS_REQUIRES_TTY/);
  await assert.rejects(runDiagnosis({ ...h.options, args: ['--unknown'] }), /INVALID_DIAGNOSIS_OPTIONS/);
  assert.deepEqual(h.calls, []); h.verifyPreserved();
});

test('diagnostic is a closed vocabulary even for hostile errors, fields, strings and stack paths', () => {
  const secret = 'PRIVATE_CHAT_PHONE_TOKEN_QR_PATH';
  for (const error of [secret, new TypeError(secret), { name: secret, code: secret, stack: secret, message: secret },
    { get message() { throw Error(secret); } }, undefined]) {
    assert.ok(!JSON.stringify(safeDiagnostic(secret, 'failed', error)).includes('PRIVATE_'));
  }
  const e = Object.assign(new Error(`Evaluation failed: ${secret}`), { code: 'EACCES' });
  assert.deepEqual(safeDiagnostic('list_chats', 'failed', e).error,
    { type: 'Error', kind: 'WEB_EVALUATION', code: 'EACCES', frames: [] });
  let names = 0, codes = 0;
  const changingGetters = { message: secret, stack: secret,
    get name() { return ++names === 1 ? 'Error' : secret; },
    get code() { return ++codes === 1 ? 'EACCES' : secret; } };
  assert.ok(!JSON.stringify(safeDiagnostic('list_chats', 'failed', changingGetters)).includes('PRIVATE_'));
});

test('diagnosis bounds a stuck getChats and releases the lock while preserving the profile', async t => {
  const h = harness(t, 'hang');
  assert.equal(await runDiagnosis({ ...h.options, readyTimeoutMs: 10 }), 'DIAGNOSIS_TIMEOUT');
  assert.deepEqual(h.calls, ['client', 'initialize', 'getChats', 'destroy']); h.verifyPreserved();
});

test('real diagnostic auth strategy refuses pairing and does not delete its synthetic profile on logout', async t => {
  const h = harness(t), store = new Store(h.root);
  const client = await realClient(store, { reuseOnly: true }); // Construct only; no initialize/browser/network.
  await client.authStrategy.beforeBrowserInitialized();
  const required = await client.authStrategy.onAuthenticationNeeded();
  assert.equal(required.failed, true); assert.equal(required.restart, false);
  await client.authStrategy.logout();
  h.verifyPreserved();
});
