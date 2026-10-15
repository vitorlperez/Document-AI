import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { Engine, chooseChats } from './core.mjs';
import { Store } from './store.mjs';
import { LiveSession } from './session.mjs';
import { diagnosticLogger, setupStep } from './diagnostics.mjs';
import { createWebReader } from './web-reader.mjs';

const cleanName = s => String(s || '(sem nome)').replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, '').slice(0, 100);

export function durationMinutes(args) {
  let duration = 60, seen = false;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '--consent') continue;
    if (args[i] !== '--duration-minutes' || seen || !/^[1-9]\d*$/.test(args[i + 1] ?? '')) throw Error('INVALID_DURATION_OPTIONS');
    seen = true; duration = Number(args[++i]);
    if (!Number.isInteger(duration) || duration > 120) throw Error('INVALID_DURATION_OPTIONS');
  }
  return duration;
}

export async function realClient(store, { reuseOnly = false } = {}) {
  const { default: wweb } = await import('whatsapp-web.js');
  const authStrategy = new wweb.LocalAuth({ clientId: 'readonly-poc', dataPath: store.directory('auth') });
  // Server logout must not rm the already linked profile, in live or diagnosis.
  // Revocation can still invalidate server auth; preserving disk cannot undo it.
  authStrategy.logout = async () => {};
  if (reuseOnly) {
    // Client.inject consults this before registering QR callbacks. Fail closed.
    authStrategy.onAuthenticationNeeded = async () => ({ failed: true, restart: false });
  }
  const client = new wweb.Client({
    authStrategy,
    webVersionCache: { type: 'local', path: store.directory('web-cache') },
    puppeteer: { headless: false, dumpio: false },
    qrMaxRetries: 5, takeoverOnConflict: false, authTimeoutMs: 120_000,
    deviceName: 'ArquivIO POC somente leitura'
  });
  // Local read contract, separate from the dependency's full chat serializers.
  client.readOnly = createWebReader(client, wweb.Chat);
  return client;
}

