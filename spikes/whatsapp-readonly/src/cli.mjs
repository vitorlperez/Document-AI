import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { Engine, normalize } from './core.mjs';
import { Store } from './store.mjs';
import { runLive } from './live.mjs';

process.umask(0o077);
const command = process.argv[2];
const base = process.env.ARQUIVIO_WA_POC_HOME || join(homedir(), '.local', 'share', 'arquivio-whatsapp-poc');
const dataPath = mode => join(resolve(base), mode);


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

try {
  if (command === 'demo') await demo();
  else if (command === 'doctor') await doctor();
  else if (command === 'live') {
    const status = await runLive();
    if (!['STOPPED', 'CANCELLED', 'RUNTIME_LIMIT'].includes(status)) process.exitCode = 1;
  }
  else if (command === 'report') {
    const mode = process.argv.includes('--real') ? 'real' : 'simulated';
    const s = new Store(dataPath(mode)); s.lock();
    try { const snapshot = s.load(); if (!snapshot) throw Error('NO_LOCAL_RUN'); console.log(JSON.stringify(new Engine({ mode, snapshot }).report(), null, 2)); }
    finally { s.unlock(); }
  } else { console.log('Uso: npm test | npm run demo | npm run doctor | npm run live -- --consent --duration-minutes 90 | npm run report -- --real'); process.exitCode = 2; }
} catch (error) {
  const safe = new Set(['LIVE_REQUIRES_TTY_AND_CONSENT', 'OUTSIDE_GIT_REQUIRED', 'ALREADY_RUNNING',
    'DEDICATED_DIRECTORY_REQUIRED', 'UNSAFE_FILE', 'NO_LOCAL_RUN', 'INCOMPATIBLE_STATE', 'INVALID_SELECTION']);
  const diagnostics = {
    INVALID_DURATION_OPTIONS: 'INVALID_DURATION_OPTIONS: use --duration-minutes 1..120 (padrão 60), uma única vez.',
    ALREADY_RUNNING: 'ALREADY_RUNNING: PID do lock ainda existe ou não pôde ser verificado; nenhuma recuperação executada. Feche o processo antes de repetir.',
    LOCK_OWNER_UNKNOWN: 'LOCK_OWNER_UNKNOWN: PID ausente/inválido. Não removido; consulte recuperação manual no README.',
    LOCK_RECOVERY_BUSY: 'LOCK_RECOVERY_BUSY: outra aquisição/recuperação em curso ou guard órfão. Não removido; repita após encerrar, ou consulte README.'
  };
  console.error(diagnostics[error.message] ?? (safe.has(error.message) ? error.message : 'POC_FAILED: diagnóstico bruto suprimido para proteger a sessão. Confira instalação/Chromium e README.'));
  process.exitCode = 1;
}
