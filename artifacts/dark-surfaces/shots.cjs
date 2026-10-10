// NODE_PATH=/private/tmp/pw/node_modules node shots.cjs <label>   (browser-local API fixtures, app at :3000)
const { chromium } = require('playwright-core');
const label = process.argv[2] || 'after';
const org = '11111111-1111-4111-8111-111111111111';
const base = 'http://localhost:3000';
const providers = ['google_drive', 'onedrive', 'sharepoint', 'notion', 'clickup'];
const sources = providers.map((provider, i) => ({ id: String(i + 1), provider, status: 'connected', account_email: 'equipe@exemplo.com' }));
const items = [
  ...['Contratos', 'Financeiro 2026', 'Jurídico'].map((name, i) => ({ id: 'f' + i, parent_id: null, source_id: '1', source_provider: 'google_drive', kind: 'folder', name, mime_type: null, children_count: 4 })),
  ...['Proposta.pdf', 'Orçamento.xlsx'].map((name, i) => ({ id: 'd' + i, parent_id: null, source_id: '1', source_provider: 'google_drive', kind: 'file', name, mime_type: 'application/pdf', status: 'Indexado' })),
];
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  for (const theme of ['dark', 'light']) {
    const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    await ctx.addInitScript(t => { try { localStorage.setItem('arquivio-theme', t); } catch {} }, theme);
    const page = await ctx.newPage();
    await page.route('**/api/**', route => {
      const p = new URL(route.request().url()).pathname.replace(/^\/api/, '');
      let json = [];
      if (p === '/me' || p === '/session') json = { id: org, email: 'qa@example.com' };
      else if (p === '/organizations') json = [{ id: org, name: 'Equipe QA', membership_id: org, role: 'owner' }];
      else if (/onboarding/.test(p)) json = { step: 'done', required: false, tour_required: false };
      else if (p === '/data-sources') json = sources;
      else if (/sync-history/.test(p)) json = { items: [] };
      else if (/scope-catalog/.test(p)) json = { folders: [{ id: 'c1', name: 'Contratos', path: 'Contratos' }], root_files: { available: true, label: 'Arquivos da raiz' }, all_accessible: { available: true, label: 'Todo o conteúdo' } };
      else if (/library|nodes|items/.test(p)) json = { items, page: 1, pages: 1, total: items.length };
      return route.fulfill({ json });
    });
    await page.goto(`${base}/companies/${org}/integrations`);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${label}-integrations-${theme}.png` });
    await page.goto(`${base}/companies/${org}/library`);
    await page.waitForTimeout(2500);
    await page.screenshot({ path: `${label}-library-${theme}.png` });
    await page.locator('aside[aria-label="Ferramentas integradas"] button').filter({ hasText: 'Contratos' }).first().click().catch(() => {});
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${label}-library-tool-${theme}.png` });
    await page.getByRole('button', { name: 'Sincronizações', exact: true }).first().click().catch(() => {});
    await page.waitForTimeout(800);
    await page.screenshot({ path: `${label}-library-panel-${theme}.png` });
    await page.goto(`${base}/companies/${org}/integrations`);
    await page.waitForTimeout(1500);
    await page.getByRole('button', { name: 'Gerenciar' }).first().click().catch(() => {});
    await page.waitForTimeout(1000);
    await page.screenshot({ path: `${label}-integrations-modal-${theme}.png` });
    await ctx.close();
  }
  await browser.close();
})();