// Injection is programmatic for offline tests; the CLI always uses these defaults.
export async function runLive({ args = process.argv.slice(3), input = process.stdin, output = process.stdout,
  home = process.env.ARQUIVIO_WA_POC_HOME || join(homedir(), '.local', 'share', 'arquivio-whatsapp-poc'),
  createPrompt = () => createInterface({ input, output }), createStore = path => new Store(path),
  makeClient = realClient, log = text => console.log(text), signals = process,
  setTimer = setTimeout, clearTimer = clearTimeout } = {}) {
  if (!args.includes('--consent') || !input.isTTY || !output.isTTY) throw Error('LIVE_REQUIRES_TTY_AND_CONSENT');
  const minutes = durationMinutes(args);
  const rl = createPrompt();
  const diagnostic = diagnosticLogger(log);
  let session, store, engine, active, commands, timer, outcome = 'LOCAL_RUN_FAILED', cancelled = false, expired = false;
  const stop = () => { session?.stop(); rl.close(); };
  try {
    log('Cliente NÃO OFICIAL. Pode haver bloqueio da conta e quebra sem aviso. Nenhum envio será feito pela POC.');
    log('A sessão vinculada recebe/cacheia dados da conta inteira no perfil local do Chromium. A seleção limita apenas a biblioteca da POC.');
    log('Nomes de chats aparecerão somente neste terminal local. Não grave/compartilhe a tela. O QR ficará só no navegador local.');
    log('Feche outras instâncias da POC. Use a conta já autorizada e conversas com participantes cientes; uma conta de teste é opcional.');
    log(`Limite desta execução: ${minutes} min, incluindo vínculo e seleção (máximo permitido: 120 min).`);
    if (await rl.question('Para abrir WhatsApp Web (reutiliza a sessão existente), digite VINCULAR: ') !== 'VINCULAR') return 'CANCELLED';
    store = createStore(join(resolve(home), 'real')); store.lock();
    if (store.recoveredLock || store.recoveredTemps?.length) log('RECOVERED_LOCAL_RUN: PID anterior encerrado; temporários conhecidos descartados sob lock. Snapshot confirmado preservado.');
    engine = new Engine({ mode: 'real', snapshot: store.load() });
    const previousCount = engine.state.selected.length;
    engine.beginRun({ durationMinutes: minutes });
    // Gate is in memory, separate from retained snapshots/evidence. Persist even
    // before selection so cancellation and connection counters have provenance.
    const save = () => store.save(engine);
    save();
    let selected = false;
    session = new LiveSession({ engine, changed: save, makeClient: () => makeClient(store), diagnostic,
      onReady: async (adapter, signal) => {
        active = adapter;
        if (!selected) {
          const chats = await setupStep(diagnostic, 'list_chats', () => adapter.list());
          if (signal.aborted) return;
          log(`Conversas disponíveis: ${chats.length}. Seleção anterior NÃO será retomada automaticamente (${previousCount}).`);
          chats.forEach((c, i) => log(`${i + 1}. [${c.isGroup ? 'grupo' : 'chat'}] ${cleanName(c.name)}`));
          const answer = await setupStep(diagnostic, 'selection', () =>
            rl.question('Escolha apenas índices, separados por vírgula (vazio cancela): ', { signal }));
          if (signal.aborted) return;
          if (!answer.trim()) { cancelled = true; session.stop(); return; }
          const ids = chooseChats(answer, chats);
          log(`Serão sincronizadas ${ids.length} conversas; textos serão gravados somente na biblioteca privada local.`);
          const confirmation = await setupStep(diagnostic, 'confirmation', () =>
            rl.question('Para autorizar esta seleção, digite SINCRONIZAR: ', { signal }));
          if (signal.aborted) return;
          if (confirmation !== 'SINCRONIZAR') { cancelled = true; session.stop(); return; }
          engine.select(ids); selected = true; save();
          ids.forEach(id => log(`${engine.alias(id)}: ${cleanName(chats.find(c => c.id === id)?.name)}`));
        }
        for (const id of engine.state.selected) {
          if (signal.aborted) return;
          try { await adapter.history(id, 200); } catch { log('HISTORY_FAILED: consulte métricas; histórico não validado.'); }
        }
        if (signal.aborted) return;
        save(); log('Sincronização local ativa. Comandos: stats | history 500 | check new pass | quit');
        if (!commands) commands = (async () => {
          for await (const line of rl) {
            const [op, a, b] = line.trim().split(/\s+/);
            try {
              if (op === 'quit') { session.stop(); break; }
              else if (op === 'stats') log(JSON.stringify(engine.report(), null, 2));
              else if (op === 'history' && /^[1-9]\d*$/.test(a || '') && Number(a) <= 5000) {
                for (const id of engine.state.selected) await active.history(id, Number(a)); save();
                log('Consulta concluída. Use stats para contagens.');
              } else if (op === 'check') { engine.observe(a, b); save(); log('Observação humana registrada; não é prova automática.'); }
              else log('Comando inválido. stats | history 1..5000 | check cenário pass/fail | quit');
            } catch { log('COMMAND_FAILED: nenhuma informação privada foi registrada no diagnóstico.'); }
          }
          session.stop();
        })().catch(() => { log('LOCAL_INPUT_CLOSED'); session.stop(); });
      }
    });
    signals.once('SIGINT', stop); signals.once('SIGTERM', stop);
    timer = setTimer(() => { expired = true; log('RUNTIME_LIMIT: encerrando e preservando evidências.'); stop(); }, minutes * 60_000);
    const status = await session.run();
    outcome = expired ? 'RUNTIME_LIMIT' : cancelled ? 'CANCELLED' : status;
    log(outcome);
    return outcome;
  } finally {
    if (timer !== undefined) clearTimer(timer);
    session?.stop(); rl.close();
    signals.off('SIGINT', stop); signals.off('SIGTERM', stop);
    try { if (engine) { engine.endRun(outcome); store.save(engine); } }
    finally { store?.unlock(); }
  }
}
