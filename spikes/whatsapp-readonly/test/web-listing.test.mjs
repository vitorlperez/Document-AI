import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { createContext, runInContext } from 'node:vm';
import { mkdtempSync, realpathSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { realClient, runLive } from '../src/live.mjs';
import { Engine } from '../src/core.mjs';
import { ReadOnlyConnector } from '../src/connector.mjs';
import { Store } from '../src/store.mjs';
import { EventEmitter } from 'node:events';

const require = createRequire(import.meta.url);
const { LoadUtils } = require('whatsapp-web.js/src/util/Injected/Utils.js');

// Runs the installed dependency's actual injected serializers in an isolated VM.
// No browser, profile, network or real account. JSON roundtrip models CDP transfer.
async function fixture(fault = 'message_key') {
  const calls = [], records = [], transfers = [];
  const message = { id: { _serialized: 'synthetic-message', id: 'synthetic', remote: 'demo@g.us' },
    type: 'chat', body: 'synthetic text', from: 'demo@g.us', t: 1_760_000_000 };
  const chat = { id: { _serialized: 'demo@g.us' }, formattedTitle: 'Synthetic group',
    lastReceivedKey: { $1: 'synthetic-message' },
    msgs: { getModelsArray: () => [{ serialize: () => structuredClone(message) }] },
    serialize() {
      calls.push('serialize');
      if (fault === 'serialize') throw Object.assign(new Error('r'), { name: 'r' });
      return { id: this.id, msgs: ['synthetic-message'] };
    } };
  const collections = {
    Chat: { getModelsArray() { calls.push('enumerate');
      if (fault === 'enumerate') throw new TypeError('PRIVATE_CHAT_NUMBER_TOKEN');
      return [chat]; }, get: () => chat },
    Msg: { get: key => { calls.push(key === undefined ? 'missing_key' : 'valid_key'); return undefined; },
      getMessagesById: async keys => {
        if (keys[0] === undefined) throw Object.assign(new Error('r'), { name: 'r' });
        return { messages: [] };
      } }
  };
  const modules = { WAWebCollections: collections, WAWebWidFactory: { createWid: id => ({ _serialized: id }) },
    WALinkify: { findLinks: () => [] }, WAWebChatLoadMessages: { loadEarlierMsgs: async () => [] } };
  const context = createContext({ window: { require: name => {
    if (fault === 'capabilities' && name === 'WAWebCollections') return {};
    if (!(name in modules)) throw Error('UNEXPECTED_MODULE');
    return modules[name];
  } } });
  runInContext(`(${LoadUtils.toString()})()`, context);
  const client = await realClient({ directory: () => '/tmp/arquivio-unused-synthetic-profile' }, { reuseOnly: true });
  client.pupPage = { async evaluate(fn, ...args) {
    context.args = args;
    const result = await runInContext(`(${fn.toString()})(...args)`, context);
    const transferred = result === undefined ? undefined : JSON.parse(JSON.stringify(result));
    transfers.push(transferred);
    return transferred;
  } };
  const engine = new Engine({ mode: 'simulated' });
  return { client, engine, chat, collections, calls, records, transfers,
    adapter: new ReadOnlyConnector(client, engine, { diagnostic: record => records.push(record) }) };
}

for (const fault of ['message_key', 'serialize']) {
  test(`real 1.34.7 getChats fails at ${fault}; POC still lists complete minimal catalog`, async () => {
    const h = await fixture(fault);
    await assert.rejects(h.client.getChats(), error => error.message === 'r');
    if (fault === 'message_key') assert.ok(h.calls.includes('missing_key'));
    h.calls.length = 0;
    assert.deepEqual(await h.adapter.list(), [{ id: 'demo@g.us', name: 'Synthetic group', isGroup: true }]);
    assert.deepEqual(h.calls, ['enumerate']);
    assert.equal(h.engine.state.catalog.groups, 1);
    assert.ok(h.records.some(r => r.stage === 'chat_enumeration' && r.event === 'reached'));
    assert.ok(h.records.some(r => r.stage === 'chat_projection' && r.event === 'reached'));
  });
}

test('history uses actual Chat.fetchMessages without getChatModel, after the selection gate only', async () => {
  const h = await fixture('serialize');
  await assert.rejects(h.client.getChatById('demo@g.us'), error => error.message === 'r');
  h.calls.length = 0;
  await assert.rejects(h.adapter.history('demo@g.us', 50), /NOT_SELECTED/);
  assert.deepEqual(h.calls, []);
  h.engine.select(['demo@g.us']);
  await h.adapter.history('demo@g.us', 50);
  assert.equal(h.engine.library()[0].blocks[0].text, 'synthetic text');
  assert.ok(!h.calls.includes('serialize'));
});

test('diagnosis probes capability, enumeration and IDs without exporting or reading titles/content', async () => {
  const h = await fixture('serialize');
  for (const field of ['formattedTitle', 'name', 'contact', 'lastReceivedKey', 'groupMetadata', 'isGroup', 'serialize', 'msgs']) {
    Object.defineProperty(h.chat, field, { get() { assert.fail(`must not access ${field}`); } });
  }
  await h.adapter.checkListing();
  assert.deepEqual(h.calls, ['enumerate']);
  assert.ok(!JSON.stringify(h.records).includes('Synthetic'));
  assert.ok(!JSON.stringify(h.records).includes('demo@'));
  assert.deepEqual(Object.keys(h.transfers.at(-1)).sort(), ['ok', 'records']);
  assert.ok(!JSON.stringify(h.transfers.at(-1)).includes('demo@'));
});

test('page failures preserve only allowlisted exception classes, even with hostile getters', async () => {
  for (const [error, type] of [[Object.assign(new Error('PRIVATE_MESSAGE'), { name: 'DataError' }), 'DataError'],
    [{ name: 'PRIVATE_NAME', code: 'PRIVATE_CODE', message: 'PRIVATE_NUMBER' }, 'unknown'],
    [{ get name() { throw Error('PRIVATE_GETTER'); } }, 'unknown']]) {
    const h = await fixture();
    h.collections.Chat.getModelsArray = () => { throw error; };
    await assert.rejects(h.adapter.checkListing(), /CATALOG_READ_FAILED/);
    const record = h.records.find(r => r.event === 'failed');
    assert.equal(record.stage, 'chat_enumeration');
    assert.equal(record.error.type, type);
    assert.ok(!JSON.stringify(h.transfers).includes('PRIVATE_'));
  }
});

test('invalid collection shape is distinct from a valid empty catalog', async () => {
  const h = await fixture();
  h.collections.Chat.getModelsArray = () => undefined;
  await assert.rejects(h.adapter.list(), /CATALOG_READ_FAILED/);
  assert.ok(h.records.some(r => r.error?.kind === 'INVALID_COLLECTION'));
  h.collections.Chat.getModelsArray = () => [];
  assert.deepEqual(await h.adapter.list(), []);
});

test('production reader reaches selection and actual upstream history in a fully synthetic live run', async t => {
  const h = await fixture('serialize');
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'wa-catalog-live-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const store = new Store(join(root, 'real')), logs = [];
  let step = 0, destroyed = false;
  h.client.initialize = async () => { h.client.emit('authenticated'); h.client.emit('ready'); };
  h.client.destroy = async () => { destroyed = true; };
  h.client.getChats = h.client.getChatById = async () => assert.fail('full chat serializer must never be used');
  const prompt = { close() {}, async question() {
    assert.equal(h.calls.includes('serialize'), false);
    assert.equal(Object.keys(store.load()?.messages ?? {}).length, 0);
    return ['VINCULAR', '1', 'SINCRONIZAR'][step++];
  }, async *[Symbol.asyncIterator]() { yield 'quit'; } };
  assert.equal(await runLive({ args: ['--consent'], input: { isTTY: true }, output: { isTTY: true },
    createPrompt: () => prompt, createStore: () => store, makeClient: async () => h.client,
    log: line => logs.push(line), signals: new EventEmitter() }), 'STOPPED');
  assert.equal(step, 3); assert.equal(destroyed, true); assert.equal(store.ownsLock, false);
  assert.equal(Object.keys(store.load().messages).length, 1);
  assert.ok(logs.some(line => line.includes('1. [grupo] Synthetic group')));
});

test('enumeration and capability failures get distinct closed stages and error classes, no skipped chats', async () => {
  for (const [fault, stage, type] of [['enumerate', 'chat_enumeration', 'TypeError'], ['capabilities', 'web_capabilities', 'Error']]) {
    const h = await fixture(fault);
    await assert.rejects(h.adapter.list());
    assert.ok(h.records.some(r => r.stage === stage && r.event === 'failed' && r.error.type === type));
    assert.ok(!JSON.stringify(h.records).includes('PRIVATE_'));
    assert.equal(h.engine.state.catalog.chats, 0);
  }
});

test('catalog excludes unsupported chats and derives groups from ID even without isGroup', async () => {
  const h = await fixture();
  h.collections.Chat.getModelsArray = () => [h.chat,
    { id: { _serialized: 'person@lid' }, name: 'Synthetic person' },
    { id: { _serialized: 'status@broadcast' }, get formattedTitle() { assert.fail('unsupported chat'); } },
    { id: { _serialized: 'feed@newsletter' } }];
  assert.deepEqual(await h.adapter.list(), [
    { id: 'demo@g.us', name: 'Synthetic group', isGroup: true },
    { id: 'person@lid', name: 'Synthetic person', isGroup: false }]);
});

test('invalid ID or throwing title fails the catalog visibly instead of returning a partial list', async () => {
  for (const fault of ['id', 'title']) {
    const h = await fixture();
    if (fault === 'id') h.chat.id = {};
    else Object.defineProperty(h.chat, 'formattedTitle', { get() { throw new RangeError('PRIVATE_NAME_PHONE'); } });
    await assert.rejects(h.adapter.list());
    assert.ok(h.records.some(r => r.stage === 'chat_projection' && r.event === 'failed'));
    assert.ok(!JSON.stringify(h.records).includes('PRIVATE_'));
    assert.equal(h.engine.state.catalog.chats, 0);
  }
});
