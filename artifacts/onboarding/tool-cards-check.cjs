// NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/onboarding/tool-cards-check.cjs
// Requires the source frontend dev server; all API responses are browser-local fixtures.
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const appBase = process.env.QA_APP_URL ?? 'http://localhost:5173';
const output = process.env.QA_OUTPUT ?? '/tmp/m31-tool-cards-results.json';
const org = '11111111-1111-4111-8111-111111111111';
const providers = ['google_drive', 'onedrive', 'sharepoint', 'notion'];
const account = 'extremely.long.account.identifier.for.card.layout@example.com';

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  const results = [];
  let interactions = 0;
  try {
    for (const status of ['available', 'connected', 'reauth_required', 'disconnected']) {
      for (const width of [1440, 768, 390, 320]) {
        const page = await browser.newPage({ viewport: { width, height: 900 } });
        page.setDefaultTimeout(15000);
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        const sources = status === 'available' ? [] : providers.map((provider, index) => ({
          id: String(index + 1), provider, status, account_email: account,
        }));
        await page.route('**/*', route => {
          const url = new URL(route.request().url());
          const pathname = url.pathname.replace(/^\/api/, '');
          let json;
          if (pathname === '/me' || pathname === '/session') json = { id: org, email: 'qa@example.com' };
          if (pathname === '/organizations') json = [{ id: org, name: 'QA onboarding', membership_id: org, role: 'owner' }];
          if (pathname === `/organizations/${org}/onboarding`) json = { step: 'integrations', required: true, tour_required: true };
          if (pathname === '/data-sources') json = sources;
          if (pathname === '/workspace-folders') json = [];
          if (/\/data-sources\/[^/]+\/scope-catalog/.test(pathname)) json = {
            folders: [], root_files: { available: false, label: '' }, all_accessible: { available: true, label: 'Todo o conteúdo' },
          };
          const headers = {
            'access-control-allow-origin': new URL(appBase).origin,
            'access-control-allow-credentials': 'true',
            'access-control-allow-headers': 'content-type',
            'access-control-allow-methods': 'GET, POST, PATCH, DELETE, OPTIONS',
          };
          if (/\/data-sources\/[^/]+$/.test(pathname) && route.request().method() === 'DELETE') {
            return route.fulfill({ status: 204, headers });
          }
          if (pathname.endsWith('/oauth/start')) return route.fulfill({ body: 'QA authorization redirect', headers });
          return json ? route.fulfill({ json, headers }) : route.continue();
        });
        await page.goto(`${appBase}/companies/${org}/integrations`);
        await page.getByText('SharePoint', { exact: true }).waitFor();
        const metrics = await page.locator('.integration-tool-card').evaluateAll(cards => cards.map(card => {
          const rect = card.getBoundingClientRect();
          const title = card.querySelector('b');
          const description = card.querySelector('.integration-tool-description') ?? card.querySelector('button .text-xs');
          const actions = [...card.querySelectorAll('.integration-tool-actions button')].map(button => ({
            text: button.textContent, height: button.getBoundingClientRect().height,
          }));
          return {
            name: title.textContent, titleOffset: title.getBoundingClientRect().y - rect.y,
            headerHeight: card.querySelector('.integration-tool-header')?.getBoundingClientRect().height,
            descriptionLeft: description?.getBoundingClientRect().x - rect.x,
            titleFont: getComputedStyle(title).fontSize,
            descriptionFont: description && getComputedStyle(description).fontSize,
            descriptionLine: description && getComputedStyle(description).lineHeight,
            actions,
          };
        }));
        const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
        assert.equal(metrics.length, 5);
        assert.ok(scrollWidth <= width, `${status}/${width}: horizontal overflow`);
        assert.ok(Math.max(...metrics.map(item => item.titleOffset)) - Math.min(...metrics.map(item => item.titleOffset)) < 1, `${status}/${width}: title alignment`);
        assert.ok(metrics.every(item => item.descriptionLeft < 24), `${status}/${width}: squeezed descriptions`);
        assert.ok(metrics.every(item => item.titleFont === '14px' && item.descriptionFont === '13px' && item.descriptionLine === '22px'));
        assert.ok(metrics.every(item => item.headerHeight >= 44));
        assert.ok(metrics.flatMap(item => item.actions).every(button => button.height >= 44));
        for (const item of metrics.filter(item => item.name !== 'Airtable')) {
          const labels = item.actions.map(action => action.text);
          if (status === 'connected') assert.deepEqual(labels, ['Desconectar', 'Gerenciar']);
          if (status === 'reauth_required') assert.deepEqual(labels, ['Desconectar', 'Reconectar']);
          if (status === 'disconnected') assert.equal(labels.length, 1);
        }
        if (width === 390 && status === 'connected') {
          for (const name of ['Google Drive', 'OneDrive', 'SharePoint', 'Notion']) {
            const card = page.locator('.integration-tool-card').filter({ has: page.getByText(name, { exact: true }) });
            await card.getByRole('button', { name: 'Gerenciar', exact: true }).click();
            const dialog = page.getByRole('dialog');
            await dialog.getByRole('heading', { name, exact: true }).waitFor();
            await dialog.getByRole('button', { name: 'Fechar', exact: true }).click();
            interactions++;
          }
          page.once('dialog', dialog => dialog.accept());
          const deletion = page.waitForRequest(request => request.method() === 'DELETE' && new URL(request.url()).pathname.endsWith('/data-sources/4'));
          await page.locator('.integration-tool-card').filter({ has: page.getByText('Notion', { exact: true }) }).getByRole('button', { name: 'Desconectar', exact: true }).click();
          await deletion;
          await page.getByText('SharePoint', { exact: true }).waitFor();
          interactions++;
        }
        if (width === 390 && status === 'available') {
          await page.getByRole('button', { name: 'Google Drive', exact: true }).click();
          await page.getByRole('dialog').getByText('Nenhuma conta conectada', { exact: true }).waitFor();
          await page.getByRole('dialog').getByRole('button', { name: 'Fechar', exact: true }).click();
          interactions++;
        }
        if (width === 390 && status === 'reauth_required') {
          const oauth = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/data-sources/onedrive/oauth/start'));
          await page.locator('.integration-tool-card').filter({ has: page.getByText('OneDrive', { exact: true }) }).getByRole('button', { name: 'Reconectar', exact: true }).click();
          const request = await oauth;
          assert.equal(new URL(request.url()).searchParams.get('source_id'), '2');
          interactions++;
        }
        assert.deepEqual(errors, []);
        results.push({ status, width, scrollWidth, metrics });
        await page.close();
      }
    }
    fs.writeFileSync(output, JSON.stringify({ cases: results.length, interactions, results }, null, 2));
    console.log(`PASS: ${results.length} responsive/status cases; ${interactions} card interactions; no horizontal overflow or page errors.`);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
