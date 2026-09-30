const { chromium } = require('playwright');
const fs = require('node:fs');
const assert = require('node:assert/strict');
const out = __dirname;
const org = '11111111-1111-4111-8111-111111111111';
const conv = '22222222-2222-4222-8222-222222222222';
const folder = (id, provider) => ({ id, name: `Pasta ${id}`, source_id: id, source_provider: provider, status: 'ready', query_status: 'ready' });
const contexts = [folder('a', 'google'), folder('b', 'google_drive'), folder('c', 'notion')];
const answer = Array.from({length: 45}, (_, i) => `Parágrafo ${i + 1}: Esta conversa longa confirma que os prazos, as entregas e as responsabilidades permanecem legíveis durante toda a rolagem. A equipe revisa os documentos e consulta as fontes para validar cada etapa. (fonte 1).`).join('\n\n');
const response = { answer, confidence: 'high', citations: [{document_id: 'doc', document_name: 'Plano de entregas.pdf', excerpt: 'Cronograma e responsabilidades da equipe.', page_number: 1, source_url: 'https://example.test/plano', source_provider: 'google_drive'}], retrieval_status: 'answered', conversation_id: conv };
const messages = [{id:'u', role:'user', content: 'Quais são os principais prazos? Explique em detalhes as entregas e responsabilidades da equipe nesta conversa longa.', context: null, response:null}, {id:'a',role:'assistant',content:answer,context:null,response}];
(async () => {
  const browser = await chromium.launch({ executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless:true });
  const results = [];
  for (const stage of ['before','after']) for (const width of [1440,390]) {
    const context = await browser.newContext({viewport:{width,height:900},deviceScaleFactor:1});
    await context.addInitScript(({org,conv}) => sessionStorage.setItem(`arquivio:conversation:${org}`, conv), {org,conv});
    await context.route('**/*', async route => {
      const u = new URL(route.request().url());
      if (u.port !== '8000' && !u.pathname.startsWith('/api/')) return route.continue();

      const p = u.pathname.replace(/^\/api/, '');
      let data;
      if (p === '/me' || p === '/session') data = {id:'user',email:'qa@example.test'};
      else if (p === '/organizations') data = [{id:org,name:'Validação do chat',membership_id:'member',role:'owner'}];
      else if (p === '/library/question-contexts') data = {items:contexts};
      else if (p === '/library' || p === '/library/syncs') data = {items:[]};
      else if (p === `/organizations/${org}/conversations/${conv}`) data = {id:conv,messages};
      else if (p.endsWith('/questions')) data = response;
      else data = {items:[]};
      await route.fulfill({status:200,contentType:'application/json',headers:{'access-control-allow-origin':route.request().headers()['origin'] || '*','access-control-allow-credentials':'true'},body:JSON.stringify(data)});
    });
    const page = await context.newPage();
    page.on('pageerror', e => console.error('PAGEERROR', e.message));
    await page.goto(`http://localhost:${stage === 'before' ? 3013 : 3012}/companies/${org}`);
    const log = page.getByRole('log');
    await page.getByText('Parágrafo 45:',{exact:false}).waitFor({timeout:15000}).catch(async e => { console.log(await page.locator('body').innerText()); await page.screenshot({path:'/tmp/document-ai-chat-qa/error.png'}); throw e; });
    await page.locator('.question-scope-count').waitFor();
    const expected = stage === 'before' ? '3 pastas disponíveis' : '2 ferramentas disponíveis';
    assert.equal(await page.locator('.question-scope-count').innerText(), expected);
    await log.evaluate(el => { el.scrollTop=0; });
    await page.getByRole('button',{name:'Nova conversa',exact:true}).scrollIntoViewIfNeeded();
    await page.screenshot({path:`${out}/${stage}-${width}-top.png`});
    const measure = async () => page.evaluate(() => {
      const button = [...document.querySelectorAll('button')].find(x => x.textContent.trim() === 'Nova conversa');
      const log = document.querySelector('[role="log"]');
      const b = button.getBoundingClientRect(), l = log.getBoundingClientRect();
      const intersections = [...log.querySelectorAll('p')].flatMap(el => {
        const range = document.createRange(); range.selectNodeContents(el);
        return [...range.getClientRects()].filter(r => r.bottom>l.top && r.top<l.bottom && r.left<b.right && r.right>b.left && r.top<b.bottom && r.bottom>b.top).map(r => ({text:el.textContent.slice(0,90),x:r.x,y:r.y,width:r.width,height:r.height}));
      });
      const frame = document.querySelector('.workspace-frame'); return {frameScrollTop:frame.scrollTop,button:{top:b.top,bottom:b.bottom},log:{top:l.top,bottom:l.bottom,height:l.height,scrollHeight:log.scrollHeight,scrollTop:log.scrollTop},intersections};
    });
    const top = await measure();
    if(stage==='before') assert.ok(top.intersections.length>0, 'Baseline should reproduce overlap');
    else assert.equal(top.intersections.length,0);
    const scrolls = [];
    if(width>=1024) {
      for (const fraction of [0.25,0.5,0.75,1]) {
        await log.evaluate((el,f)=>{el.scrollTop=(el.scrollHeight-el.clientHeight)*f;},fraction);
        const m = await measure(); scrolls.push(m);
        if(stage==='after') assert.equal(m.intersections.length,0);
      }
    } else {
      for (const fraction of [0.25,0.5,0.75,1]) {
        await page.locator('.workspace-frame').evaluate((el,f) => { el.scrollTop=(el.scrollHeight-el.clientHeight)*f; },fraction);
        const m=await measure(); scrolls.push(m);
        if(stage==='after') assert.equal(m.intersections.length,0);
      }
    }
    await page.screenshot({path:`${out}/${stage}-${width}-scrolled.png`});
    await page.locator('.question-scope-count').scrollIntoViewIfNeeded();
    await page.screenshot({path:`${out}/${stage}-${width}-composer.png`});
    if(stage==='after') {
      await page.getByRole('button',{name:'Ferramentas: Todas as ferramentas'}).click();
      assert.equal(await page.locator('#question-scope-menu .question-scope-option').count()-1,2);
      await page.getByRole('button',{name:'Google Drive',exact:true}).click();
      assert.equal(await page.locator('.question-scope-count').innerText(),'1 ferramenta disponível');
      await page.getByRole('button',{name:'Google Drive',exact:true}).click();
      assert.equal(await page.locator('.question-scope-count').innerText(),'0 ferramentas disponíveis');
      await page.getByRole('button',{name:'Todas as ferramentas',exact:true}).click();
      assert.equal(await page.locator('.question-scope-count').innerText(),'2 ferramentas disponíveis');
      await page.getByRole('button',{name:'Nova conversa',exact:true}).click();
      await page.getByRole('heading',{name:'O que você quer descobrir?'}).waitFor();
      assert.equal(await page.evaluate(({org}) => sessionStorage.getItem(`arquivio:conversation:${org}`),{org}),null);
    }
    results.push({stage,width,label:expected,top,scrolls});
    await context.close();
  }
  fs.writeFileSync(`${out}/visual-results.json`,JSON.stringify(results,null,2));
  console.log('PASS: overlap reproduced before on desktop/mobile; zero overlap after at top and four scroll positions each; labels/menu count and singular/plural; new conversation reset. 12 screenshots.');
  await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
