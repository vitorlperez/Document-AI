import { emptyCounters, supportedChat } from './core.mjs';

export class RetryBudget {
  attempts = 0;
  next(reason) {
    if (['LOGOUT', 'UNPAIRED', 'UNPAIRED_IDLE', 'CONFLICT', 'auth_failure'].includes(reason) || this.attempts >= 3) return null;
    return 1000 * 2 ** this.attempts++;
  }
}

// Deliberately small read surface. No raw client or message objects escape this adapter.
export class ReadOnlyConnector {
  constructor(client, engine, { changed = () => {}, failed = () => {}, diagnostic = () => {} } = {}) {
    this.client = client; this.engine = engine; this.handlers = []; this.active = true;
    this.diagnostic = diagnostic;
    const on = (event, fn) => {
      const wrapped = (...args) => { try { fn(...args); } catch { failed('EVENT_FAILED'); } };
      client.on(event, wrapped); this.handlers.push([event, wrapped]);
    };
    // Gate first: nothing is inspected before selection; afterwards only messages
    // resolving to a selected chat are counted (see Engine.ingest).
    const apply = (kind, raw, opts) => {
      if (!engine.ingestionEnabled) return;
      if (engine.ingest(kind, raw, opts).ok) changed();
    };
    // message_create includes messages sent manually on another linked device.
    on('message_create', msg => apply('new', msg));
    on('message_edit', (msg, newBody) => apply('edit', msg, { text: newBody }));
    on('message_revoke_everyone', msg => apply('delete_everyone', msg));
    on('message_revoke_me', msg => apply('delete_me', msg));
    for (const [event, metric] of [['ready', 'ready'], ['disconnected', 'disconnected'], ['auth_failure', 'authFailure']]) {
      on(event, () => { engine.state.connection[metric]++; changed(); });
    }
  }
  async checkListing() {
    await this.client.readOnly.catalog({ probeOnly: true, diagnostic: this.diagnostic });
  }
  async list() {
    const chats = (await this.client.readOnly.catalog({ diagnostic: this.diagnostic }))
      .filter(c => supportedChat(c.id));
    this.engine.state.catalog = { chats: chats.length, groups: chats.filter(c => c.isGroup).length,
      individual: chats.filter(c => !c.isGroup).length };
    return chats;
  }
  async history(id, limit) {
    if (!this.active) throw Error('INACTIVE_SESSION');
    if (!this.engine.ingestionEnabled || !this.engine.state.selected.includes(id)) throw Error('NOT_SELECTED');
    if (!Number.isInteger(limit) || limit < 1 || limit > 5000) throw Error('INVALID_LIMIT');
    const start = performance.now(), baseline = this.engine.revision, ingestion = emptyCounters();
    let messages = [];
    try {
      messages = await this.client.readOnly.history(id, limit);
      if (!this.active) throw Error('INACTIVE_SESSION');
      for (const raw of messages) this.engine.ingest('history', raw, { baseline, requested: id, counters: ingestion });
      const times = messages.map(m => m.timestamp).filter(Number.isFinite);
      this.engine.historyResult(id, { requested: limit, returned: messages.length, newlyRetained: ingestion.retained,
        oldestAgeDays: times.length ? Math.floor((Date.now() / 1000 - Math.min(...times)) / 86400) : null,
        spanDays: times.length ? Math.floor((Math.max(...times) - Math.min(...times)) / 86400) : null,
        durationMs: Math.round(performance.now() - start), ingestion, ok: true });
    } catch (error) {
      // Fetched but never processed (inactive session, capacity): received, not discarded silently.
      ingestion.unprocessed = messages.length - ingestion.processed;
      ingestion.received = messages.length;
      this.engine.historyResult(id, { requested: limit, returned: messages.length,
        newlyRetained: ingestion.retained, durationMs: Math.round(performance.now() - start), ingestion, ok: false });
      throw Error('HISTORY_FAILED');
    }
  }
  dispose() { this.active = false; for (const [event, handler] of this.handlers) this.client.off(event, handler); }
}
