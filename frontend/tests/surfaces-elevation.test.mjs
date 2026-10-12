import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const globals = readFileSync(new URL("../app/globals.css", import.meta.url), "utf8");
const surfaces = readFileSync(new URL("../app/surfaces.css", import.meta.url), "utf8");

function block(start) {
  const i = globals.indexOf(start);
  return globals.slice(i, globals.indexOf("\n}\n", i));
}
const light = block(":root {");
const dark = block(".dark {");
const get = (blk, name) => blk.match(new RegExp(`\\n\\s*${name}: ([^;]+);`))?.[1].trim();
function hex(blk, name, base) {
  let v = get(blk, name) ?? (base && get(base, name));
  for (let i = 0; v?.startsWith("var("); i++) v = get(blk, v.slice(6, -1)) ?? get(base ?? blk, v.slice(6, -1));
  return v;
}
const lum = (h) => {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };

for (const [name, blk, base] of [["claro", light, undefined], ["escuro", dark, light]]) {
  test(`superfícies (${name}): níveis definidos e distintos`, () => {
    const levels = ["--surface-canvas", "--surface", "--surface-sunken", "--surface-raised", "--surface-overlay"].map((t) => hex(blk, t, base));
    levels.forEach((v) => assert.match(v, /^#[0-9a-f]{6}$/i));
    assert.ok(new Set(levels.map((v) => v.toLowerCase())).size >= (name === "claro" ? 3 : 5), `níveis colapsaram: ${levels}`);
    for (const e of ["--elev-1", "--elev-2", "--elev-3", "--elev-inset"]) assert.ok(get(blk, e) ?? (base && get(base, e)), e);
  });

  test(`contraste AA do texto nas superfícies (${name})`, () => {
    for (const s of ["--surface-canvas", "--surface", "--surface-sunken", "--surface-raised", "--surface-overlay"]) {
      const bg = hex(blk, s, base);
      assert.ok(ratio(hex(blk, "--foreground", base), bg) >= 4.5, `foreground em ${s}`);
      assert.ok(ratio(hex(blk, "--muted-foreground", base), bg) >= 4.5, `muted em ${s}: ${ratio(hex(blk, "--muted-foreground", base), bg).toFixed(2)}`);
    }
  });

  test(`bordas perceptíveis (${name})`, () => {
    const surface = hex(blk, "--surface", base);
    assert.ok(ratio(hex(blk, "--control-edge", base), hex(blk, "--surface-sunken", base)) >= 3, "borda de controle ≥ 3:1");
    assert.ok(ratio(hex(blk, "--edge-subtle", base), surface) >= 1.25, "borda sutil visível");
    assert.ok(ratio(hex(blk, "--edge-strong", base), surface) > ratio(hex(blk, "--edge-subtle", base), surface), "forte > sutil");
  });
}

test("surfaces.css: seletores com bump de especificidade, sem ms/cubic-bezier literais", () => {
  assert.doesNotMatch(surfaces, /\d+ms|cubic-bezier/);
  assert.match(surfaces, /var\(--elev-3\)/);
  assert.match(surfaces, /\.integration-tool-card:hover/);
  assert.match(surfaces, /prefers-reduced-motion: reduce/);
});

test("globals importa surfaces.css", () => assert.match(globals, /@import "\.\/surfaces\.css"/));
