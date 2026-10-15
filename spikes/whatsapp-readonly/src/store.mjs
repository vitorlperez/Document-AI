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
  if (existsSync(path) && (!lstatSync(path).isFile() || lstatSync(path).isSymbolicLink())) throw Error('UNSAFE_FILE');
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
    this.write('.arquivio-wa-poc', { schema: 1 });
  }
  write(name, value) {
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
    try { writeFileSync(join(this.root, 'run.lock'), String(process.pid), { flag: 'wx', mode: 0o600 }); }
    catch { throw Error('ALREADY_RUNNING'); }
    this.ownsLock = true;
  }
  unlock() { if (this.ownsLock) { unlinkSync(join(this.root, 'run.lock')); this.ownsLock = false; } }
  save(engine) {
    // Canonical state and every derived text block are replaced in ONE atomic file.
    this.write('library.private.json', { state: engine.state, documents: engine.library() });
    this.write('report.json', engine.report());
  }
}
