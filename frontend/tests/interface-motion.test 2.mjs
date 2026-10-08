import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { clampDuration, playSurfaceEntry, REDUCED_MOTION_QUERY } from "../app/interface-motion.ts";

function fakeMedia(matches = false) {
  const listeners = new Set();
  return {
    matches,
    addEventListener: (type, listener) => { assert.equal(type, "change"); listeners.add(listener); },
    removeEventListener: (type, listener) => listeners.delete(listener),
    emit(next) { this.matches = next; for (const listener of [...listeners]) listener({ matches: next }); },
    get size() { return listeners.size; },
  };
}

function fakeElement() {
  const element = { calls: [], animations: [] };
  element.animate = (keyframes, options) => {
    let resolve;
    const animation = { cancelled: false, cancel() { animation.cancelled = true; }, finished: new Promise((done) => { resolve = done; }), finish: () => resolve() };
    element.calls.push({ keyframes, options });
    element.animations.push(animation);
    return animation;
  };
  return element;
}

test("plays a short visual entry with the approved timing and no fill", () => {
  const media = fakeMedia(false);
  const element = fakeElement();
  playSurfaceEntry(element, { matchMedia: (query) => { assert.equal(query, REDUCED_MOTION_QUERY); return media; } });
  assert.equal(element.calls.length, 1);
  const [{ keyframes, options }] = element.calls;
  assert.deepEqual(keyframes, [{ opacity: 0.92, transform: "translateY(6px)" }, { opacity: 1, transform: "none" }]);
  assert.equal(options.duration, 200);
  assert.equal(options.fill, "none");
  assert.equal(media.size, 1);
});

test("reduced motion at start animates nothing and registers nothing", () => {
  const media = fakeMedia(true);
  const element = fakeElement();
  const cancel = playSurfaceEntry(element, { matchMedia: () => media });
  assert.equal(element.calls.length, 0);
  assert.equal(media.size, 0);
  cancel();
});

test("switching to reduced motion mid-entry cancels the animation and detaches", () => {
  const media = fakeMedia(false);
  const element = fakeElement();
  playSurfaceEntry([element, element], { matchMedia: () => media });
  media.emit(true);
  assert.ok(element.animations.every((animation) => animation.cancelled));
  assert.equal(media.size, 0);
});

test("a new cycle cancels the previous one: only the latest entry stays alive", () => {
  const media = fakeMedia(false);
  const element = fakeElement();
  const cancels = [];
  for (let step = 0; step < 20; step++) { cancels.at(-1)?.(); cancels.push(playSurfaceEntry(element, { matchMedia: () => media })); }
  assert.equal(element.animations.filter((animation) => !animation.cancelled).length, 1);
  assert.equal(media.size, 1);
  cancels.at(-1)();
  cancels.at(-1)();
  assert.ok(element.animations.every((animation) => animation.cancelled));
  assert.equal(media.size, 0);
});

test("finishing naturally removes the media listener without cancelling", async () => {
  const media = fakeMedia(false);
  const element = fakeElement();
  playSurfaceEntry(element, { matchMedia: () => media });
  element.animations[0].finish();
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(media.size, 0);
  assert.equal(element.animations[0].cancelled, false);
});

test("ignores missing targets and clamps duration to the 180–220ms band", () => {
  assert.doesNotThrow(() => playSurfaceEntry([null, undefined], { matchMedia: () => fakeMedia(false) })());
  assert.equal(clampDuration(undefined), 200);
  assert.equal(clampDuration(90), 180);
  assert.equal(clampDuration(500), 220);
  assert.equal(clampDuration(Number.NaN), 200);
});

test("the helper owns no business behaviour: no timers, focus, storage or network", () => {
  const source = readFileSync(new URL("../app/interface-motion.ts", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*$/gm, "");
  for (const banned of [/setTimeout/, /setInterval/, /requestAnimationFrame/, /\.focus\(/, /fetch\(/, /localStorage/, /sessionStorage/, /getAnimations/, /inert/]) assert.doesNotMatch(source, banned);
});

test("interface motion CSS is opt-in only and honours reduced motion", () => {
  const css = readFileSync(new URL("../app/interface-motion.css", import.meta.url), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
  const rules = css.replace(/@keyframes[^{]+\{(?:[^{}]*\{[^}]*\})*\s*\}/g, "").replace(/@media[^{]+\{/g, "");
  assert.doesNotMatch(css, /:root/);
  const selectors = [...rules.matchAll(/(?:^|\})\s*([^@{}][^{}]*)\{/g)].map((match) => match[1].trim()).filter((selector) => !/^(from|to|\d+%)$/.test(selector));
  for (const selector of selectors) assert.match(selector, /data-arquivio-motion|aq-motion-overlay/, `not opt-in: ${selector}`);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none !important/);
  for (const [, duration] of css.matchAll(/--aq-motion-(?:enter|exit): (\d+)ms/g)) assert.ok(+duration >= 180 && +duration <= 220);
});

test("Sheet keeps its default motion; the arquivio profile is opt-in from the mobile menu only", () => {
  const sheet = readFileSync(new URL("../components/ui/sheet.tsx", import.meta.url), "utf8");
  assert.match(sheet, /data-\[state=closed\]:duration-300 data-\[state=open\]:animate-in data-\[state=open\]:duration-500/, "default branch unchanged");
  assert.match(sheet, /: <SheetOverlay \/>\}/, "default overlay unchanged");
  const mobileNav = readFileSync(new URL("../app/mobile-nav.tsx", import.meta.url), "utf8");
  assert.match(mobileNav, /motionProfile="arquivio"/);
  for (const file of ["../components/ui/sidebar.tsx", "../components/ui/dialog.tsx", "../components/ui/alert-dialog.tsx", "../components/ui/drawer.tsx", "../components/ui/command.tsx"]) {
    assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), "utf8"), /motionProfile|data-arquivio-motion/, file);
  }
});

test("modal seams only add opt-in markers; dismissal and secret handling stay as they were", () => {
  const read = (file) => readFileSync(new URL(file, import.meta.url), "utf8");
  const library = read("../app/product/library-screen.tsx");
  assert.match(library, /useDialogBackdropClose\(syncDialog, closeSpacesPanel, busyNodeId !== null \|\| busyFolderId !== null\)/);
  assert.match(library, /if \(spacesPanelOpen\) dialog\?\.showModal\(\); else dialog\?\.close\(\);/);
  const integrations = read("../app/product/integrations-screen.tsx");
  assert.match(integrations, /<ModalOverlay onClose=\{closeTool\} busy=\{busy\} labelledBy="sync-tool-title" className="aq-motion-overlay /);
  const access = read("../app/access-settings.tsx");
  assert.match(access, /function closeSecret\(\) \{\n    dialog\.current\?\.close\(\); setSecret\(null\); setCopied\(false\);/);
  assert.match(access, /onCancel=\{closeSecret\} onClose=\{\(\) => setSecret\(null\)\}/);
  const tour = read("../app/conversation-tour.tsx");
  assert.match(tour, /return playSurfaceEntry\(text, \{ offsetY: 6 \}\);/);
  assert.match(tour, /onCancel=\{\(event\) => \{ event\.preventDefault\(\); void finish\(\); \}\}/);
  assert.doesNotMatch(read("../app/modal-dismiss.tsx"), /arquivio-motion/);
});
