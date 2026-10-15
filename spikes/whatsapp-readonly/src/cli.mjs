import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { Engine, normalize, chooseChats } from './core.mjs';
import { Store } from './store.mjs';
import { LiveSession } from './session.mjs';

process.umask(0o077);
const command = process.argv[2];
const base = process.env.ARQUIVIO_WA_POC_HOME || join(homedir(), '.local', 'share', 'arquivio-whatsapp-poc');
const dataPath = mode => join(resolve(base), mode);
const cleanName = s => String(s || '(sem nome)').replace(/[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]/g, '').slice(0, 100);

async function demo() {
  const fixture = JSON.parse(readFileSync(new URL('../fixtures/scenario.json', import.meta.url)));
  const store = new Store(dataPath('simulated')); store.lock();
  try {
    const e = new Engine({ mode: 'simulated', selected: fixture.selected });
    for (const event of fixture.events) e.apply(event.kind, normalize(event.message, { deletion: event.kind.startsWith('delete') }));
    store.save(e); console.log(JSON.stringify(e.report(), null, 2));
  } finally { store.unlock(); }
}
async function doctor() {
  // Launches only about:blank. No WhatsApp URL/client initialization or auth access.
  const { default: wweb } = await import('whatsapp-web.js');
  const { createRequire } = await import('node:module');
  const require = createRequire(import.meta.url);
  const puppeteer = require(require.resolve('puppeteer', { paths: [require.resolve('whatsapp-web.js')] }));
  const browser = await puppeteer.launch({ headless: true, dumpio: false });
  try {
    const page = await browser.newPage(); await page.goto('about:blank');
    console.log(JSON.stringify({ node: process.version, library: 'whatsapp-web.js@1.34.7',
      clientImport: typeof wweb.Client === 'function', chromiumLaunch: true,
      chromiumVersion: await browser.version(), whatsappConnected: false }));
  } finally { await browser.close(); }
}
async function live() {
  if (!process.argv.includes('--consent') || !process.stdin.isTTY || !process.stdout.isTTY) throw Error('LIVE_REQUIRES_TTY_AND_CONSENT');
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  let session, store, engine, active, commands;
  const stop = () => { session?.stop(); rl.close(); };
  try {
    console.log('Cliente NÃO OFICIAL. Pode haver bloqueio da conta e quebra sem aviso. Nenhum envio será feito pela POC.');
    console.log('A sessão vinculada recebe/cacheia dados da conta inteira no perfil local do Chromium. A seleção limita apenas a biblioteca da POC.');
    console.log('Nomes de chats aparecerão somente neste terminal local. Não grave/compartilhe a tela. O QR ficará só no navegador local.');
    console.log('Feche outras instâncias da POC. Use uma conta de teste e conversas com participantes cientes.');
    if (await rl.question('Para abrir WhatsApp Web e vincular conscientemente, digite VINCULAR: ') !== 'VINCULAR') return;
    store = new Store(dataPath('real')); store.lock();
    engine = new Engine({ mode: 'real', snapshot: store.load() });
    // No ingestion on restart until a fresh explicit selection. Keep prior snapshot in memory until selection.
    const previous = engine.state.selected; engine.state.selected = [];
    const { default: wweb } = await import('whatsapp-web.js');
    let selected = false;
    const save = () => { if (selected) store.save(engine); };
    session = new LiveSession({ engine, changed: save,
      makeClient: async () => new wweb.Client({
        authStrategy: new wweb.LocalAuth({ clientId: 'readonly-poc', dataPath: store.directory('auth') }),
        webVersionCache: { type: 'local', path: store.directory('web-cache') },
        puppeteer: { headless: false, dumpio: false },
        qrMaxRetries: 5, takeoverOnConflict: false, authTimeoutMs: 120_000,
        deviceName: 'ArquivIO POC somente leitura'
      }),
      onReady: async (adapter, signal) => {
        active = adapter;
        if (!selected) {
          const chats = await adapter.list();
          if (signal.aborted) return;
          console.log(`Conversas disponíveis: ${chats.length}. Seleção anterior NÃO será retomada automaticamente (${previous.length}).`);
          chats.forEach((c, i) => console.log(`${i + 1}. [${c.isGroup ? 'grupo' : 'chat'}] ${cleanName(c.name)}`));
          const ids = chooseChats(await rl.question('Escolha apenas índices, separados por vírgula (vazio cancela): ', { signal }), chats);
          console.log(`Serão sincronizadas ${ids.length} conversas; textos serão gravados somente na biblioteca privada local.`);
          if (await rl.question('Para autorizar esta seleção, digite SINCRONIZAR: ', { signal }) !== 'SINCRONIZAR') { session.stop(); return; }
          if (signal.aborted) return;
          engine.select(ids); selected = true;
          ids.forEach((id, index) => console.log(`chat-${index + 1}: ${cleanName(chats.find(c => c.id === id)?.name)}`));
        }
        for (const id of engine.state.selected) {
          try { await adapter.history(id, 200); } catch { console.log('HISTORY_FAILED: consulte métricas; histórico não validado.'); }
        }
        if (signal.aborted) return;
        save(); console.log('Sincronização local ativa. Comandos: stats | history 500 | check new pass | quit');
        if (!commands) commands = (async () => {
          for await (const line of rl) {
            const [op, a, b] = line.trim().split(/\s+/);
            try {
              if (op === 'quit') { session.stop(); break; }
              else if (op === 'stats') console.log(JSON.stringify(engine.report(), null, 2));
              else if (op === 'history' && /^[1-9]\d*$/.test(a || '') && Number(a) <= 5000) {
                for (const id of engine.state.selected) await active.history(id, Number(a)); save();
                console.log('Consulta concluída. Use stats para contagens.');
              } else if (op === 'check') { engine.observe(a, b); save(); console.log('Observação humana registrada; não é prova automática.'); }
              else console.log('Comando inválido. stats | history 1..5000 | check cenário pass/fail | quit');
            } catch { console.log('COMMAND_FAILED: nenhuma informação privada foi registrada no diagnóstico.'); }
          }
          session.stop();
        })().catch(() => { console.log('LOCAL_INPUT_CLOSED'); session.stop(); });
      }
    });
    process.once('SIGINT', stop); process.once('SIGTERM', stop);
    const maxRuntime = setTimeout(stop, 30 * 60_000);
    try { const status = await session.run(); save(); console.log(status); if (status !== 'STOPPED') process.exitCode = 1; }
    finally { clearTimeout(maxRuntime); }
  } finally {
    session?.stop(); rl.close(); store?.unlock();
    process.off('SIGINT', stop); process.off('SIGTERM', stop);
  }
}

