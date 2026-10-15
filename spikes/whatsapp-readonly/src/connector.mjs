import { normalize, supportedChat } from './core.mjs';

export class RetryBudget {
  attempts = 0;
  next(reason) {
    if (['LOGOUT', 'UNPAIRED', 'UNPAIRED_IDLE', 'CONFLICT', 'auth_failure'].includes(reason) || this.attempts >= 3) return null;
    return 1000 * 2 ** this.attempts++;
  }
}

// Deliberately small read surface. No raw client or message objects escape this adapter.
export class ReadOnlyConnector {
  constructor(client, engine, { changed = () => {}, failed = () => {} } = {}) {
    this.client = client; this.engine = engine; this.handlers = []; this.active = true;
    const on = (event, fn) => {
      const wrapped = (...args) => { try { fn(...args); } catch { failed('EVENT_FAILED'); } };
      client.on(event, wrapped); this.handlers.push([event, wrapped]);
    };
    const apply = (kind, raw, opts) => { if (engine.apply(kind, normalize(raw, opts))) changed(); };
    // message_create includes messages sent manually on another linked device.
    on('message_create', msg => apply('new', msg));
    on('message_edit', (msg, newBody) => apply('edit', msg, { text: newBody }));
    on('message_revoke_everyone', msg => apply('delete_everyone', msg, { deletion: true }));
    on('message_revoke_me', msg => apply('delete_me', msg, { deletion: true }));
    for (const [event, metric] of [['ready', 'ready'], ['disconnected', 'disconnected'], ['auth_failure', 'authFailure']]) {
      on(event, () => { engine.state.connection[metric]++; changed(); });
    }
  }
  async list() {
    const chats = (await this.client.getChats()).filter(c => supportedChat(c.id?._serialized)).map(c => ({
      id: c.id._serialized, name: c.name, isGroup: Boolean(c.isGroup) }));
    this.engine.state.catalog = { chats: chats.length, groups: chats.filter(c => c.isGroup).length,
      individual: chats.filter(c => !c.isGroup).length };
    return chats;
  }
  async history(id, limit) {
    if (!this.active) throw Error('INACTIVE_SESSION');
    if (!this.engine.state.selected.includes(id)) throw Error('NOT_SELECTED');
    if (!Number.isInteger(limit) || limit < 1 || limit > 5000) throw Error('INVALID_LIMIT');
    const start = performance.now(), baseline = this.engine.revision;
    try {
      const chat = await this.client.getChatById(id);
      const messages = await chat.fetchMessages({ limit });
      if (!this.active) throw Error('INACTIVE_SESSION');
      let retained = 0;
      for (const raw of messages) {
        if (raw.type === 'revoked') this.engine.apply('delete_everyone', normalize(raw, { deletion: true }));
        else if (this.engine.apply('history', normalize(raw), { baseline })) retained++;
      }
      const times = messages.map(m => m.timestamp).filter(Number.isFinite);
      this.engine.historyResult(id, { requested: limit, returned: messages.length, newlyRetained: retained,
        oldestAgeDays: times.length ? Math.floor((Date.now() / 1000 - Math.min(...times)) / 86400) : null,
        spanDays: times.length ? Math.floor((Math.max(...times) - Math.min(...times)) / 86400) : null,
        durationMs: Math.round(performance.now() - start), ok: true });
    } catch {
      this.engine.historyResult(id, { requested: limit, returned: 0, durationMs: Math.round(performance.now() - start), ok: false });
      throw Error('HISTORY_FAILED');
    }
  }
  dispose() { this.active = false; for (const [event, handler] of this.handlers) this.client.off(event, handler); }
}
