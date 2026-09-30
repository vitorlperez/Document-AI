// NODE_PATH=/tmp/document-ai-chat-qa/node_modules node artifacts/chat-answer-format/visual-check.cjs before|after
const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const fixture = require('./fixture.json');
const stage = process.argv[2];
assert.ok(['before', 'after'].includes(stage));
const org = '11111111-1111-4111-8111-111111111111';
const conv = '22222222-2222-4222-8222-222222222222';
const response = { ...fixture, confidence: 'high', retrieval_status: 'answered', conversation_id: conv };
const messages = [{ id: 'u', role: 'user', content: fixture.question, context: null, response: null },
  { id: 'a', role: 'assistant', content: fixture.answer, context: null, response }];
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const results = [];
  for (const width of [1440, 390]) {
    const context = await browser.newContext({ viewport: { width, height: width === 390 ? 1600 : 1100 }, deviceScaleFactor: 1 });
    await context.addInitScript(({ org, conv }) => sessionStorage.setItem(`arquivio:conversation:${org}`, conv), { org, conv });
    await context.route('**/*', async route => {
      const u = new URL(route.request().url());
      if (u.port !== '8000' && !u.pathname.startsWith('/api/')) return route.continue();
      const p = u.pathname.replace(/^\/api/, '');
      let data;
      if (p === '/me' || p === '/session') data = { id: 'user', email: 'qa@example.test' };
      else if (p === '/organizations') data = [{ id: org, name: 'Validação do chat', membership_id: 'member', role: 'owner', onboarding_completed: true }];
      else if (p === '/library/question-contexts') data = { items: [{ id: 'folder', name: 'Currículos', source_provider: 'google_drive', status: 'ready', query_status: 'ready' }] };
      else if (p === `/organizations/${org}/conversations/${conv}`) data = { id: conv, messages };
      else if (p.endsWith('/questions')) data = response;
      else data = { items: [] };
      await route.fulfill({ status: 200, contentType: 'application/json', headers: { 'access-control-allow-origin': route.request().headers()['origin'] || '*', 'access-control-allow-credentials': 'true' }, body: JSON.stringify(data) });
    });
    const page = await context.newPage();
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`http://127.0.0.1:3014/companies/${org}`);
    await page.locator('.answer-body').waitFor({ timeout: 30000 });
    await page.locator('.source-row').first().waitFor();
    await page.locator('[role="log"]').evaluate(el => { el.scrollTop = 0; });
    await page.locator('.conversation-answer').screenshot({ path: `${__dirname}/${stage}-${width}-answer.png` });
    await page.screenshot({ path: `${__dirname}/${stage}-${width}-page.png`, fullPage: true });
    const measures = await page.evaluate(() => {
      const answer = document.querySelector('.answer-body');
      const lists = [...answer.querySelectorAll('ol')].map(el => ({ start: el.start, items: el.children.length }));
      const rows = [...document.querySelectorAll('.source-row')].map(el => {
        const name = el.querySelector('span.flex-1'), provider = el.querySelector('.citation-tool'), link = el.querySelector('a');
        return { height: el.getBoundingClientRect().height, nameSize: getComputedStyle(name).fontSize, providerSize: getComputedStyle(provider).fontSize, providerColor: getComputedStyle(provider).color,
          linkCenterDelta: Math.abs((link.getBoundingClientRect().top + link.getBoundingClientRect().height / 2) - (el.getBoundingClientRect().top + el.getBoundingClientRect().height / 2)), href: link.href };
      });
      return { lists, rows, citations: answer.querySelectorAll('.answer-cite').length, overflow: document.documentElement.scrollWidth > innerWidth };
    });
    assert.equal(errors.length, 0, errors.join('\n'));
    assert.equal(measures.rows.length, 3);
    assert.equal(measures.citations, 6);
    if (stage === 'before') {
      assert.deepEqual(measures.lists, Array.from({ length: 4 }, () => ({ start: 1, items: 1 })));
      assert.ok(measures.rows.every(r => parseFloat(r.providerSize) > parseFloat(r.nameSize)));
    } else {
      assert.deepEqual(measures.lists, [{ start: 1, items: 4 }]);
      assert.ok(measures.rows.every(r => parseFloat(r.providerSize) <= parseFloat(r.nameSize)));
      assert.ok(measures.rows.every(r => r.height <= (width === 390 ? 62 : 40)));
      assert.ok(measures.rows.every(r => r.linkCenterDelta < 1));
      assert.equal(measures.overflow, false);
      await page.getByRole('button', { name: 'Fonte 3: Profile.pdf', exact: true }).click();
      await page.locator('#source-a-3:focus').waitFor();
      assert.equal(await page.locator('#source-a-3 a').getAttribute('target'), '_blank');
    }
    results.push({ stage, width, ...measures });
    await context.close();
  }
  fs.writeFileSync(`${__dirname}/${stage}-results.json`, JSON.stringify(results, null, 2) + '\n');
  console.log(`PASS ${stage}: desktop and 390px; numbered list, 6 citations, 3 source links, provider typography and layout checked.`);
  await browser.close();
})().catch(e => { console.error(e); process.exit(1); });
