// NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules node artifacts/developer-page/visual-check.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const org = '11111111-1111-4111-8111-111111111111';
const other = '22222222-2222-4222-8222-222222222222';
const origin = process.env.DEVELOPER_QA_URL || 'http://localhost:5183';
const results = [];
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  try {
    for (const scenario of [
      { name: 'desktop-configured', width: 1440, role: 'owner', configured: true },
      { name: 'mobile-configured', width: 390, role: 'admin', configured: true },
      { name: 'desktop-unconfigured', width: 1440, role: 'owner', configured: false },
      { name: 'desktop-member', width: 1440, role: 'member', configured: true },
      { name: 'mobile-member', width: 390, role: 'member', configured: true },
    ]) {
      const context = await browser.newContext({ viewport: { width: scenario.width, height: 900 }, deviceScaleFactor: 1 });
      const calls = [], errors = [];
      let publicEnabled = false, mcpEnabled = false, active = false, keys = [];
      await context.route('**/*', async route => {
        const request = route.request(), url = new URL(request.url());
        if (url.port !== '8000' && !url.pathname.startsWith('/api/')) return route.continue();
        const path = url.pathname.replace(/^\/api/, ''), method = request.method();
        calls.push({ path, method });
        let data = { items: [] }, status = 200;
        if (path === '/me' || path === '/session') data = { id: 'qa-user', email: 'qa@example.test' };
        else if (path === '/organizations') data = [org, other].map((id, index) => ({ id, name: index ? 'Outra organização' : 'Organização de teste', membership_id: `m${index}`, role: scenario.role }));
        else if (path.endsWith('/onboarding')) data = { required: false, step: 'complete', tour_required: false };
        else if (path.endsWith('/mcp-info')) data = { configured: scenario.configured, resource_url: scenario.configured ? 'https://mcp.example.test/custom/mcp' : null, issuer_url: scenario.configured ? 'https://auth.example.test' : null, static_key_enabled: true, transport: 'streamable-http', tools: ['search', 'fetch', 'list_sources'] };
        else if (path.endsWith('/access-settings')) {
          if (method === 'PUT') publicEnabled = request.postDataJSON().public_api_enabled;
          data = { public_api_enabled: publicEnabled, mcp_enabled: mcpEnabled };
        } else if (path.endsWith('/mcp-settings')) {
          mcpEnabled = request.postDataJSON().mcp_enabled; data = { mcp_enabled: mcpEnabled };
        } else if (path.endsWith('/mcp-connection')) {
          if (method === 'PUT') active = true;
          if (method === 'DELETE') { active = false; status = 204; }
          data = { active };
        } else if (path.endsWith('/api-keys')) {
          if (method === 'POST') {
            const key = { id: 'test-key', ...request.postDataJSON(), prefix: 'arq_test', revoked_at: null, last_used_at: null, expires_at: null };
            keys.push(key); data = { ...key, key: 'arq_test_fixture_only' }; status = 201;
          } else data = keys;
        } else if (path.endsWith('/api-keys/test-key')) {
          keys = keys.map(key => ({ ...key, revoked_at: '2026-10-02T12:00:00Z' })); status = 204;
        } else if (path === '/data-sources' || path === '/workspace-folders') data = [];
        await route.fulfill({ status, contentType: 'application/json', headers: { 'access-control-allow-origin': request.headers()['origin'] || origin, 'access-control-allow-credentials': 'true' }, ...(status === 204 ? {} : { body: JSON.stringify(data) }) });
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      page.on('dialog', dialog => dialog.accept());
      await page.goto(`${origin}/companies/${org}/developer`);
      const openMenu = () => page.getByRole('button', { name: scenario.width < 768 ? 'Abrir menu' : 'Navegar', exact: true }).click();
      if (scenario.role === 'member') {
        await page.getByRole('heading', { name: 'Acesso restrito' }).waitFor();
        assert.equal(calls.filter(call => /mcp-info|api-keys|access-settings/.test(call.path)).length, 0, 'Member never loads developer data');
        await openMenu();
        assert.equal(await page.getByRole('button', { name: /Desenvolvedor/ }).count(), 0);
        await page.screenshot({ path: `${__dirname}/${scenario.name}.png`, fullPage: true });
      } else {
        await page.getByRole('heading', { name: 'Desenvolvedor', exact: true }).waitFor();
        await page.getByText('Nenhuma chave criada.', { exact: true }).waitFor();
        await page.getByRole('heading', { name: 'Ferramentas do servidor' }).waitFor();
        assert.equal(await page.locator('input[type=checkbox]').first().isChecked(), false);
        await page.getByLabel('Habilitar API pública', { exact: true }).click();
        await page.waitForFunction(() => [...document.querySelectorAll('label')].find(label => label.textContent.includes('Habilitar API pública'))?.querySelector('input')?.checked);
        assert.equal(publicEnabled, true);
        if (scenario.configured) {
          await page.getByText('Conectar um cliente', { exact: true }).waitFor();
          assert.match(await page.locator('pre').nth(0).innerText(), /custom\/mcp/);
          assert.equal(JSON.parse(await page.locator('pre').nth(2).innerText()).mcpServers.arquivio.url, 'https://mcp.example.test/custom/mcp');
          await page.getByLabel('Habilitar MCP para a organização').click();
          await page.waitForFunction(() => [...document.querySelectorAll('label')].find(label => label.textContent.includes('Habilitar MCP para a organização'))?.querySelector('input')?.checked);
          await page.getByRole('button', { name: 'Vincular minha conta', exact: true }).click();
          await page.getByRole('button', { name: 'Desvincular minha conta', exact: true }).waitFor();
          assert.equal(mcpEnabled && active, true);
          await page.getByRole('button', { name: 'Desvincular minha conta', exact: true }).click();
          await page.getByRole('button', { name: 'Vincular minha conta', exact: true }).waitFor();
          assert.equal(active, false);
          await page.getByLabel('Nome', { exact: true }).fill('Automação de teste');
          await page.getByRole('button', { name: 'Criar chave', exact: true }).click();
          await page.getByRole('dialog').waitFor();
          assert.equal(await page.getByLabel('Chave de API').inputValue(), 'arq_test_fixture_only');
          await page.getByRole('button', { name: 'Fechar', exact: true }).click();
          await page.getByRole('button', { name: 'Revogar Automação de teste', exact: true }).click();
          await page.getByRole('cell', { name: 'Revogada', exact: true }).waitFor();
        } else {
          await page.getByText(/O servidor MCP já existe, mas a conexão ainda não está configurada/).waitFor();
          assert.equal(await page.locator('pre').count(), 0);
          assert.equal(await page.getByLabel('Habilitar MCP para a organização').isDisabled(), true);
        }
        await page.screenshot({ path: `${__dirname}/${scenario.name}.png`, fullPage: true });
        const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        assert.equal(horizontalOverflow, false, 'No page-level horizontal overflow');
        await openMenu();
        const developerItem = page.getByRole('button', { name: /Desenvolvedor/ });
        await developerItem.waitFor();
        await developerItem.click();
        await page.getByRole('heading', { name: 'Desenvolvedor', exact: true }).waitFor();
        const companySelect = page.getByLabel(scenario.width < 768 ? 'Organização ativa' : 'Organização ativa');
        if (scenario.width < 768) await openMenu();
        await companySelect.selectOption(other);
        await page.waitForURL(`**/companies/${other}/developer`);
        await page.getByRole('heading', { name: 'Desenvolvedor', exact: true }).waitFor();
        await page.goto(`${origin}/companies/${org}/integrations`);
        await page.getByRole('heading', { name: 'Fontes de conhecimento', exact: true }).waitFor();
        assert.equal(await page.getByRole('heading', { name: 'Acesso por API e IA' }).count(), 0);
        await page.screenshot({ path: `${__dirname}/${scenario.name}-integrations.png`, fullPage: true });
      }
      assert.deepEqual(errors, [], 'No browser runtime errors');
      results.push({ ...scenario, passed: true, calls: calls.length, runtimeErrors: errors });
      await context.close();
    }
    fs.writeFileSync(`${__dirname}/visual-results.json`, JSON.stringify(results, null, 2));
    console.log(`PASS: ${results.length}/5 scenarios; API lifecycle, MCP enable/bind/revoke, configured/unconfigured state, desktop/mobile navigation, organization switch, member denial, API removed from Integrations, no runtime errors or horizontal overflow. Screenshots in artifacts/developer-page/.`);
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
