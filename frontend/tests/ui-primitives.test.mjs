import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import test from "node:test";

import { clampProgress, ENTER_VARIANTS, exitDelayMs, MOTION_MS, skeletonLineWidths, staggerIndex, staggerStyle, STAGGER_MAX } from "../app/ui/motion-logic.ts";

const css = readFileSync(new URL("../app/ui/motion-tokens.css", import.meta.url), "utf8");

test("stagger é inteiro, não negativo e limitado ao máximo", () => {
  assert.equal(staggerIndex(-3), 0);
  assert.equal(staggerIndex(Number.NaN), 0);
  assert.equal(staggerIndex(2.9), 2);
  assert.equal(staggerIndex(99), STAGGER_MAX);
  assert.deepEqual(staggerStyle(3), { "--mo-i": 3 });
});

test("saída sem animação em reduced motion", () => {
  assert.equal(exitDelayMs(true), 0);
  assert.equal(exitDelayMs(false), MOTION_MS.fast);
  assert.equal(exitDelayMs(false, -5), 0);
});

test("progresso é limitado a 0–100", () => {
  assert.equal(clampProgress(-1), 0);
  assert.equal(clampProgress(48.6), 49);
  assert.equal(clampProgress(400), 100);
  assert.equal(clampProgress(Number.NaN), 0);
});

test("linhas de skeleton são determinísticas e a última é curta", () => {
  const a = skeletonLineWidths(3);
  assert.deepEqual(a, skeletonLineWidths(3));
  assert.equal(a.length, 3);
  assert.equal(a.at(-1), "60%");
  assert.equal(skeletonLineWidths(0).length, 1);
});

test("MOTION_MS espelha os tokens de duração do CSS", () => {
  for (const [name, ms] of Object.entries(MOTION_MS)) {
    const match = css.match(new RegExp(`--motion-${name}:\\s*(\\d+)ms;`));
    assert.ok(match, `token --motion-${name} ausente`);
    assert.equal(Number(match[1]), ms, `--motion-${name} divergente`);
  }
});

test("todo variant de Enter tem regra de entrada no CSS", () => {
  for (const v of ENTER_VARIANTS) assert.match(css, new RegExp(`\\.mo-enter\\[data-variant="${v}"\\]`), v);
});

test("reduced motion: tokens colapsam, regra global e loops sem animação", () => {
  const reduce = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
  assert.match(reduce, /--motion-base:\s*0\.01ms/);
  assert.match(reduce, /animation-duration:\s*0\.01ms !important/);
  assert.match(reduce, /transition-duration:\s*0\.01ms !important/);
  for (const loop of [".mo-skeleton", ".mo-spinner", ".mo-typing i", ".mo-caret", ".mo-pulse"]) {
    assert.ok(css.split("@media (prefers-reduced-motion: reduce)").slice(1).some((chunk) => chunk.includes(loop)), `${loop} sem versão reduced`);
  }
  assert.match(css, /@supports \(animation-timeline: view\(\)\)\s*\{\s*@media \(prefers-reduced-motion: no-preference\)/);
});

test("cada keyframe mo-* declarado é usado no CSS", () => {
  const names = [...css.matchAll(/@keyframes (mo-[\w-]+)/g)].map((m) => m[1]);
  for (const name of names) assert.ok(css.split(name).length > 2, `${name} não usado`);
});

test("sem ms/cubic-bezier literais nas regras (só nos tokens)", () => {
  const rules = css.slice(css.indexOf("/* ---------- Keyframes"));
  const body = rules.replace(/@keyframes[^{]+\{(?:[^{}]|\{[^{}]*\})*\}/g, "");
  assert.doesNotMatch(body, /cubic-bezier\(/);
  assert.doesNotMatch(body.replace(/\b0\.01ms|\b0ms/g, ""), /\b\d+ms\b/);
});

test("componentes só usam primitives exportados e globals importa os tokens", () => {
  assert.match(readFileSync(new URL("../app/globals.css", import.meta.url), "utf8"), /@import "\.\/ui\/motion-tokens\.css"/);
  const index = readFileSync(new URL("../app/ui/index.ts", import.meta.url), "utf8");
  for (const name of ["Skeleton", "Spinner", "ProgressIndicator", "TypingIndicator", "StreamingText", "Transition", "StaggerItem", "Reveal", "ScreenTransition", "EmptyState", "ErrorState", "Toast", "closeDialogAnimated"]) assert.match(index, new RegExp(`\\b${name}\\b`));
  assert.ok(readdirSync(new URL("../app/ui/", import.meta.url)).includes("motion-logic.ts"));
});
