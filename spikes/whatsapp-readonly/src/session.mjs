import { ReadOnlyConnector, RetryBudget } from './connector.mjs';
import { setTimeout as delay } from 'node:timers/promises';

export class LiveSession {
  constructor({ makeClient, engine, onReady = async () => {}, changed = () => {},
    delay: sleep = delay, readyTimeoutMs = 180_000 }) {
    Object.assign(this, { makeClient, engine, onReady, changed, sleep, readyTimeoutMs });
    this.stopped = false; this.retry = new RetryBudget();
  }
  stop() { this.stopped = true; this.wake?.({ type: 'stop' }); }
  async run() {
    while (!this.stopped) {
      const client = await this.makeClient();
      const adapter = new ReadOnlyConnector(client, this.engine, {
        changed: this.changed, failed: () => { this.failure = 'EVENT_PERSISTENCE_FAILED'; this.stop(); } });
      const setup = new AbortController();
      let readyTimer;
      let readyResolve, endResolve;
      const ready = new Promise(r => { readyResolve = r; });
      const ended = new Promise(r => { endResolve = r; });
      const wake = event => { readyResolve(event); endResolve(event); };
      this.wake = wake;
      const onReady = () => readyResolve({ type: 'ready' });
      const onDisconnect = reason => wake({ type: 'disconnect', reason });
      const onAuth = () => wake({ type: 'auth' });
      client.once('ready', onReady); client.once('disconnected', onDisconnect); client.once('auth_failure', onAuth);
      readyTimer = setTimeout(() => wake({ type: 'timeout' }), this.readyTimeoutMs);
      let result;
      try {
        Promise.resolve().then(() => client.initialize()).catch(() => wake({ type: 'init_error' }));
        result = await ready; clearTimeout(readyTimer);
        if (result.type === 'ready') {
          result = await Promise.race([Promise.resolve(this.onReady(adapter, setup.signal)).then(() => null), ended]);
          if (!result) result = this.stopped ? { type: 'stop' } : await ended;
        }
      } catch { result = { type: 'setup_error' }; }
      finally {
        clearTimeout(readyTimer); setup.abort(); adapter.dispose(); this.wake = undefined;
        client.off('ready', onReady); client.off('disconnected', onDisconnect); client.off('auth_failure', onAuth);
        try { await client.destroy(); } catch { /* no raw browser/session errors in logs */ }
      }
      if (result.type === 'stop') return this.failure || 'STOPPED';
      if (result.type === 'auth') return 'AUTH_REQUIRED';
      if (result.type === 'timeout') return 'READY_TIMEOUT';
      if (result.type !== 'disconnect') return 'LOCAL_SETUP_FAILED';
      const pause = this.retry.next(result.reason);
      if (pause === null) return this.retry.attempts >= 3 ? 'RETRIES_EXHAUSTED' : 'AUTH_REQUIRED';
      this.engine.state.connection.reconnectAttempts++; this.changed();
      await this.sleep(pause);
    }
    return 'STOPPED';
  }
}
