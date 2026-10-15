import { randomBytes, createHmac } from 'node:crypto';

const EVENTS = new Set(['history', 'new', 'edit', 'delete_everyone', 'delete_me']);
export const supportedChat = id => typeof id === 'string' && /@(g\.us|c\.us|lid)$/.test(id);
export function chooseChats(input, chats) {
  const tokens = input.split(',').map(s => s.trim());
  if (!tokens.length || tokens.some(s => !/^[1-9]\d*$/.test(s) || !chats[Number(s) - 1])) throw Error('INVALID_SELECTION');
  return [...new Set(tokens.map(s => chats[Number(s) - 1].id))];
}

// No getChat/getContact/downloadMedia: normalization never performs network I/O.
export function normalize(raw, { deletion = false, text } = {}) {
  if (!raw || typeof raw !== 'object') return null;
  const id = (deletion && raw.protocolMessageKey?._serialized) || raw.id?._serialized;
  const chatId = (deletion && (typeof raw.protocolMessageKey?.remote === 'string'
    ? raw.protocolMessageKey.remote : raw.protocolMessageKey?.remote?._serialized)) || (raw.fromMe ? raw.to : raw.from);
  if (!id || typeof id !== 'string' || !supportedChat(chatId)) return null;
  if (deletion) return { id, chatId };
  if (raw.type !== 'chat' || raw.isEphemeral || raw.isViewOnce || raw._data?.isEphemeral || raw._data?.isViewOnce) return null;
  const body = text ?? raw.body;
  if (typeof body !== 'string' || !body || body.length > 64_000 ||
      !Number.isFinite(raw.timestamp) || raw.timestamp <= 0 || raw.timestamp > 8_640_000_000_000) return null;
  return { id, chatId, text: body, timestamp: raw.timestamp,
    author: raw.author || (raw.fromMe ? 'self' : raw.from), fromMe: Boolean(raw.fromMe) };
}

