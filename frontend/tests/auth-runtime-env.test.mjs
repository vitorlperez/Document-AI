import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

test("runtime bridges auth settings as hidden bindings, never secret CLI arguments", () => {
  const script = fileURLToPath(new URL("../scripts/sites-env.mjs", import.meta.url));
  const secret = "test-only-proxy-secret-at-least-32-chars";
  const probe = `
    const fs = await import('node:fs');
    const fileIndex = process.argv.indexOf('--env-file');
    const file = fileIndex >= 0 ? process.argv[fileIndex + 1] : null;
    const content = file ? fs.readFileSync(file, 'utf8') : '';
    console.log(JSON.stringify({
      hasFile: !!file, secretInArgs: process.argv.some(x => x.includes(process.env.AUTH_PROXY_SECRET)),
      mode: file ? fs.statSync(file).mode & 0o777 : null,
      hasSecret: content.includes(process.env.AUTH_PROXY_SECRET), hasSource: content.includes('AUTH_CLIENT_IP_SOURCE='),
      unrelatedSecret: content.includes('UNRELATED_SECRET='),
    }));
  `;
  const result = spawnSync(process.execPath, ["--import", script, "--eval", probe], {
    encoding: "utf8", env: { ...process.env, AUTH_PROXY_SECRET: secret, AUTH_CLIENT_IP_SOURCE: "railway", UNRELATED_SECRET: "do-not-copy" },
  });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout), { hasFile: true, secretInArgs: false, mode: 0o600, hasSecret: true, hasSource: true, unrelatedSecret: false });
});
