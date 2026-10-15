import { existsSync, mkdirSync, realpathSync, readdirSync, chmodSync, lstatSync,
  readFileSync, writeFileSync, renameSync, unlinkSync, openSync, closeSync, fsyncSync } from 'node:fs';
import { dirname, join, relative, resolve, sep, isAbsolute } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';

const REPO = realpathSync(fileURLToPath(new URL('../../../', import.meta.url)));
const inside = (parent, path) => path === parent || path.startsWith(parent + sep);
function canonical(path) {
  if (existsSync(path)) return realpathSync(path);
  const parent = dirname(path);
  if (parent === path) return path;
  return resolve(canonical(parent), relative(parent, path));
}
function safeFile(path) {
  let stat;
  try { stat = lstatSync(path); } catch (error) { if (error.code === 'ENOENT') return; throw error; }
  if (!stat.isFile() || stat.isSymbolicLink()) throw Error('UNSAFE_FILE');
}
const sameFile = (a, b) => a.dev === b.dev && a.ino === b.ino;
function ownerAlive(pid) {
  try { process.kill(pid, 0); return true; }
  catch (error) { if (error.code === 'ESRCH') return false; return true; }
}
export class Store {
  constructor(root) {
    if (!isAbsolute(root)) throw Error('ABSOLUTE_DATA_DIR_REQUIRED');
    this.root = canonical(resolve(root)); this.ownsLock = false;
    if (inside(REPO, this.root) || this.root === homedir() || dirname(this.root) === this.root) throw Error('OUTSIDE_GIT_REQUIRED');
    for (let p = this.root; ; p = dirname(p)) {
      if (existsSync(join(p, '.git'))) throw Error('OUTSIDE_GIT_REQUIRED');
      if (dirname(p) === p) break;
    }
    if (existsSync(this.root) && readdirSync(this.root).length && !existsSync(join(this.root, '.arquivio-wa-poc'))) throw Error('DEDICATED_DIRECTORY_REQUIRED');
    mkdirSync(this.root, { recursive: true, mode: 0o700 }); chmodSync(this.root, 0o700);
    // Never replace the marker or create a shared .tmp before acquiring the lock.
    const marker = join(this.root, '.arquivio-wa-poc'); safeFile(marker);
    try { writeFileSync(marker, '{"schema":1}\n', { flag: 'wx', mode: 0o600 }); }
    catch (error) { if (error.code !== 'EEXIST') throw error; }
  }
  write(name, value) {
    if (!this.ownsLock) throw Error('LOCK_REQUIRED');
    const dest = join(this.root, name), tmp = dest + '.tmp';
    safeFile(dest); safeFile(tmp);
    // O_EXCL also refuses dangling symlinks. No credentials/content on stdout.
    const fd = openSync(tmp, 'wx', 0o600);
    try { writeFileSync(fd, JSON.stringify(value, null, 2) + '\n'); fsyncSync(fd); }
    finally { closeSync(fd); }
    renameSync(tmp, dest);
  }
  load() {
    const path = join(this.root, 'library.private.json'); safeFile(path);
    return existsSync(path) ? JSON.parse(readFileSync(path, 'utf8')).state : undefined;
  }
  directory(name) {
    if (!['auth', 'web-cache'].includes(name)) throw Error('UNSAFE_DIRECTORY');
    const path = join(this.root, name);
    if (existsSync(path) && (lstatSync(path).isSymbolicLink() || !lstatSync(path).isDirectory())) throw Error('UNSAFE_DIRECTORY');
    mkdirSync(path, { recursive: true, mode: 0o700 }); chmodSync(path, 0o700);
    return path;
  }
  lock() {
    if (this.ownsLock) throw Error('ALREADY_RUNNING');
    const path = join(this.root, 'run.lock'), guard = join(this.root, 'run.lock.guard');
    // Every contender must hold this exclusive guard before inspecting/removing a
    // dead owner's lock. A second reaper cannot unlink the new owner's lock.
    // Never auto-reap this short-lived guard: a crash inside recovery fails closed.
    safeFile(guard);
    let fd;
    try { fd = openSync(guard, 'wx', 0o600); }
    catch (error) { if (error.code === 'EEXIST') throw Error('LOCK_RECOVERY_BUSY'); throw error; }
    try {
      writeFileSync(fd, String(process.pid));
      safeFile(path);
      if (existsSync(path)) {
        const text = readFileSync(path, 'utf8');
        const pid = Number(text);
        if (!/^[1-9]\d*$/.test(text) || !Number.isSafeInteger(pid) || pid > 2_147_483_647) throw Error('LOCK_OWNER_UNKNOWN');
        if (ownerAlive(pid)) throw Error('ALREADY_RUNNING');
        unlinkSync(path); this.recoveredLock = true;
      }
      writeFileSync(path, String(process.pid), { flag: 'wx', mode: 0o600 });
      this.lockIdentity = lstatSync(path); this.ownsLock = true;
      this.recoveredTemps = [];
      for (const name of ['.arquivio-wa-poc.tmp', 'library.private.json.tmp', 'report.json.tmp']) {
        const tmp = join(this.root, name); safeFile(tmp);
        if (existsSync(tmp)) { unlinkSync(tmp); this.recoveredTemps.push(name); }
      }
    } catch (error) { this.unlock(); throw error; }
    finally { closeSync(fd); unlinkSync(guard); }
  }
  unlock() {
    if (this.ownsLock) {
      const path = join(this.root, 'run.lock'); safeFile(path);
      // Never delete a replacement file, including after accidental external changes.
      if (existsSync(path) && sameFile(this.lockIdentity, lstatSync(path)) &&
          readFileSync(path, 'utf8') === String(process.pid)) unlinkSync(path);
      this.ownsLock = false;
    }
  }
  save(engine) {
    // Canonical state and every derived text block are replaced in ONE atomic file.
    this.write('library.private.json', { state: engine.state, documents: engine.library() });
    this.write('report.json', engine.report());
  }
}
