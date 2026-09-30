const { chromium } = require('playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  await page.goto('http://localhost:5173/login');
  await page.getByRole('button', { name: 'Criar uma conta', exact: true }).click();
  await page.getByLabel('Nome da organização').fill('Review regression A');
  await page.getByRole('button', { name: 'Criar organização', exact: true }).click();
  await page.getByRole('heading', { name: 'Boas-vindas ao Arquivio' }).waitFor();
  const org = new URL(page.url()).pathname.split('/')[2];
  let patches = 0;
  await page.route('**/organizations', async route => {
    const response = await route.fetch();
    const memberships = await response.json();
    await route.fulfill({ response, json: memberships.map(item => ({ ...item, role: 'member' })) });
  });
  await page.route(`**/organizations/${org}/onboarding`, async route => {
    if (route.request().method() === 'PATCH') patches++;
    await route.fulfill({ json: { step: 'welcome', required: false, tour_required: false } });
  });
  await page.getByRole('button', { name: 'Vamos começar', exact: true }).click();
  await page.getByRole('heading', { name: 'O que você quer descobrir?' }).waitFor();
  assert.equal(patches, 0, 'R-1: a demoted member must never submit an advance');
  assert.equal(await page.locator('.onboarding-actions').count(), 0);
  await page.screenshot({ path: 'artifacts/onboarding/qa/fixed-R-1.png' });
  await page.unroute('**/organizations');
  await page.unroute(`**/organizations/${org}/onboarding`);
  // Persist A completion so the next scenario can load its conversation normally.
  await context.request.patch(`http://localhost:8011/organizations/${org}/onboarding`, { data: { step: 'complete' } });
  await context.request.post(`http://localhost:8011/organizations/${org}/onboarding/tour/complete`);
  console.log('PASS R-1: current member role hides actions and prevents PATCH');
  const response = await context.request.post('http://localhost:8011/organizations', { data: { name: 'Review regression B' } });
  const other = (await response.json()).id;
  await context.request.patch(`http://localhost:8011/organizations/${other}/onboarding`, { data: { step: 'complete' } });
  await context.request.post(`http://localhost:8011/organizations/${other}/onboarding/tour/complete`);
  await page.reload();
  await page.getByRole('heading', { name: 'O que você quer descobrir?' }).waitFor();
  let captured, release, delivered;
  const pending = new Promise(resolve => { captured = resolve; });
  const gate = new Promise(resolve => { release = resolve; });
  const delivery = new Promise(resolve => { delivered = resolve; });
  await page.route(`**/organizations/${other}/onboarding`, async route => {
    const response = await route.fetch();
    captured();
    await gate;
    await route.fulfill({ response }).catch(() => {}); // Cancellation is the correct result too.
    delivered();
  });
  await page.getByLabel('Organização ativa').selectOption(other);
  await pending;
  await page.goBack();
  await page.getByRole('heading', { name: 'O que você quer descobrir?' }).waitFor();
  release();
  await delivery;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  assert.equal(await page.getByLabel('Organização ativa').inputValue(), org, 'R-2: late B response cannot replace active A');
  assert.equal(await page.getByRole('heading', { name: 'O que você quer descobrir?' }).count(), 1);
  await page.screenshot({ path: 'artifacts/onboarding/qa/fixed-R-2.png' });
  console.log('PASS R-2: late response from the previous organization is discarded');
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
