import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, readFileSync, statSync, symlinkSync, realpathSync, mkdirSync, writeFileSync, existsSync } from 'node:fs';
import { spawn, spawnSync } from 'node:child_process';
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
  s.lock(); t.after(() => s.unlock());
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

test('recovers dead PID and known orphan tmp files while preserving committed evidence', async t => {
  const child = spawnSync(process.execPath, ['-e', '']); assert.equal(child.status, 0);
  const s = new Store(sandbox(t)), e = new Engine({ mode: 'simulated' });
  s.lock(); s.save(e); s.unlock();
  writeFileSync(join(s.root, 'run.lock'), String(child.pid));
  for (const name of ['library.private.json.tmp', 'report.json.tmp', '.arquivio-wa-poc.tmp']) writeFileSync(join(s.root, name), 'incomplete');
  writeFileSync(join(s.root, 'unrelated.tmp'), 'preserve');
  const recovered = new Store(s.root); recovered.lock();
  assert.equal(recovered.recoveredLock, true);
  assert.deepEqual(recovered.load(), e.state);
  assert.equal(existsSync(join(s.root, 'library.private.json.tmp')), false);
  assert.equal(existsSync(join(s.root, 'report.json.tmp')), false);
  assert.equal(existsSync(join(s.root, 'unrelated.tmp')), true);
  recovered.unlock();
});

test('active and uncertain locks are never removed and tmp cleanup waits for ownership', t => {
  const s = new Store(sandbox(t)); s.lock();
  writeFileSync(join(s.root, 'library.private.json.tmp'), 'keep');
  const second = new Store(s.root);
  assert.throws(() => second.lock(), /ALREADY_RUNNING/);
  assert.equal(readFileSync(join(s.root, 'run.lock'), 'utf8'), String(process.pid));
  assert.equal(readFileSync(join(s.root, 'library.private.json.tmp'), 'utf8'), 'keep');
  s.unlock();
  writeFileSync(join(s.root, 'run.lock'), 'not-a-pid');
  assert.throws(() => second.lock(), /LOCK_OWNER_UNKNOWN/);
  assert.equal(readFileSync(join(s.root, 'run.lock'), 'utf8'), 'not-a-pid');
});

test('concurrent recovery contenders permit exactly one writer', async t => {
  const dead = spawnSync(process.execPath, ['-e', '']);
  const s = new Store(sandbox(t));
  writeFileSync(join(s.root, 'run.lock'), String(dead.pid));
  const module = new URL('../src/store.mjs', import.meta.url).href;
  const children = Array.from({ length: 6 }, () => spawn(process.execPath, ['--input-type=module', '-e',
    `import { Store } from ${JSON.stringify(module)}; const s = new Store(process.argv[1]);
     try { s.lock(); process.send('locked'); } catch { process.send('refused'); }
     process.on('message', () => { s.unlock(); process.exit(0); });`, s.root], { stdio: ['ignore', 'ignore', 'pipe', 'ipc'] }));
  t.after(() => children.forEach(c => c.kill()));
  const outcomes = await Promise.all(children.map(c => new Promise((resolve, reject) => {
    c.once('message', resolve); c.once('error', reject); c.once('exit', code => { if (code) reject(Error(`child exit ${code}`)); });
  })));
  assert.equal(outcomes.filter(x => x === 'locked').length, 1);
  await Promise.all(children.map(c => new Promise(resolve => { c.once('exit', resolve); c.send('exit'); })));
});

test('recovery guard fails closed even for a dead PID and does not touch active lock', t => {
  const dead = spawnSync(process.execPath, ['-e', '']);
  const s = new Store(sandbox(t)); s.lock();
  writeFileSync(join(s.root, 'run.lock.guard'), String(dead.pid));
  const other = new Store(s.root);
  assert.throws(() => other.lock(), /LOCK_RECOVERY_BUSY/);
  assert.equal(readFileSync(join(s.root, 'run.lock'), 'utf8'), String(process.pid));
  assert.equal(readFileSync(join(s.root, 'run.lock.guard'), 'utf8'), String(dead.pid));
  s.unlock();
});

test('dangling symlink tmp is refused without following or deleting it', t => {
  const s = new Store(sandbox(t));
  const tmp = join(s.root, 'library.private.json.tmp');
  symlinkSync(join(s.root, 'missing'), tmp);
  assert.throws(() => s.lock(), /UNSAFE_FILE/);
  assert.equal(s.ownsLock, false); assert.equal(existsSync(join(s.root, 'run.lock')), false);
});
