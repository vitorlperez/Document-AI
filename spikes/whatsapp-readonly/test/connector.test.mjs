import test from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { Engine } from '../src/core.mjs';
import { ReadOnlyConnector, RetryBudget } from '../src/connector.mjs';

class FakeClient extends EventEmitter {
  calls = [];
  async getChats() { this.calls.push('getChats'); return [{ id: { _serialized: 'demo@g.us' }, isGroup: true, name: 'Demo' }]; }
  async getChatById(id) { this.calls.push(['getChatById', id]); return { fetchMessages: async options => {
    this.calls.push(['fetchMessages', options]); return [this.message()];
  } }; }
  message() { return { id: { _serialized: 'm1' }, from: 'demo@g.us', timestamp: 1_760_000_000, type: 'chat', body: 'original' }; }
  sendMessage() { throw Error('MUST NEVER BE CALLED'); }
  sendSeen() { throw Error('MUST NEVER BE CALLED'); }
}
test('adapter lists, fetches only explicit selection and captures own/new/edit/delete events', async () => {
  const c = new FakeClient(), e = new Engine({ mode: 'simulated' });
  const adapter = new ReadOnlyConnector(c, e);
  assert.equal((await adapter.list())[0].isGroup, true);
  await assert.rejects(adapter.history('demo@g.us', 50));
  e.select(['demo@g.us']); await adapter.history('demo@g.us', 50);
  c.emit('message_create', c.message());
  c.emit('message_edit', c.message(), 'edited', 'original');
  assert.equal(e.library()[0].blocks[0].text, 'edited');
  c.emit('message_revoke_everyone', { ...c.message(), body: undefined }, undefined);
  assert.equal(e.library().length, 0);
  assert.deepEqual(c.calls, ['getChats', ['getChatById', 'demo@g.us'], ['fetchMessages', { limit: 50 }]]);
  adapter.dispose(); assert.equal(c.listenerCount('message_create'), 0);
});
test('disconnection records safe counters, not raw reasons; revoke_me works', () => {
  const c = new FakeClient(), e = new Engine({ mode: 'simulated', selected: ['demo@g.us'] });
  new ReadOnlyConnector(c, e);
  c.emit('message_create', c.message()); c.emit('message_revoke_me', c.message());
  c.emit('disconnected', 'SECRET_REASON');
  assert.equal(e.library().length, 0);
  assert.equal(e.report().connection.disconnected, 1);
  assert.ok(!JSON.stringify(e.state).includes('SECRET_REASON'));
});
test('retry budget is bounded, exponential, and auth failures are terminal', () => {
  const b = new RetryBudget();
  assert.deepEqual([b.next('network'), b.next('network'), b.next('network'), b.next('network')], [1000, 2000, 4000, null]);
  for (const reason of ['LOGOUT', 'UNPAIRED', 'UNPAIRED_IDLE', 'CONFLICT', 'auth_failure']) assert.equal(new RetryBudget().next(reason), null);
});
test('revocation uses protocolMessageKey for original identity when envelope id differs', () => {
  const c = new FakeClient(), e = new Engine({ mode: 'simulated', selected: ['demo@g.us'] });
  new ReadOnlyConnector(c, e); c.emit('message_create', c.message());
  c.emit('message_revoke_everyone', { ...c.message(), id: { _serialized: 'revoke-envelope' },
    protocolMessageKey: { _serialized: 'm1' } });
  assert.equal(e.library().length, 0);
});
test('refetch reconciles changed historical text but does not overwrite an edit during fetch', async () => {
  const c = new FakeClient(), e = new Engine({ mode: 'simulated', selected: ['demo@g.us'] });
  const adapter = new ReadOnlyConnector(c, e);
  c.emit('message_create', c.message());
  c.getChatById = async () => ({ fetchMessages: async () => [{ ...c.message(), body: 'edited while offline' }] });
  await adapter.history('demo@g.us', 50);
  assert.equal(e.library()[0].blocks[0].text, 'edited while offline');
  c.getChatById = async () => ({ fetchMessages: async () => {
    c.emit('message_edit', c.message(), 'edit during fetch');
    return [c.message()];
  } });
  await adapter.history('demo@g.us', 50);
  assert.equal(e.library()[0].blocks[0].text, 'edit during fetch');
});
test('revoked marker in refetched history purges a known message', async () => {
  const c = new FakeClient(), e = new Engine({ mode: 'simulated', selected: ['demo@g.us'] });
  const adapter = new ReadOnlyConnector(c, e); c.emit('message_create', c.message());
  c.getChatById = async () => ({ fetchMessages: async () => [{ ...c.message(), type: 'revoked', body: '' }] });
  await adapter.history('demo@g.us', 50); assert.equal(e.library().length, 0);
});
