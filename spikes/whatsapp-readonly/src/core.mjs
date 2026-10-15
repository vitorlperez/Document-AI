import { randomBytes, createHmac } from 'node:crypto';

const EVENTS = new Set(['history', 'new', 'edit', 'delete_everyone', 'delete_me']);
export const supportedChat = id => typeof id === 'string' && /@(g\.us|c\.us|lid)$/.test(id);
export function chooseChats(input, chats) {
  const tokens = input.split(',').map(s => s.trim());
  if (!tokens.length || tokens.some(s => !/^[1-9]\d*$/.test(s) || !chats[Number(s) - 1])) throw Error('INVALID_SELECTION');
  return [...new Set(tokens.map(s => chats[Number(s) - 1].id))];
}

// Rejection reasons by stage. Counts only: no ids, chats or text leave the engine.
const NORMALIZATION = ['inspection_failed', 'invalid_message_id', 'identity_conflict', 'unsupported_chat',
  'unsupported_media', 'unsupported_type', 'ephemeral', 'view_once', 'empty_body', 'body_too_large', 'invalid_timestamp'];
const SELECTION = ['unselected_chat'];
const APPLICATION = ['duplicate', 'already_deleted', 'unchanged_edit', 'capacity_reached'];
const MEDIA = new Set(['image', 'video', 'audio', 'ptt', 'document', 'sticker', 'ptv']);
export const emptyCounters = () => ({ received: 0, processed: 0, unprocessed: 0, normalized: 0,
  normalizationRejected: 0, eligible: 0, selectionRejected: 0, applied: 0, applicationRejected: 0,
  retained: 0, tombstoned: 0,
  rejections: Object.fromEntries([...NORMALIZATION, ...SELECTION, ...APPLICATION].map(r => [r, 0])),
  observed: { text: 0, media: 0, revoked: 0, other: 0, pnLidSelectionMismatch: 0 } });
export function addCounters(into, from) {
  for (const [k, v] of Object.entries(from)) {
    if (typeof v === 'number') into[k] = (into[k] ?? 0) + v;
    else addCounters(into[k] ??= {}, v);
  }
  return into;
}

// whatsapp-web.js 1.34.7 reads only _serialized; current WA Web may expose the
// same wid/key only as $1. Every alternative must agree, or identity is rejected.
const CONFLICT = Symbol('conflict');
const keys = v => typeof v === 'string' ? [v] : v && typeof v === 'object'
  ? [v._serialized, v.$1].filter(s => typeof s === 'string') : [];
function identity(...values) {
  const found = new Set(values.flatMap(keys).filter(Boolean));
  return found.size > 1 ? CONFLICT : [...found][0];
}

// No getChat/getContact/downloadMedia: normalization never performs network I/O.
// The chat comes only from the directed endpoint (from, or to when fromMe);
// id.remote can only veto it, and author never authorizes a chat.
export function inspect(raw, { deletion = false, text } = {}) {
  if (!raw || typeof raw !== 'object') return { reason: 'invalid_message_id' };
  const data = raw._data && typeof raw._data === 'object' ? raw._data : {};
  const fromMe = Boolean(raw.fromMe ?? raw.id?.fromMe ?? data.id?.fromMe);
  const dir = fromMe ? 'to' : 'from';
  const own = identity(raw.id, data.id);
  if (own === CONFLICT) return { reason: 'identity_conflict' };
  const endpoint = identity(raw[dir], data[dir]), remote = identity(raw.id?.remote, data.id?.remote);
  if (endpoint === CONFLICT || remote === CONFLICT || (endpoint && remote && endpoint !== remote)) {
    return { reason: 'identity_conflict' };
  }
  let id = own, chatId = endpoint;
  if (deletion) {
    const key = raw.protocolMessageKey ?? data.protocolMessageKey;
    const keyId = identity(key), keyChat = identity(key?.remote);
    if (keyId === CONFLICT || keyChat === CONFLICT) return { reason: 'identity_conflict' };
    id = keyId || id; chatId = keyChat || chatId;
  }
  if (!id) return { reason: 'invalid_message_id' };
  if (!supportedChat(chatId)) return { reason: 'unsupported_chat' };
  if (deletion) return { msg: { id, chatId } };
  if (raw.hasMedia || data.directPath || MEDIA.has(raw.type)) return { reason: 'unsupported_media' };
  if (raw.type !== 'chat') return { reason: 'unsupported_type' };
  if (raw.isEphemeral || data.isEphemeral) return { reason: 'ephemeral' };
  if (raw.isViewOnce || data.isViewOnce) return { reason: 'view_once' };
  const body = text ?? raw.body;
  if (typeof body !== 'string' || !body) return { reason: 'empty_body' };
  if (body.length > 64_000) return { reason: 'body_too_large' };
  if (!Number.isFinite(raw.timestamp) || raw.timestamp <= 0 || raw.timestamp > 8_640_000_000_000) {
    return { reason: 'invalid_timestamp' };
  }
  const author = identity(raw.author, data.author);
  return { msg: { id, chatId, text: body, timestamp: raw.timestamp,
    author: (author !== CONFLICT && author) || (fromMe ? 'self' : chatId), fromMe } };
}
export const normalize = (raw, opts) => inspect(raw, opts).msg ?? null;

