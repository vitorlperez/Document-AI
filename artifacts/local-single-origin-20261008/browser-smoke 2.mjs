import { chromium } from '/Users/vitorperez/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs';
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';
const browser = await chromium.launch({headless:true, executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const evidence = {timestamp:new Date().toISOString(), target:'http://localhost:3000/login', backend:'http://localhost:3000/api', mode:'same-origin', realAuthenticationAttempted:false, emailsRequested:false, viewports:[]};
try {
  for (const [width,height] of [[1440,900],[390,844],[320,740]]) {
    const context = await browser.newContext({viewport:{width,height}});
    const blockedExternal=[]; const pageErrors=[]; const sessionResponses=[];
    await context.route('**/*', async route => {
      const u=new URL(route.request().url());
      if (['http://localhost:3000'].includes(u.origin)) return route.continue();
      blockedExternal.push(u.hostname); return route.abort();
    });
    const page=await context.newPage();
    page.on('pageerror', e=>pageErrors.push(e.message));
    page.on('response', r=>{if(r.url()==='http://localhost:3000/api/session') sessionResponses.push(r.status());});
    const response=await page.goto(evidence.target,{waitUntil:'networkidle',timeout:60000});
    await page.getByLabel('E-mail',{exact:true}).waitFor();
    assert.equal(page.url(),evidence.target,'login must stay in Arquivio');
    assert.equal(response.status(),200);
    assert.equal(await page.getByRole('heading',{name:'Bem-vindo de volta.'}).count(),1);
    assert.equal(await page.getByLabel('Senha',{exact:true}).count(),1);
    assert.equal(await page.locator('[role="alert"]').count(),0);
    assert.ok(sessionResponses.includes(200),'real API session check must return anonymous 200/null');
    assert.deepEqual(blockedExternal,[],'no external redirects or requests');
    assert.deepEqual(pageErrors,[],'no uncaught JS errors');
    const dimensions=await page.evaluate(()=>({viewport:innerWidth,content:document.documentElement.scrollWidth}));
    assert.ok(dimensions.content<=width,'no horizontal overflow');
    assert.equal(response.headers()['referrer-policy'],'no-referrer');
    await page.screenshot({path:new URL(`login-${width}.png`,import.meta.url).pathname,fullPage:true});
    const probes=await page.evaluate(async()=>{
      const ready=await fetch('http://localhost:3000/api/health/ready',{credentials:'include'});
      const password=await fetch('http://localhost:3000/api/auth/password',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'include',body:'{}'});
      return {readiness:{status:ready.status,body:await ready.json()},passwordInvalidBody:{status:password.status,detail:(await password.json()).detail}};
    });
    assert.equal(probes.readiness.status,200); assert.equal(probes.readiness.body.status,'ready');
    assert.equal(probes.passwordInvalidBody.status,422); assert.equal(probes.passwordInvalidBody.detail,'Confira os dados informados e tente novamente.');
    await page.getByRole('button',{name:'Criar conta',exact:true}).click();
    await page.getByRole('heading',{name:'Comece pelo conhecimento.'}).waitFor();
    assert.equal(await page.locator('input[name="password"]').count(),0);
    await page.getByRole('button',{name:'Entrar',exact:true}).click();
    await page.getByRole('button',{name:'Esqueceu a senha?',exact:true}).click();
    await page.getByRole('button',{name:'Enviar link de recuperação',exact:true}).waitFor();
    await page.getByRole('button',{name:'Voltar para entrar',exact:true}).click();
    await page.getByRole('heading',{name:'Bem-vindo de volta.'}).waitFor();
    evidence.viewports.push({width,height,url:page.url(),httpStatus:response.status(),...dimensions,sessionResponses,blockedExternal,pageErrors,probes,signupForm:'email only; not submitted',recoveryForm:'present; not submitted',screenshot:`login-${width}.png`});
    await context.close();
  }
  writeFileSync(new URL('browser-smoke.json',import.meta.url),JSON.stringify(evidence,null,2)+'\n');
  console.log(JSON.stringify(evidence,null,2));
} finally { await browser.close(); }