export class Engine {
  constructor({ mode, snapshot, selected = [] } = {}) {
    if (!['simulated', 'real'].includes(mode)) throw Error('INVALID_MODE');
    if (snapshot && (snapshot.schema !== 1 || snapshot.mode !== mode)) throw Error('INCOMPATIBLE_STATE');
    this.revision = 0; this.revisions = new Map();
    this.state = snapshot ?? { schema: 1, mode, salt: randomBytes(32).toString('hex'), selected: [],
      messages: {}, events: { history: 0, new: 0, edit: 0, delete_everyone: 0, delete_me: 0 },
      history: [], catalog: { chats: 0, groups: 0, individual: 0 },
      connection: { ready: 0, disconnected: 0, authFailure: 0, reconnectAttempts: 0 },
      observations: [], startedAt: new Date().toISOString() };
    this.ingestionEnabled = true;
    this.state.chatAliases ??= Object.fromEntries(this.state.selected.map((id, i) => [id, `chat-${i + 1}`]));
    this.state.runs ??= [];
    this.state.selections ??= [];
    for (const row of [...this.state.history, ...this.state.observations]) {
      row.runId ??= 'legacy'; row.selectionId ??= 'legacy';
    }
    if (!snapshot) this.select(selected);
  }
  hash(s) { return createHmac('sha256', this.state.salt).update(s).digest('hex').slice(0, 24); }
  alias(id) {
    return this.state.chatAliases[id] ??= `chat-${Object.keys(this.state.chatAliases).length + 1}`;
  }
  beginRun({ durationMinutes }) {
    // The persisted selection remains available for materialization, never authorization.
    this.ingestionEnabled = false; this.selectionId = undefined;
    this.run = { id: `run-${randomBytes(8).toString('hex')}`, startedAt: new Date().toISOString(),
      durationMinutes, status: 'running' };
    this.state.runs.push(this.run);
  }
  endRun(status) {
    this.ingestionEnabled = false;
    if (this.run) Object.assign(this.run, { status, endedAt: new Date().toISOString() });
  }
  provenance() { return { runId: this.run?.id ?? 'legacy', selectionId: this.selectionId ?? 'legacy' }; }
  select(ids) {
    if (!Array.isArray(ids) || ids.some(id => !supportedChat(id))) throw Error('INVALID_CHAT');
    this.state.selected = [...new Set(ids)];
    for (const [key, msg] of Object.entries(this.state.messages)) {
      if (!ids.includes(msg.chatId)) delete this.state.messages[key];
    }
    this.ingestionEnabled = ids.length > 0;
    this.selectionId = `selection-${this.state.selections.length + 1}`;
    this.state.selections.push({ id: this.selectionId, runId: this.run?.id ?? 'legacy',
      chats: this.state.selected.map(id => this.alias(id)), at: new Date().toISOString() });
  }
  apply(kind, msg, { baseline } = {}) {
    if (!EVENTS.has(kind)) throw Error('INVALID_EVENT');
    if (!this.ingestionEnabled || !msg || !this.state.selected.includes(msg.chatId)) return false;
    const key = this.hash(`${msg.chatId}:${msg.id}`), old = this.state.messages[key];
    if (kind.startsWith('delete')) {
      this.state.messages[key] = { chatId: msg.chatId, deleted: true };
      if (!old?.deleted) this.state.events[kind]++;
      return true;
    }
    const reconcile = old && kind === 'history' && baseline !== undefined &&
      (this.revisions.get(key) ?? 0) <= baseline && old.text !== msg.text;
    if (old?.deleted || (old && kind !== 'edit' && !reconcile)) return false;
    if (!old && Object.keys(this.state.messages).length >= 50_000) throw Error('LOCAL_CAPACITY_REACHED');
    if (old?.text === msg.text && kind === 'edit') return false;
    this.state.messages[key] = { chatId: msg.chatId, timestamp: msg.timestamp, text: msg.text,
      author: `person-${this.hash(msg.author ?? 'unknown')}`, fromMe: msg.fromMe, deleted: false };
    this.revisions.set(key, ++this.revision);
    this.state.events[kind]++;
    return true;
  }
  historyResult(id, data) {
    this.state.history.push({ ...data, chat: this.alias(id), ...this.provenance(), complete: false });
  }
  observe(scenario, result) {
    if (!['listing', 'selection', 'history', 'new', 'edit', 'delete', 'reconnect', 'restart', 'logout'].includes(scenario) ||
      !['pass', 'fail'].includes(result)) throw Error('INVALID_OBSERVATION');
    this.state.observations.push({ scenario, result, ...this.provenance(), source: 'human_assertion', at: new Date().toISOString() });
  }
  library() {
    const docs = new Map();
    for (const [key, m] of Object.entries(this.state.messages)) {
      if (m.deleted || !this.state.selected.includes(m.chatId)) continue;
      const chat = this.alias(m.chatId);
      const day = new Date(m.timestamp * 1000).toISOString().slice(0, 10), id = `${chat}/${day}`;
      if (!docs.has(id)) docs.set(id, { id, source_url: `arquivio-poc://whatsapp/${id}`,
        section_path: `${chat} / ${day}`, untrusted: true, blocks: [] });
      docs.get(id).blocks.push({ id: key, at: new Date(m.timestamp * 1000).toISOString(),
        author: m.author, text: m.text, untrusted: true });
    }
    return [...docs.values()].sort((a, b) => a.id.localeCompare(b.id)).map(doc => ({ ...doc,
      blocks: doc.blocks.sort((a, b) => a.at.localeCompare(b.at) || a.id.localeCompare(b.id)) }));
  }
  report() {
    const live = Object.values(this.state.messages).filter(m => !m.deleted);
    return { schema: 1, validation: this.state.mode === 'real' ? 'real_observations_pending_review' : 'simulated',
      realIntegrationValidated: false, selectedChats: this.state.selected.length,
      retainedMessages: live.length, tombstones: Object.values(this.state.messages).filter(m => m.deleted).length,
      documents: this.library().length, events: { ...this.state.events }, catalog: this.state.catalog, history: this.state.history,
      connection: { ...this.state.connection }, observations: this.state.observations,
      runs: this.state.runs, selections: this.state.selections,
      historyCompleteness: 'unknown; fetch limit is not a completeness guarantee',
      startedAt: this.state.startedAt, generatedAt: new Date().toISOString() };
  }
}