function observedKind(raw, deletion) {
  if (deletion || raw?.type === 'revoked') return 'revoked';
  if (raw?.hasMedia || raw?._data?.directPath || MEDIA.has(raw?.type)) return 'media';
  return raw?.type === 'chat' ? 'text' : 'other';
}
const namespace = id => typeof id === 'string' ? id.slice(id.lastIndexOf('@') + 1) : '';

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
    this.state.ingestion ??= {};
    for (const kind of EVENTS) this.state.ingestion[kind] ??= emptyCounters();
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
  apply(kind, msg, opts) { return this.applyResult(kind, msg, opts).ok; }
  applyResult(kind, msg, { baseline } = {}) {
    if (!EVENTS.has(kind)) throw Error('INVALID_EVENT');
    if (!this.ingestionEnabled || !msg) return { ok: false, reason: 'ingestion_disabled' };
    if (!this.state.selected.includes(msg.chatId)) return { ok: false, reason: 'unselected_chat' };
    const key = this.hash(`${msg.chatId}:${msg.id}`), old = this.state.messages[key];
    if (kind.startsWith('delete')) {
      this.state.messages[key] = { chatId: msg.chatId, deleted: true };
      if (!old?.deleted) this.state.events[kind]++;
      return { ok: true, effect: 'tombstoned' };
    }
    const reconcile = old && kind === 'history' && baseline !== undefined &&
      (this.revisions.get(key) ?? 0) <= baseline && old.text !== msg.text;
    if (old?.deleted) return { ok: false, reason: 'already_deleted' };
    if (old?.text === msg.text && kind === 'edit') return { ok: false, reason: 'unchanged_edit' };
    if (old && kind !== 'edit' && !reconcile) return { ok: false, reason: 'duplicate' };
    if (!old && Object.keys(this.state.messages).length >= 50_000) throw Error('LOCAL_CAPACITY_REACHED');
    this.state.messages[key] = { chatId: msg.chatId, timestamp: msg.timestamp, text: msg.text,
      author: `person-${this.hash(msg.author ?? 'unknown')}`, fromMe: msg.fromMe, deleted: false };
    this.revisions.set(key, ++this.revision);
    this.state.events[kind]++;
    return { ok: true, effect: 'retained' };
  }
  // Full pipeline for one raw message with numeric accounting per stage/reason.
  // History passes its own per-call counters; live events count into state.
  ingest(stage, raw, { text, baseline, requested, counters = this.state.ingestion[stage] } = {}) {
    const deletion = stage.startsWith('delete') || (stage === 'history' && raw?.type === 'revoked');
    const kind = deletion && stage === 'history' ? 'delete_everyone' : stage;
    counters.received++; counters.processed++;
    let inspected;
    try {
      counters.observed[observedKind(raw, deletion)]++;
      inspected = inspect(raw, { deletion, text });
    } catch { inspected = { reason: 'inspection_failed' }; }
    const reject = (stageField, reason) => {
      counters[stageField]++; counters.rejections[reason]++; return { ok: false, reason };
    };
    if (!inspected.msg) return reject('normalizationRejected', inspected.reason);
    counters.normalized++;
    if (!this.state.selected.includes(inspected.msg.chatId)) {
      const pair = [namespace(inspected.msg.chatId), namespace(requested)].sort().join('/');
      if (pair === 'c.us/lid') counters.observed.pnLidSelectionMismatch++;
      return reject('selectionRejected', 'unselected_chat');
    }
    counters.eligible++;
    let result;
    try { result = this.applyResult(kind, inspected.msg, { baseline }); }
    catch (error) { reject('applicationRejected', 'capacity_reached'); throw error; }
    if (!result.ok) return reject('applicationRejected', result.reason);
    counters.applied++; counters[result.effect]++;
    return result;
  }
  historyResult(id, data) {
    if (data.ingestion) addCounters(this.state.ingestion.history, data.ingestion);
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
      ingestion: structuredClone(this.state.ingestion),
      ingestionCoverage: { historyMeasured: this.state.history.filter(h => h.ingestion).length,
        historyUnmeasured: this.state.history.filter(h => !h.ingestion).length },
      connection: { ...this.state.connection }, observations: this.state.observations,
      runs: this.state.runs, selections: this.state.selections,
      historyCompleteness: 'unknown; fetch limit is not a completeness guarantee',
      startedAt: this.state.startedAt, generatedAt: new Date().toISOString() };
  }
}
