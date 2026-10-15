// Closed vocabulary: never redact-and-print an arbitrary message, stack or payload.
const stages = new Set(['make_client', 'initialize', 'authenticated', 'ready', 'setup_callback',
  'list_chats', 'selection', 'confirmation', 'destroy', 'session_profile', 'reuse_auth']);
const events = new Set(['started', 'reached', 'failed']);
const types = new Set(['Error', 'TypeError', 'RangeError', 'SyntaxError', 'TimeoutError', 'ProtocolError', 'TargetCloseError']);
const codes = new Set(['ENOENT', 'EACCES', 'EPERM', 'ENOSPC', 'EEXIST', 'EMFILE', 'EIO']);

export function safeDiagnostic(stage, event, error) {
  const record = { stage: stages.has(stage) ? stage : 'unknown', event: events.has(event) ? event : 'unknown' };
  if (event !== 'failed') return record;
  record.error = { type: 'unknown', kind: 'UNCLASSIFIED', code: 'unknown', frames: [] };
  try {
    // Read each field once: getters must not replace an allowlisted value after validation.
    const rawMessage = typeof error === 'string' ? error : error?.message;
    const rawStack = error?.stack, rawType = error?.name, rawCode = error?.code;
    const message = typeof rawMessage === 'string' ? rawMessage : '';
    const stack = typeof rawStack === 'string' ? rawStack : '';
    const type = types.has(rawType) ? rawType : 'unknown';
    const code = codes.has(rawCode) ? rawCode : 'unknown';
    let kind = 'UNCLASSIFIED';
    if (/^r(?:: r)?$/.test(message)) kind = 'OPAQUE_WEB_ERROR';
    else if (message.includes('Failed to add page binding') && message.includes('already exists')) kind = 'BINDING_ALREADY_EXISTS';
    else if (/user data directory is already in use|browser is already running|ProcessSingleton/i.test(message)) kind = 'PROFILE_IN_USE';
    else if (message === 'auth timeout') kind = 'AUTH_TIMEOUT';
    else if (type === 'TimeoutError') kind = 'TIMEOUT';
    else if (message.includes('Evaluation failed')) kind = 'WEB_EVALUATION';
    else if (message.includes('Execution context was destroyed')) kind = 'CONTEXT_DESTROYED';
    else if (type === 'TargetCloseError') kind = 'TARGET_CLOSED';
    else if (code !== 'unknown') kind = 'LOCAL_IO';
    const frames = ['Client.initialize', 'Client.inject', 'Client.getChats', 'ExecutionContext.evaluate']
      .filter(frame => stack.includes(frame));
    record.error = { type, kind, code, frames };
  } catch { /* Even exceptions with throwing getters get a fixed, safe diagnostic. */ }
  return record;
}

export async function setupStep(diagnostic, stage, operation) {
  diagnostic(safeDiagnostic(stage, 'started'));
  try {
    const value = await operation();
    diagnostic(safeDiagnostic(stage, 'reached'));
    return value;
  } catch (error) {
    diagnostic(safeDiagnostic(stage, 'failed', error));
    throw error;
  }
}

export const diagnosticLogger = log => record => log(`SETUP_DIAGNOSTIC ${JSON.stringify(record)}`);
