import { lstatSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { Engine } from './core.mjs';
import { Store } from './store.mjs';
import { LiveSession } from './session.mjs';
import { realClient } from './live.mjs';
import { diagnosticLogger, setupStep } from './diagnostics.mjs';

function requireProfile(root) {
  // Metadata only. Never open Local State, Preferences, databases, caches or snapshots.
  try {
    for (const part of ['', 'auth', 'auth/session-readonly-poc']) {
      const stat = lstatSync(join(root, part));
      if (stat.isSymbolicLink() || !stat.isDirectory()) throw Error();
    }
    const marker = lstatSync(join(root, '.arquivio-wa-poc'));
    if (marker.isSymbolicLink() || !marker.isFile()) throw Error();
  } catch { throw Error('EXISTING_SESSION_REQUIRED'); }
}

// Human-run, existing authorized session only. No interactive authorization or selection.
export async function runDiagnosis({ args = process.argv.slice(3), input = process.stdin, output = process.stdout,
  home = process.env.ARQUIVIO_WA_POC_HOME || join(homedir(), '.local', 'share', 'arquivio-whatsapp-poc'),
  createStore = root => new Store(root), makeClient = realClient, log = text => console.log(text),
  signals = process, readyTimeoutMs = 180_000 } = {}) {
  if (args.length) throw Error('INVALID_DIAGNOSIS_OPTIONS');
  if (!input.isTTY || !output.isTTY) throw Error('DIAGNOSIS_REQUIRES_TTY');
  const diagnostic = diagnosticLogger(log), root = join(resolve(home), 'real');
  await setupStep(diagnostic, 'session_profile', () => requireProfile(root));
  const store = createStore(root);
  let session, timer, listed = false, expired = false;
  const stop = () => session?.stop();
  store.lock();
  try {
    log('Diagnóstico da sessão já autorizada: capacidade, enumeração e projeção mínima; sem exibir conversas, selecionar ou ingerir.');
    log('Sem novo vínculo. Se a sessão pedir QR, o diagnóstico encerra. Auth/cache e biblioteca serão preservados.');
    // Fresh, disabled in-memory engine. Do not load/save any existing private state.
    const engine = new Engine({ mode: 'real' }); engine.beginRun({ durationMinutes: 3 });
    session = new LiveSession({ engine, makeClient: () => makeClient(store, { reuseOnly: true }), diagnostic,
      reuseOnly: true, readyTimeoutMs,
      onReady: async (adapter, signal) => {
        await setupStep(diagnostic, 'list_chats', () => adapter.checkListing());
        if (signal.aborted) return;
        listed = true; session.stop();
      } });
    signals.once('SIGINT', stop); signals.once('SIGTERM', stop);
    // Also bounds catalog probes after ready; the ready-only timer no longer applies then.
    timer = setTimeout(() => { expired = true; stop(); }, readyTimeoutMs);
    const status = await session.run();
    const outcome = expired ? 'DIAGNOSIS_TIMEOUT' : listed && status === 'STOPPED' ? 'SETUP_DIAGNOSED'
      : status === 'STOPPED' ? 'DIAGNOSIS_INTERRUPTED' : status;
    log(outcome);
    return outcome;
  } finally {
    clearTimeout(timer);
    session?.stop(); signals.off('SIGINT', stop); signals.off('SIGTERM', stop);
    store.unlock();
  }
}
