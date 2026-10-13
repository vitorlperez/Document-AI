// Regressão de viewport da tela de login: nenhum scroll vertical do documento nos viewports comuns.
// Uso: LOGIN_FIT_BASE=http://localhost:5173 PLAYWRIGHT_CORE=<caminho do playwright-core/index.mjs> node scripts/login-fit-check.mjs [pasta-de-screenshots]
import { mkdirSync } from "node:fs";
import { pathToFileURL } from "node:url";

const { chromium } = await import(process.env.PLAYWRIGHT_CORE ? pathToFileURL(process.env.PLAYWRIGHT_CORE).href : "playwright-core");
const base = process.env.LOGIN_FIT_BASE ?? "http://localhost:5173";
const shots = process.argv[2];
if (shots) mkdirSync(shots, { recursive: true });
const viewports = [[1280, 720], [1366, 768], [1440, 900], [1536, 864], [1920, 1080], [390, 844], [360, 740]];
const modes = [{ name: "sign-in" }, { name: "sign-up", path: "?mode=sign-up" }, { name: "forgot", click: "Esqueceu a senha?" }];
const browser = await chromium.launch({ headless: true, channel: process.env.LOGIN_FIT_CHANNEL ?? "chrome" });
const failures = [];
for (const theme of ["light", "dark"]) for (const [width, height] of viewports) for (const mode of modes) {
  const context = await browser.newContext({ viewport: { width, height }, colorScheme: theme });
  await context.addInitScript((value) => { try { localStorage.setItem("theme", value); } catch { /* sem storage */ } }, theme);
  const page = await context.newPage();
  await page.goto(`${base}/login${mode.path ?? ""}`, { waitUntil: "networkidle" });
  await page.locator(".login-page").waitFor();
  if (mode.click) await page.getByRole("button", { name: mode.click }).click();
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running"));
  const m = await page.evaluate(() => {
    const side = document.querySelector(".login-form-side");
    const form = document.querySelector(".login-form-container").getBoundingClientRect();
    return { doc: document.documentElement.scrollHeight - innerHeight, side: side.scrollHeight - side.clientHeight, x: document.documentElement.scrollWidth - innerWidth, formCut: Math.round(Math.max(0, -form.top, form.bottom - innerHeight)) };
  });
  const label = `${theme} ${width}x${height} ${mode.name}`;
  if (m.doc > 0 || m.side > 0 || m.x > 0 || m.formCut > 0) failures.push(`${label}: ${JSON.stringify(m)}`);
  if (shots) await page.screenshot({ path: `${shots}/${theme}-${width}x${height}-${mode.name}.png` });
  await context.close();
}
await browser.close();
if (failures.length) { console.error(`Login ultrapassa a viewport:\n${failures.join("\n")}`); process.exit(1); }
console.log(`Login cabe em 100% da altura em ${viewports.length * 2 * modes.length} combinações (viewports × tema × modo).`);
