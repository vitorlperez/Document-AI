// Optional Chromium/CDP check with synthetic page state only. Never opens WhatsApp.
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { realClient } from '../src/live.mjs';
import { Engine } from '../src/core.mjs';
import { ReadOnlyConnector } from '../src/connector.mjs';

const require = createRequire(import.meta.url);
const puppeteer = require(require.resolve('puppeteer', { paths: [require.resolve('whatsapp-web.js')] }));
const { LoadUtils } = require('whatsapp-web.js/src/util/Injected/Utils.js');
// Puppeteer creates its own temporary profile; no LocalAuth initialization.
const browser = await puppeteer.launch({ headless: true, dumpio: false });
try {
  const page = await browser.newPage();
  await page.setRequestInterception(true);
  page.on('request', request => request.abort());
  await page.goto('about:blank');
  await page.evaluate(() => {
    const chat = { id: { _serialized: 'synthetic@g.us' }, formattedTitle: 'Synthetic group',
      lastReceivedKey: { $1: 'synthetic-key' },
      serialize: () => ({ id: { _serialized: 'synthetic@g.us' }, msgs: ['synthetic-key'] }),
      msgs: { getModelsArray: () => [] } };
    const modules = {
      WAWebCollections: { Chat: { getModelsArray: () => [chat], get: () => chat },
        Msg: { get: () => undefined, getMessagesById: async keys => {
          // Use native IndexedDB key validation, without opening a database.
          // The pinned serializer supplies undefined for a $1-only message key.
          IDBKeyRange.only(keys[0]);
          return { messages: [] };
        } } },
      WAWebWidFactory: { createWid: id => ({ _serialized: id }) },
      WAWebChatLoadMessages: { loadEarlierMsgs: async () => [] }
    };
    window.require = name => modules[name];
  });
  await page.evaluate(LoadUtils);
  const client = await realClient({ directory: () => '/tmp/arquivio-unused-synthetic-profile' }, { reuseOnly: true });
  client.pupPage = page;
  // CDP recreates DOM exceptions as a Node error named DOMException, losing the
  // original class. The new catalog classifies inside the page before transfer.
  await assert.rejects(client.getChats(), error =>
    error.name === 'DOMException' && error.message.startsWith('DataError:'));
  const records = [], engine = new Engine({ mode: 'simulated' });
  const adapter = new ReadOnlyConnector(client, engine, { diagnostic: record => records.push(record) });
  await adapter.checkListing();
  assert.deepEqual(await adapter.list(), [{ id: 'synthetic@g.us', name: 'Synthetic group', isGroup: true }]);
  assert.ok(!JSON.stringify(records).includes('synthetic'));
  engine.select(['synthetic@g.us']);
  await adapter.history('synthetic@g.us', 10);
  assert.equal(engine.state.history.at(-1).ok, true);
  await page.evaluate(() => {
    window.require('WAWebCollections').Chat.getModelsArray = () => {
      throw new DOMException('Private synthetic metadata', 'DataError');
    };
  });
  await assert.rejects(adapter.checkListing(), /CATALOG_READ_FAILED/);
  assert.ok(records.some(r => r.stage === 'chat_enumeration' && r.error?.type === 'DataError'));
  assert.ok(!JSON.stringify(records).includes('Private'));
  assert.equal(page.url(), 'about:blank');
  console.log(JSON.stringify({ chromium: true, whatsappConnected: false, upstreamFailure: 'DataError',
    minimalCatalog: 'pass', probePrivacy: 'pass', historyWithoutChatSerialization: 'pass',
    browserErrorClassBeforeCDP: 'pass' }));
} finally { await browser.close(); }
