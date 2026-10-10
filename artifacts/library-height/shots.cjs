// NODE_PATH=/private/tmp/pw/node_modules node grid-shots.cjs <label>   (browser-local API fixtures, app at :3000)
const { chromium } = require('playwright-core');
const label = process.argv[2] || 'after';
const org = '11111111-1111-4111-8111-111111111111';
const base = process.env.BASE || 'http://localhost:3000';
const providers = ['google_drive', 'onedrive', 'sharepoint', 'notion', 'clickup'];
const sources = providers.map((provider, i) => ({ id: String(i + 1), provider, status: 'connected', account_email: 'equipe@exemplo.com' }));
const items0 = [
  ...['Contratos', 'Financeiro 2026', 'Jurídico'].map((name, i) => ({ id: 'f' + i, parent_id: null, source_id: '1', source_provider: 'google_drive', kind: 'folder', name, mime_type: null, children_count: 4 })),
  ...['Proposta.pdf', 'Orçamento.xlsx'].map((name, i) => ({ id: 'd' + i, parent_id: null, source_id: '1', source_provider: 'google_drive', kind: 'file', name, mime_type: 'application/pdf', status: 'Indexado' })),
];

const items = Array.from({length: 40}, (_, i) => i % 5 === 0 ? { id: 'f'+i, parent_id: null, source_id: '1', source_provider: 'google_drive', kind: 'folder', name: 'Pasta '+i, mime_type: null, children_count: 4 } : { id: 'd'+i, parent_id: null, source_id: '1', source_provider: 'google_drive', kind: 'file', name: 'Arquivo '+i+'.pdf', mime_type: 'application/pdf' });
const itemsFew = items0;
const sizes = { desktop: { width: 1440, height: 900 }, mobile: { width: 390, height: 844 } };
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  for (const [dev, vp] of Object.entries(sizes)) for (const mode of ['list','grid']) for (const theme of ['light','dark']) for (const data of (process.env.DATA||'many,few').split(',')) {
    const ctx = await browser.newContext({ viewport: vp, isMobile: dev==='mobile' });
    await ctx.addInitScript(([t,m]) => { try { localStorage.setItem('arquivio-theme', t); localStorage.setItem('arquivio:library-view', JSON.stringify({ mode: m, size: 'm' })); } catch {} }, [theme, mode]);
    const page = await ctx.newPage();
    const list = data==='many' ? items : itemsFew;
    await page.route('**/api/**', route => {
      const p = new URL(route.request().url()).pathname.replace(/^\/api/, '');
      let json = [];
      if (p === '/me' || p === '/session') json = { id: org, email: 'qa@example.com' };
      else if (p === '/organizations') json = [{ id: org, name: 'Equipe QA', membership_id: org, role: 'owner' }];
      else if (/onboarding/.test(p)) json = { step: 'done', required: false, tour_required: false };
      else if (p === '/data-sources') json = sources;
      else if (/sync-history/.test(p)) json = { items: [] };
      else if (/library|nodes|items/.test(p)) json = { items: list, page: 1, pages: 1, total: list.length };
      return route.fulfill({ json });
    });
    await page.goto(`${base}/companies/${org}/library`);
    await page.waitForTimeout(1500);
    const btn = page.locator(dev==='mobile' ? 'aside button' : 'aside[aria-label="Ferramentas integradas"] button').filter({ hasText: /Pasta 0|Contratos/ }).first();
    await btn.click().catch(() => {});
    await page.waitForTimeout(1500);
    const m = await page.evaluate(() => { const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return [Math.round(b.top), Math.round(b.bottom)]; }; const st=[...document.querySelectorAll('p[role=status]')].find(e=>/Todos os itens/.test(e.textContent)); const sb = st && st.getBoundingClientRect(); const fr=document.querySelector('.workspace-frame'); return { vh: innerHeight, docH: document.documentElement.scrollHeight, docW: document.documentElement.scrollWidth, frame: r('.workspace-frame'), main: r('.library-panels > main'), status: sb && [Math.round(sb.top), Math.round(sb.bottom)] }; });
    console.log(dev, mode, theme, data, JSON.stringify(m));
    if (data==='many' || theme==='light') await page.screenshot({ path: `${label}-${dev}-${mode}-${theme}-${data}.png` });
    await ctx.close();
  }
  await browser.close();
})();
