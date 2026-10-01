// Browser regression for F-007. All API requests use an anonymous local fixture.
// NODE_PATH=/tmp/document-ai-onboarding-tools/node_modules QA_APP_URL=http://localhost:3000 node TASK/evidence/f007/landing-check.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.QA_APP_URL ?? 'http://localhost:3000';
const output = process.env.QA_OUTPUT_DIR ?? __dirname;
const label = process.env.QA_LABEL ?? 'after-container';

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  const results = [];
  const failures = [];
  try {
    for (const width of [320, 390, 720, 768, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 1000 } });
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.route('**/*', route => {
        const pathname = new URL(route.request().url()).pathname.replace(/^\/api/, '');
        if (pathname === '/me' || pathname === '/session') {
          return route.fulfill({ status: 401, json: { detail: 'Anonymous QA fixture' } });
        }
        return route.continue();
      });
      await page.goto(base);
      await page.locator('.landing-source-row').first().waitFor();
      await page.evaluate(() => document.fonts.ready);
      const metrics = await page.evaluate(() => {
        const measure = node => {
          const rect = node.getBoundingClientRect();
          const style = getComputedStyle(node);
          return { display: style.display, visibility: style.visibility, width: rect.width, height: rect.height };
        };
        const sources = document.querySelector('.landing-app-sources');
        return {
          scrollWidth: document.documentElement.scrollWidth,
          gridDisplay: getComputedStyle(sources).display,
          gridColumns: getComputedStyle(sources).gridTemplateColumns,
          rows: [...document.querySelectorAll('.landing-source-row')].map(row => ({
            name: row.querySelector(':scope > span:not(.provider-logo)').textContent,
            logo: measure(row.querySelector('.provider-logo > svg')),
            chevron: measure(row.querySelector(':scope > svg:last-child')),
            scrollWidth: row.scrollWidth,
            clientWidth: row.clientWidth,
          })),
        };
      });
      await page.screenshot({ path: path.join(output, `${label}-full-${width}.png`), fullPage: true });
      await page.locator('.landing-preview').screenshot({ path: path.join(output, `${label}-preview-${width}.png`) });
      await page.locator('.landing-app-sources').screenshot({ path: path.join(output, `${label}-sources-${width}.png`) });
      const result = { width, ...metrics, errors };
      results.push(result);
      try {
        assert.equal(metrics.rows.length, 4);
        assert.deepEqual(metrics.rows.map(row => row.name), ['Google Drive', 'Notion', 'OneDrive', 'SharePoint']);
        assert.ok(metrics.scrollWidth <= width, `${width}: page overflow`);
        if (width <= 960) {
          assert.equal(metrics.gridDisplay, 'grid');
          assert.equal(metrics.gridColumns.split(' ').length, width <= 720 ? 2 : 4);
        } else assert.equal(metrics.gridDisplay, 'flex');
        for (const row of metrics.rows) {
          assert.ok(row.logo.display !== 'none' && row.logo.visibility === 'visible' && row.logo.width > 0 && row.logo.height > 0, `${width}/${row.name}: logo hidden`);
          assert.equal(row.chevron.display === 'none', width <= 720, `${width}/${row.name}: chevron breakpoint`);
          if (width > 720) assert.ok(row.chevron.width > 0 && row.chevron.height > 0);
          assert.ok(row.scrollWidth <= row.clientWidth, `${width}/${row.name}: row overflow`);
        }
        assert.deepEqual(errors, []);
      } catch (error) {
        failures.push(error.message);
      }
      await page.close();
    }
    fs.writeFileSync(path.join(output, `${label}-results.json`), JSON.stringify({ base, cases: results.length, failures, results }, null, 2));
    assert.deepEqual(failures, [], failures.join('\n'));
    console.log('PASS: 5 widths; 20 visible logos; correct mobile-only chevron hiding; responsive grid preserved; no page/row overflow or page errors.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
