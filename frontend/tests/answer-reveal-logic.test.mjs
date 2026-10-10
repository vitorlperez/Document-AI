import assert from "node:assert/strict";
import test from "node:test";

import { revealDurationMs, revealPlan, revealedText, revealedUnits } from "../app/answer-reveal-logic.ts";

const prefixes = (text) => revealPlan(text).map((cut) => text.slice(0, cut));

test("revealPlan reveals word by word and always ends with the full text", () => {
  const text = "O prazo final é dia 10.";
  const plan = revealPlan(text);
  assert.equal(plan.length, 6);
  assert.equal(plan.at(-1), text.length);
  assert.deepEqual(plan, [...plan].sort((a, b) => a - b));
  assert.deepEqual(revealPlan(""), []);
});

test("revealPlan never cuts inside a citation marker", () => {
  const text = "A entrega foi definida (fonte 1, 2) em reunião.";
  for (const shown of prefixes(text)) assert.doesNotMatch(shown, /\([^)]*$/, shown);
  assert.ok(prefixes(text).includes("A entrega foi definida (fonte 1, 2) "));
});

test("revealPlan holds back unclosed bold and code spans, then releases them closed", () => {
  const text = "Veja **o prazo final** e `o código` hoje.";
  for (const shown of prefixes(text)) {
    assert.equal(shown.split("**").length % 2, 1, shown);
    assert.equal(shown.split("`").length % 2, 1, shown);
  }
});

test("revealPlan stops holding a span that never closes", () => {
  const text = `**${"palavra ".repeat(30)}fim`;
  assert.ok(revealPlan(text).length > 5);
});

test("revealPlan reveals a table row only once it is complete", () => {
  const text = "| Item | Prazo |\n| --- | --- |\n| Entrega | 10/11 |\nFim";
  for (const shown of prefixes(text)) {
    const last = shown.split("\n").at(-1);
    if (last.trimStart().startsWith("|")) assert.ok(last.trimEnd().endsWith("|") || shown === text, shown);
  }
});

test("revealDurationMs scales with length but is clamped", () => {
  assert.equal(revealDurationMs(3), 700);
  assert.equal(revealDurationMs(50), 1400);
  assert.equal(revealDurationMs(5000), 3600);
});

test("revealedUnits grows with time and completes at the duration", () => {
  assert.equal(revealedUnits(0, 100, 1000), 0);
  assert.equal(revealedUnits(10, 0, 1000), 1);
  assert.equal(revealedUnits(10, 500, 1000), 5);
  assert.equal(revealedUnits(10, 1000, 1000), 10);
  assert.equal(revealedUnits(10, 9999, 1000), 10);
});

test("revealedText slices at the chosen cut and returns the full text when done", () => {
  const text = "um dois três";
  const plan = revealPlan(text);
  assert.equal(revealedText(text, plan, 0), "");
  assert.equal(revealedText(text, plan, 2), "um dois ");
  assert.equal(revealedText(text, plan, plan.length), text);
});
