// npm install --prefix /tmp/document-ai-onboarding-tools --no-save playwright tsx
// Start qa-server.py and the source frontend as documented in qa-server.py.
// NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/onboarding/browser-check.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const output = path.join(__dirname, 'qa', 'fixed');
fs.mkdirSync(output, { recursive: true });
const checks = new Set((process.env.CHECK_ITEMS ?? 'F-001,F-002,F-003,F-004').split(','));
const check = (id, fn) => checks.has(id) ? fn() : undefined;

(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const results = [];
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error' && message.text().includes('Encountered two children')) errors.push(message.text()); });
    const httpErrors = [];
    page.on('response', response => {
      const url = new URL(response.url());
      if (url.port === '8011' && url.pathname !== '/me' && response.status() >= 400) httpErrors.push({ path: url.pathname, status: response.status() });
    });
    await page.goto('http://localhost:5173/login');
    await page.getByRole('button', { name: 'Criar uma conta', exact: true }).click();
    await page.getByLabel('Nome da organização').fill(`QA onboarding ${width}`);
    await page.getByRole('button', { name: 'Criar organização', exact: true }).click();
    await page.getByRole('heading', { name: 'Boas-vindas ao Arquivio', exact: true }).waitFor();
    const org = new URL(page.url()).pathname.split('/')[2];
    const state = async () => {
      const response = await context.request.get(`http://localhost:8011/organizations/${org}/onboarding`);
      assert.equal(response.status(), 200);
      return response.json();
    };
    const fit = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await fit();
    await page.screenshot({ path: path.join(output, `welcome-${width}.png`), fullPage: true });
    {
      await page.getByRole('button', { name: 'Vamos começar', exact: true }).click();
      await page.getByRole('heading', { name: 'Traga o conhecimento da sua equipe', exact: true }).waitFor();
      assert.equal((await state()).step, 'integrations');
      await page.reload();
      await page.getByRole('heading', { name: 'Traga o conhecimento da sua equipe', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Voltar', exact: true }).click();
      await page.getByRole('heading', { name: 'Boas-vindas ao Arquivio', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Vamos começar', exact: true }).click();
      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({ path: path.join(output, `integrations-first-fold-${width}.png`) });
      await check('F-001', async () => {
        if (width !== 390) return;
        for (const name of ['Voltar', 'Conectar depois', 'Ir para a conversa']) {
          const bounds = await page.getByRole('button', { name, exact: true }).boundingBox();
          assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= page.viewportSize().height, `F-001: ${name} must fit first fold`);
        }
      });
      await page.getByRole('button', { name: 'Conectar', exact: true }).click();
      await page.getByRole('dialog', { name: 'Google Drive', exact: true }).waitFor();
      assert.equal((await state()).step, 'integrations'); // OAuth returns into the pending wizard.
      // Resume setup on the conversation route so finishing it preserves the same ProductApp.
      await page.goto(`http://localhost:5173/companies/${org}`);
      await page.getByRole('heading', { name: 'Traga o conhecimento da sua equipe', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Gerenciar', exact: true }).last().click();
      const syncDialog = page.getByRole('dialog', { name: 'Google Drive', exact: true });
      await syncDialog.getByRole('checkbox', { name: /Client A/ }).check();
      await syncDialog.getByRole('checkbox', { name: /Confirmo/ }).check();
      const syncResponse = page.waitForResponse(response => /\/workspace-folders\/[^/]+\/sync\?/.test(response.url()) && response.request().method() === 'POST');
      await syncDialog.getByRole('button', { name: /Sincronizar selecionados/ }).click();
      assert.equal((await syncResponse).status(), 202);
      await page.getByText('Sincronização iniciada.', { exact: false }).waitFor();
      const history = await context.request.get(`http://localhost:8011/library/sync-history?organization_id=${org}`);
      const entries = (await history.json()).items;
      assert.equal(entries.length, 1);
      assert.equal(entries[0].status, 'queued');
      await syncDialog.getByRole('button', { name: 'Fechar', exact: true }).click();
      await page.screenshot({ path: path.join(output, `integrations-${width}.png`), fullPage: true });
      await page.getByRole('button', { name: 'Ir para a conversa', exact: true }).click();
    }
    const tour = page.getByRole('dialog', { name: 'Pergunte aos seus documentos', exact: true });
    await tour.waitFor();
    await check('F-002', async () => assert.equal(await page.getByText('Sincronização iniciada.', { exact: false }).count(), 0, 'F-002: sync toast must be dismissed when setup finishes'));
    assert.equal((await state()).required, false);
    for (let index = 0; index < 4; index++) {
      await page.waitForFunction(() => {
        const card = document.querySelector('.tour-card');
        if (!card) return false;
        const rect = card.getBoundingClientRect();
        return rect.top >= 0 && rect.left >= 0 && rect.right <= innerWidth + 1 && rect.bottom <= innerHeight + 1;
      });
      await page.waitForFunction(target => {
        const element = document.querySelector(`[data-tour="${target}"]`);
        const highlight = document.querySelector('.tour-highlight');
        const rect = element?.getBoundingClientRect();
        const marker = highlight?.getBoundingClientRect();
        return rect && marker && Math.abs(marker.top - Math.max(4, rect.top - 5)) < 2 && Math.abs(marker.left - Math.max(4, rect.left - 5)) < 2;
      }, ['composer', 'tools', 'new-conversation', 'navigation'][index]);
      const focused = await page.evaluate(() => document.querySelector('dialog[open]').contains(document.activeElement));
      assert.equal(focused, true);
      if (index === 3) await check('F-004', async () => assert.equal(await page.locator('[data-tour="navigation"]').getByText('Navegar', { exact: true }).isVisible(), true, 'F-004: navigation target needs the label used by the tour'));
      await page.screenshot({ path: path.join(output, `tour-${width}-${index + 1}.png`) });
      await page.getByRole('button', { name: index === 3 ? 'Começar a conversar' : 'Próximo', exact: true }).click();
    }
    await page.locator('dialog[open]').waitFor({ state: 'detached' });
    await page.getByRole('heading', { name: 'O que você quer descobrir?', exact: true }).waitFor();
    const checkScope = async () => assert.equal(await page.evaluate(() => {
      const scope = document.querySelector('.sources-scope');
      if (getComputedStyle(scope).display === 'none') return true;
      const note = scope.getBoundingClientRect();
      const panel = scope.parentElement.getBoundingClientRect();
      return note.top >= panel.top && note.bottom <= panel.bottom + 1;
    }), true, 'F-003: scope note must be entirely visible or hidden on stacked layouts');
    await check('F-003', checkScope);
    await page.screenshot({ path: path.join(output, `chat-${width}.png`) });
    if (width === 390 && checks.has('F-003')) {
      await page.setViewportSize({ width: 768, height: 1024 });
      await checkScope();
      await page.screenshot({ path: path.join(output, 'chat-768.png') });
      await page.setViewportSize({ width, height: 844 });
    }
    assert.equal((await state()).tour_required, false);
    assert.equal(new URL(page.url()).pathname, `/companies/${org}`);
    await page.getByRole('button', { name: 'Sair da conta', exact: true }).click();
    await page.getByRole('button', { name: 'Entrar na minha conta', exact: true }).click();
    await page.getByRole('heading', { name: 'O que você quer descobrir?', exact: true }).waitFor();
    assert.equal(await page.locator('.onboarding-page, dialog[open]').count(), 0);
    assert.equal((await state()).tour_required, false);
    await page.getByRole('button', { name: 'Rever tour do app', exact: true }).click();
    await page.getByRole('dialog').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('dialog[open]').waitFor({ state: 'detached' });
    await page.reload();
    await page.getByRole('heading', { name: 'O que você quer descobrir?', exact: true }).waitFor();
    assert.equal(await page.locator('dialog[open]').count(), 0);
    assert.deepEqual(errors, []);
    assert.deepEqual(httpErrors, []);
    results.push({ width, signupAndOrg: true, welcome: true, skip: false, oauthResumeAndSyncQueued: true, tourSteps: 4, focusTrapped: true, viewportFit: true, secondLoginDirectChat: true, replayAndEscape: true, pageErrors: 0, httpErrors: 0 });
    await context.close();
  }
  fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify(results, null, 2));
  await browser.close();
  console.log('PASS: desktop/mobile signup → organization → welcome/connect-or-skip → chat → 4 coachmarks → logout/login direct chat. OAuth resume, real sync queue/history, replay, Escape, focus and viewport checks passed.');
})().catch(error => { console.error(error); process.exit(1); });