try {
  if (command === 'demo') await demo();
  else if (command === 'doctor') await doctor();
  else if (command === 'live') await live();
  else if (command === 'report') {
    const mode = process.argv.includes('--real') ? 'real' : 'simulated';
    const s = new Store(dataPath(mode)); s.lock();
    try { const snapshot = s.load(); if (!snapshot) throw Error('NO_LOCAL_RUN'); console.log(JSON.stringify(new Engine({ mode, snapshot }).report(), null, 2)); }
    finally { s.unlock(); }
  } else { console.log('Uso: npm test | npm run demo | npm run doctor | npm run live -- --consent | npm run report -- --real'); process.exitCode = 2; }
} catch (error) {
  const safe = new Set(['LIVE_REQUIRES_TTY_AND_CONSENT', 'OUTSIDE_GIT_REQUIRED', 'ALREADY_RUNNING',
    'DEDICATED_DIRECTORY_REQUIRED', 'UNSAFE_FILE', 'NO_LOCAL_RUN', 'INCOMPATIBLE_STATE', 'INVALID_SELECTION']);
  console.error(safe.has(error.message) ? error.message : 'POC_FAILED: diagnóstico bruto suprimido para proteger a sessão. Confira instalação/Chromium e README.');
  process.exitCode = 1;
}
