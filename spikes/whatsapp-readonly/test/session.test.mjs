import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { LiveSession } from '../src/session.mjs';
import { Engine } from '../src/core.mjs';

test('actual lifecycle destroys clients, reuses engine and retries three times only', async () => {
  const e = new Engine({ mode: 'simulated' }); let created = 0, destroyed = 0, ready = 0;
  class Client extends EventEmitter {
    async initialize() { this.emit('ready'); setImmediate(() => this.emit('disconnected', 'NETWORK')); }
    async destroy() { destroyed++; }
  }
  const session = new LiveSession({ engine: e, makeClient: async () => { created++; return new Client(); },
    onReady: async () => { ready++; }, delay: async () => {} });
  assert.equal(await session.run(), 'RETRIES_EXHAUSTED');
  assert.equal(created, 4); assert.equal(destroyed, 4); assert.equal(ready, 4);
  assert.equal(e.report().connection.reconnectAttempts, 3);
});
test('auth failure never retries or leaks its private reason', async () => {
  const e = new Engine({ mode: 'simulated' }); let created = 0;
  class Client extends EventEmitter {
    async initialize() { this.emit('auth_failure', 'PRIVATE_TOKEN'); }
    async destroy() {}
  }
  const s = new LiveSession({ engine: e, makeClient: async () => { created++; return new Client(); } });
  assert.equal(await s.run(), 'AUTH_REQUIRED'); assert.equal(created, 1);
  assert.ok(!JSON.stringify(e.report()).includes('PRIVATE_TOKEN'));
});
test('timeout and operator stop are bounded and clean up', async () => {
  class Client extends EventEmitter { async initialize() {} async destroy() {} }
  const e = new Engine({ mode: 'simulated' });
  const s = new LiveSession({ engine: e, makeClient: async () => new Client(), readyTimeoutMs: 5 });
  assert.equal(await s.run(), 'READY_TIMEOUT');
  const s2 = new LiveSession({ engine: e, makeClient: async () => new Client() });
  const running = s2.run(); setImmediate(() => s2.stop());
  assert.equal(await running, 'STOPPED');
});
test('disconnect aborts an in-progress human setup instead of leaving a stale prompt', async () => {
  const e = new Engine({ mode: 'simulated' }); let cancelled = false;
  class Client extends EventEmitter {
    async initialize() { this.emit('ready'); setImmediate(() => this.emit('disconnected', 'LOGOUT')); }
    async destroy() {}
  }
  const s = new LiveSession({ engine: e, makeClient: async () => new Client(),
    onReady: async (_adapter, signal) => new Promise(resolve => {
      signal.addEventListener('abort', () => { cancelled = true; resolve(); }, { once: true });
    }) });
  assert.equal(await s.run(), 'AUTH_REQUIRED'); assert.equal(cancelled, true);
});
test('failed persistence is an error status, not successful operator stop', async () => {
  const e = new Engine({ mode: 'simulated' });
  class Client extends EventEmitter { async initialize() { this.emit('ready'); } async destroy() {} }
  const s = new LiveSession({ engine: e, makeClient: async () => new Client(),
    changed: () => { throw Error('PRIVATE_PATH'); } });
  assert.equal(await s.run(), 'EVENT_PERSISTENCE_FAILED');
});
