import { safeDiagnostic } from './diagnostics.mjs';

// Executed in the page. Return primitives only: never serialize a WhatsApp model.
// Probe mode returns no catalog and does not even read titles.
function catalogSnapshot(probeOnly) {
  const records = [];
  let stage = 'web_capabilities';
  const started = next => { stage = next; records.push({ stage, event: 'started' }); };
  const reached = () => records.push({ stage, event: 'reached' });
  const fail = code => { throw Object.assign(new Error(), { code }); };
  try {
    started('web_capabilities');
    if (typeof window.require !== 'function') fail('CAPABILITY_MISSING');
    const collection = window.require('WAWebCollections')?.Chat;
    if (typeof collection?.getModelsArray !== 'function') fail('CAPABILITY_MISSING');
    reached();

    started('chat_enumeration');
    const models = collection.getModelsArray();
    if (!Array.isArray(models)) fail('INVALID_COLLECTION');
    reached();

    started('chat_projection');
    const chats = [];
    for (const model of models) {
      const id = model?.id?._serialized;
      if (typeof id !== 'string' || !id) fail('INVALID_CHAT_ID');
      if (!/@(g\.us|c\.us|lid)$/.test(id)) continue;
      if (probeOnly) continue;
      // isGroup isn't reliably exposed by the raw model; the namespace is enough.
      const title = model.formattedTitle || model.name;
      chats.push({ id, name: typeof title === 'string' ? title : '', isGroup: id.endsWith('@g.us') });
    }
    reached();
    return probeOnly ? { ok: true, records } : { ok: true, records, chats };
  } catch (error) {
    let type = 'unknown', code = 'unknown', opaque = false;
    try {
      const name = error?.name, rawCode = error?.code, message = error?.message;
      if (['Error', 'TypeError', 'RangeError', 'SyntaxError', 'DataError', 'InvalidStateError',
        'NotSupportedError', 'NotFoundError', 'SecurityError'].includes(name)) type = name;
      if (['CAPABILITY_MISSING', 'INVALID_COLLECTION', 'INVALID_CHAT_ID'].includes(rawCode)) code = rawCode;
      opaque = typeof message === 'string' && /^r(?:: r)?$/.test(message);
    } catch { /* Error getters can themselves throw. No raw fields leave the page. */ }
    records.push({ stage, event: 'failed', error: { type, code, opaque } });
    return { ok: false, records };
  }
}

export function createWebReader(client, Chat) {
  return {
    async catalog({ probeOnly = false, diagnostic = () => {} } = {}) {
      const result = await client.pupPage.evaluate(catalogSnapshot, probeOnly);
      for (const record of result.records) {
        // Revalidate at the process boundary, even though the page uses literals.
        const error = record.error;
        diagnostic(safeDiagnostic(record.stage, record.event, error && {
          name: error.type, code: error.code, message: error.opaque === true ? 'r' : ''
        }));
      }
      if (!result.ok) throw Error('CATALOG_READ_FAILED');
      return result.chats;
    },
    async history(id, limit) {
      // getChatById would invoke getChatModel again. Construct only the ID holder;
      // the pinned Chat.fetchMessages uses getChat(..., {getAsModel:false}).
      const chat = new Chat(client, { id: { _serialized: id } });
      return chat.fetchMessages({ limit });
    }
  };
}
