// npm install --prefix /tmp/document-ai-onboarding-tools --no-save playwright tsx
// Start qa-server.py and the source frontend as documented in qa-server.py.
// NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/onboarding/browser-check.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const apiBase = process.env.QA_API_URL ?? 'http://localhost:8011';
const appBase = process.env.QA_APP_URL ?? 'http://localhost:5173';
const fs = require('node:fs');
const path = require('node:path');
const output = path.join(__dirname, 'qa', 'fixed');
fs.mkdirSync(output, { recursive: true });
const checks = new Set((process.env.CHECK_ITEMS ?? 'F-001,F-002,F-003,F-004,F-005,F-006').split(','));
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
      if (url.origin === new URL(apiBase).origin && url.pathname !== '/me' && response.status() >= 400) httpErrors.push({ path: url.pathname, status: response.status() });
    });
    await page.goto(`${appBase}/login`);
    await page.getByRole('button', { name: 'Criar uma conta', exact: true }).click();
    await page.getByLabel('Nome da organização').fill(`QA onboarding ${width}`);
    await page.getByRole('button', { name: 'Criar organização', exact: true }).click();
    await page.getByRole('heading', { name: 'Boas-vindas ao Arquivio', exact: true }).waitFor();
    const org = new URL(page.url()).pathname.split('/')[2];
    const state = async () => {
      const response = await context.request.get(`${apiBase}/organizations/${org}/onboarding`);
      assert.equal(response.status(), 200);
      return response.json();
    };
    const fit = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    await fit();
    const alignment = async () => page.evaluate(() => {
      const bounds = selector => {
        const element = document.querySelector(selector);
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        const left = parseFloat(style.paddingLeft), right = parseFloat(style.paddingRight);
        return { x: rect.x + left, width: rect.width - left - right, y: rect.y };
      };
      return { progress: bounds('.onboarding-progress'), title: bounds('.onboarding-intro h1'), actions: bounds('.onboarding-actions') };
    });
    const welcomeAlignment = await alignment();
    await page.screenshot({ path: path.join(output, `welcome-${width}.png`), fullPage: true });
    {
      await page.getByRole('button', { name: 'Vamos começar', exact: true }).click();
      await page.getByRole('heading', { name: 'Traga o conhecimento da sua equipe', exact: true }).waitFor();
      assert.equal((await state()).step, 'integrations');
      await check('F-006', async () => {
        const integrationAlignment = await alignment();
        for (const key of ['progress', 'title', 'actions']) {
          assert.equal(integrationAlignment[key].x, welcomeAlignment[key].x, `F-006: ${key} left edge`);
          assert.equal(integrationAlignment[key].width, welcomeAlignment[key].width, `F-006: ${key} width`);
        }
        assert.equal(integrationAlignment.progress.y, welcomeAlignment.progress.y, 'F-006: stepper vertical position');
        assert.equal(integrationAlignment.title.y, welcomeAlignment.title.y, 'F-006: title vertical position');
      });
      await page.reload();
      await page.getByRole('heading', { name: 'Traga o conhecimento da sua equipe', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Voltar', exact: true }).click();
      await page.getByRole('heading', { name: 'Boas-vindas ao Arquivio', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Vamos começar', exact: true }).click();
      await page.locator('.integration-tool-card').first().waitFor();
      await page.getByText('Carregando fontes conectadas.', { exact: true }).waitFor({ state: 'detached' });
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
      await page.goto(`${appBase}/companies/${org}`);
      await page.getByRole('heading', { name: 'Traga o conhecimento da sua equipe', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Gerenciar', exact: true }).last().click();
      const syncDialog = page.getByRole('dialog', { name: 'Google Drive', exact: true });
      await syncDialog.getByRole('checkbox', { name: /Client A/ }).check();
      await syncDialog.getByRole('checkbox', { name: /Confirmo/ }).check();
      const syncResponse = page.waitForResponse(response => /\/workspace-folders\/[^/]+\/sync\?/.test(response.url()) && response.request().method() === 'POST');
      await syncDialog.getByRole('button', { name: /Sincronizar selecionados/ }).click();
      assert.equal((await syncResponse).status(), 202);
      await page.getByText('Sincronização iniciada.', { exact: false }).waitFor();
      const history = await context.request.get(`${apiBase}/library/sync-history?organization_id=${org}`);
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
    await check('F-005', async () => {
      const message = page.getByText('Sincronização em andamento — as respostas ficam disponíveis conforme a indexação termina.', { exact: true });
      await message.first().waitFor();
      assert.equal(await message.count(), 2, 'F-005: persistent queue status in sidebar and composer');
      assert.equal(await page.getByText('Nenhuma fonte sincronizada.', { exact: true }).count(), 0);
    });
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
    const pendingOrgResponse = await context.request.post(`${apiBase}/organizations`, { data: { name: `Pending owner setup ${width}` } });
    assert.equal(pendingOrgResponse.status(), 201);
    const pendingOrg = (await pendingOrgResponse.json()).id;
    for (const role of ['admin', 'member']) {
      const invited = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } });
      const guest = await invited.newPage();
      guest.setDefaultTimeout(20000);
      guest.on('pageerror', error => errors.push(error.message));
      await guest.goto(`${appBase}/login`);
      await guest.getByRole('button', { name: 'Criar uma conta', exact: true }).click();
      await guest.getByRole('heading', { name: 'Crie sua primeira organização', exact: true }).waitFor();
      const identity = await invited.request.get(`${apiBase}/me`);
      const { email } = await identity.json();
      const invitation = await context.request.post(`${apiBase}/organizations/${pendingOrg}/members/invitations`, { data: { email, role } });
      assert.equal(invitation.status(), 202);
      const outbox = await context.request.get(`${apiBase}/qa/invitations`);
      const invitationURL = (await outbox.json()).findLast(item => item.recipient === email).invitation_url;
      await guest.goto(invitationURL);
      await guest.getByRole('button', { name: 'Aceitar convite', exact: true }).click();
      await guest.getByRole('dialog', { name: 'Pergunte aos seus documentos', exact: true }).waitFor();
      assert.equal(await guest.locator('.onboarding-page').count(), 0, `${role}: no owner setup`);
      assert.equal(await guest.getByRole('heading', { name: 'O que você quer descobrir?', exact: true }).count(), 1);
      const guestState = async () => (await invited.request.get(`${apiBase}/organizations/${pendingOrg}/onboarding`)).json();
      assert.deepEqual(await guestState(), { step: 'welcome', required: false, tour_required: true });
      for (const step of ['integrations', 'complete']) {
        const forbidden = await invited.request.patch(`${apiBase}/organizations/${pendingOrg}/onboarding`, { data: { step } });
        assert.equal(forbidden.status(), 403);
      }
      await guest.screenshot({ path: path.join(output, `invited-${role}-tour-${width}.png`) });
      if (role === 'admin') {
        await guest.getByRole('button', { name: 'Pular tour', exact: true }).click();
      } else {
        for (let index = 0; index < 4; index++) await guest.getByRole('button', { name: index === 3 ? 'Começar a conversar' : 'Próximo', exact: true }).click();
      }
      await guest.locator('dialog[open]').waitFor({ state: 'detached' });
      assert.equal((await guestState()).tour_required, false);
      await guest.getByRole('button', { name: 'Sair da conta', exact: true }).click();
      await guest.getByRole('button', { name: 'Entrar na minha conta', exact: true }).click();
      await guest.getByRole('heading', { name: 'O que você quer descobrir?', exact: true }).waitFor();
      assert.equal(await guest.locator('.onboarding-page, dialog[open]').count(), 0);
      assert.equal((await guestState()).tour_required, false);
      await guest.screenshot({ path: path.join(output, `invited-${role}-second-login-${width}.png`) });
      results.push({ width, role, setupStillPending: true, onlyTour: true, tourSkipped: role === 'admin', secondLoginDirectChat: true });
      await invited.close();
    }
    const ownerState = await context.request.get(`${apiBase}/organizations/${pendingOrg}/onboarding`);
    assert.deepEqual(await ownerState.json(), { step: 'welcome', required: true, tour_required: false });
    assert.deepEqual(errors, []);
    results.push({ width, role: 'owner', signupAndOrg: true, welcome: true, skip: false, oauthResumeAndSyncQueued: true, tourSteps: 4, focusTrapped: true, viewportFit: true, secondLoginDirectChat: true, replayAndEscape: true, pageErrors: 0, httpErrors: 0 });
    const skipping = await browser.newContext({ viewport: { width, height: width === 390 ? 844 : 900 } });
    const skipPage = await skipping.newPage();
    await skipPage.goto(`${appBase}/login`);
    await skipPage.getByRole('button', { name: 'Criar uma conta', exact: true }).click();
    await skipPage.getByLabel('Nome da organização').fill(`Owner skipping ${width}`);
    await skipPage.getByRole('button', { name: 'Criar organização', exact: true }).click();
    await skipPage.getByRole('button', { name: 'Pular introdução', exact: true }).click();
    await skipPage.getByRole('button', { name: 'Pular tour', exact: true }).click();
    await skipPage.locator('dialog[open]').waitFor({ state: 'detached' });
    await skipPage.getByRole('button', { name: 'Sair da conta', exact: true }).click();
    await skipPage.getByRole('button', { name: 'Entrar na minha conta', exact: true }).click();
    await skipPage.getByRole('heading', { name: 'O que você quer descobrir?', exact: true }).waitFor();
    assert.equal(await skipPage.locator('.onboarding-page, dialog[open]').count(), 0);
    results.push({ width, role: 'owner', skipSetupAndTour: true, secondLoginDirectChat: true });
    await skipping.close();
    await context.close();
  }
  fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify(results, null, 2));
  await browser.close();
  console.log('PASS: owner full setup; invited admin/member tour with owner setup pending; all second logins direct chat. Desktop/mobile signup → organization → welcome/connect-or-skip → chat → 4 coachmarks → logout/login direct chat. OAuth resume, real sync queue/history, replay, Escape, focus and viewport checks passed.');
})().catch(error => { console.error(error); process.exit(1); });
