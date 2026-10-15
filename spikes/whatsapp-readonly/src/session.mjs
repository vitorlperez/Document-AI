import { ReadOnlyConnector, RetryBudget } from './connector.mjs';
import { setTimeout as delay } from 'node:timers/promises';
import { safeDiagnostic, setupStep } from './diagnostics.mjs';

export class LiveSession {
  constructor({ makeClient, engine, onReady = async () => {}, changed = () => {},
    delay: sleep = delay, readyTimeoutMs = 180_000, diagnostic = () => {}, reuseOnly = false }) {
    Object.assign(this, { makeClient, engine, onReady, changed, sleep, readyTimeoutMs, diagnostic, reuseOnly });
    this.stopped = false; this.retry = new RetryBudget();
  }
  stop() { this.stopped = true; this.wake?.({ type: 'stop' }); }
  async run() {
    while (!this.stopped) {
      let client;
      try { client = await setupStep(this.diagnostic, 'make_client', this.makeClient); }
      catch { return 'LOCAL_SETUP_FAILED'; }
      const adapter = new ReadOnlyConnector(client, this.engine, {
        changed: this.changed, failed: () => { this.failure = 'EVENT_PERSISTENCE_FAILED'; this.stop(); } });
      const setup = new AbortController();
      let readyTimer;
      let readyResolve, endResolve;
      const ready = new Promise(r => { readyResolve = r; });
      const ended = new Promise(r => { endResolve = r; });
      const wake = event => { readyResolve(event); endResolve(event); };
      this.wake = wake;
      const onReady = () => { this.diagnostic(safeDiagnostic('ready', 'reached')); readyResolve({ type: 'ready' }); };
      const onDisconnect = reason => wake({ type: 'disconnect', reason });
      const onAuth = () => wake({ type: 'auth' });
      const onAuthenticated = () => this.diagnostic(safeDiagnostic('authenticated', 'reached'));
      const onQR = () => { this.diagnostic(safeDiagnostic('reuse_auth', 'failed')); wake({ type: 'auth' }); };
      client.once('ready', onReady); client.once('disconnected', onDisconnect); client.once('auth_failure', onAuth);
      client.on('authenticated', onAuthenticated);
      if (this.reuseOnly) client.on('qr', onQR);
      readyTimer = setTimeout(() => wake({ type: 'timeout' }), this.readyTimeoutMs);
      let result, activeAttempt = true;
      try {
        this.diagnostic(safeDiagnostic('initialize', 'started'));
        Promise.resolve().then(() => client.initialize()).catch(error => {
          if (!activeAttempt) return;
          this.diagnostic(safeDiagnostic('initialize', 'failed', error));
          wake({ type: 'init_error' });
        });
        result = await ready; clearTimeout(readyTimer);
        if (result.type === 'ready') {
          result = await Promise.race([Promise.resolve(this.onReady(adapter, setup.signal)).then(() => null), ended]);
          if (!result) result = this.stopped ? { type: 'stop' } : await ended;
        }
      } catch (error) {
        this.diagnostic(safeDiagnostic('setup_callback', 'failed', error));
        result = { type: 'setup_error' };
      }
      finally {
        activeAttempt = false;
        clearTimeout(readyTimer); setup.abort(); adapter.dispose(); this.wake = undefined;
        client.off('ready', onReady); client.off('disconnected', onDisconnect); client.off('auth_failure', onAuth);
        client.off('authenticated', onAuthenticated); client.off('qr', onQR);
        try { await client.destroy(); }
        catch (error) { this.diagnostic(safeDiagnostic('destroy', 'failed', error)); }
      }
      if (result.type === 'stop') return this.failure || 'STOPPED';
      if (result.type === 'auth') return 'AUTH_REQUIRED';
      if (result.type === 'timeout') return 'READY_TIMEOUT';
      if (result.type !== 'disconnect') return 'LOCAL_SETUP_FAILED';
      if (this.reuseOnly) return 'DISCONNECTED'; // Diagnosis is one attempt, never automatic reauthorization/retry.
      const pause = this.retry.next(result.reason);
      if (pause === null) return this.retry.attempts >= 3 ? 'RETRIES_EXHAUSTED' : 'AUTH_REQUIRED';
      this.engine.state.connection.reconnectAttempts++; this.changed();
      await this.sleep(pause);
    }
    return 'STOPPED';
  }
}
