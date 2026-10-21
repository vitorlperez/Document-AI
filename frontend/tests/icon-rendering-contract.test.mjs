import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

// Contrato de renderização dos ícones: traço constante em pixel de tela e tamanhos inteiros pares.
const root = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");
const tracked = (...globs) => execFileSync("git", ["ls-files", ...globs], { cwd: root, encoding: "utf8" }).split("\n").filter((f) => f && !/ \d\./.test(f));

test("o CSS central de ícones fixa o traço em largura de tela", () => {
  const css = read("app/ui/icons.css");
  assert.match(css, /svg\.lucide\s*\{[^}]*stroke-width:\s*var\(--icon-stroke\)/s);
  assert.match(css, /vector-effect:\s*non-scaling-stroke/);
  assert.match(css, /--icon-stroke:\s*1\.5px/);
  assert.match(css, /--icon-stroke-lg:\s*2px/);
  assert.match(css, /svg\.lucide\s*\{[^}]*flex-shrink:\s*0/s);
  assert.match(read("app/globals.css"), /@import "\.\/ui\/icons\.css";/);
});

test("nenhum ícone declara tamanho ímpar em size={…}", () => {
  const offenders = [];
  for (const file of tracked("app/*.tsx", "app/**/*.tsx", "components/**/*.tsx")) {
    read(file).split("\n").forEach((line, index) => {
      for (const match of line.matchAll(/\bsize=\{(\d+)\}/g)) if (Number(match[1]) % 2 !== 0) offenders.push(`${file}:${index + 1} size={${match[1]}}`);
    });
  }
  assert.deepEqual(offenders, []);
});

test("ícones lucide não carregam strokeWidth próprio (o traço vem do CSS central)", () => {
  const offenders = [];
  for (const file of tracked("app/*.tsx", "app/**/*.tsx", "components/**/*.tsx")) {
    read(file).split("\n").forEach((line, index) => { if (/\bstrokeWidth=\{/.test(line) && !/<svg\b/.test(line)) offenders.push(`${file}:${index + 1}`); });
  }
  assert.deepEqual(offenders, []);
});

test("tamanhos de ícone em CSS são pares", () => {
  for (const file of ["app/brand.css", "app/landing.css"]) {
    for (const match of read(file).matchAll(/arquivio-brand[^{]*>\s*svg[^{]*\{([^}]*)\}/g)) {
      for (const size of match[1].matchAll(/(?:width|height):\s*(\d+)px/g)) assert.equal(Number(size[1]) % 2, 0, `${file}: ${size[0]}`);
    }
  }
});
