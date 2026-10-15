import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, statSync, symlinkSync, realpathSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Store } from '../src/store.mjs';
import { Engine } from '../src/core.mjs';

const repo = fileURLToPath(new URL('../../../', import.meta.url));
function sandbox(t) { const dir = mkdtempSync(join(realpathSync(tmpdir()), 'wa-poc-test-')); t.after(() => rmSync(dir, { recursive: true, force: true })); return join(dir, 'data'); }
test('refuses data under repo, including symlink aliases', t => {
  assert.throws(() => new Store(join(repo, 'tmp', 'wa-data')), /OUTSIDE_GIT/);
  const path = sandbox(t); symlinkSync(repo, path);
  assert.throws(() => new Store(join(path, 'tmp')), /OUTSIDE_GIT/);
});
test('refuses any other git repository and symlinked state files', t => {
  const path = sandbox(t); mkdirSync(join(path, '.git'), { recursive: true });
  assert.throws(() => new Store(join(path, 'local')), /OUTSIDE_GIT/);
  const s = new Store(sandbox(t)); symlinkSync('/etc/hosts', join(s.root, 'library.private.json'));
  assert.throws(() => s.load(), /UNSAFE_FILE/);
});
test('atomic private snapshot roundtrips and is mode 0600, directory 0700', t => {
  const s = new Store(sandbox(t)), e = new Engine({ mode: 'simulated', selected: ['demo@g.us'] });
  s.save(e); assert.deepEqual(s.load(), e.state);
  assert.equal(statSync(s.root).mode & 0o777, 0o700);
  assert.equal(statSync(join(s.root, 'library.private.json')).mode & 0o777, 0o600);
  assert.equal(JSON.parse(readFileSync(join(s.root, 'report.json'))).validation, 'simulated');
});
test('exclusive lock refuses second writer and releases cleanly', t => {
  const s = new Store(sandbox(t)); s.lock(); assert.throws(() => s.lock(), /ALREADY_RUNNING/);
  s.unlock(); s.lock(); s.unlock();
});
test('store refuses arbitrary nonempty directory', t => {
  const path = sandbox(t); mkdirSync(join(path, 'unrelated'), { recursive: true });
  assert.throws(() => new Store(path), /DEDICATED_DIRECTORY/);
});
test('auth and cache directories cannot redirect credentials through symlinks', t => {
  const s = new Store(sandbox(t)); symlinkSync(repo, join(s.root, 'auth'));
  assert.throws(() => s.directory('auth'), /UNSAFE_DIRECTORY/);
  assert.equal(statSync(s.directory('web-cache')).mode & 0o777, 0o700);
  assert.equal(s.directory('web-cache'), join(s.root, 'web-cache'));
});
