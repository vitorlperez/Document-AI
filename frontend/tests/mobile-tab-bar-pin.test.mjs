import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../app/mobile-chat.css", import.meta.url), "utf8");
const rule = css.match(/^\.mobile-tab-bar \{([^}]*)\}/m)?.[1] ?? "";

test("a barra de abas do mobile desce para o rodape quando a pagina e curta (margin-top: auto no shell flex)", () => {
  assert.match(rule, /margin-top:\s*auto/);
  assert.match(rule, /position:\s*sticky/);
  assert.match(rule, /bottom:\s*0/);
});
