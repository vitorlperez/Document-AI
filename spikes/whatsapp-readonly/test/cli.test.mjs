import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, rmSync, readFileSync, existsSync, realpathSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const cli = fileURLToPath(new URL('../src/cli.mjs', import.meta.url));
function run(t, args) {
  const root = mkdtempSync(join(realpathSync(tmpdir()), 'wa-cli-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const env = { ...process.env, ARQUIVIO_WA_POC_HOME: join(root, 'data') };
  return { root: env.ARQUIVIO_WA_POC_HOME, env, result: spawnSync(process.execPath, [cli, ...args], { env, encoding: 'utf8' }) };
}
test('live refuses no-consent/non-TTY before data directory or client is created', t => {
  for (const args of [['live'], ['live', '--consent']]) {
    const { root, result } = run(t, args);
    assert.equal(result.status, 1); assert.match(result.stderr, /LIVE_REQUIRES_TTY_AND_CONSENT/);
    assert.equal(existsSync(root), false);
  }
});
test('CLI fixture to disk to report works offline; removed/unselected content is absent', t => {
  const { root, env, result } = run(t, ['demo']);
  assert.equal(result.status, 0);
  const report = JSON.parse(result.stdout);
  assert.equal(report.retainedMessages, 2); assert.equal(report.tombstones, 1);
  assert.equal(report.documents, 2); assert.equal(report.realIntegrationValidated, false);
  const disk = readFileSync(join(root, 'simulated', 'library.private.json'), 'utf8');
  for (const forbidden of ['UNSELECTED_FIXTURE_MUST_NOT_PERSIST', 'Orçamento fictício aprovado.', 'Não deve ressuscitar.']) assert.ok(!disk.includes(forbidden));
  const reported = spawnSync(process.execPath, [cli, 'report'], { env, encoding: 'utf8' });
  assert.equal(reported.status, 0); assert.equal(JSON.parse(reported.stdout).retainedMessages, 2);
  assert.equal(existsSync(join(root, 'real')), false);
});
