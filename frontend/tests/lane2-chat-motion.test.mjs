import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
test('a espera da resposta reserva mensagem e fontes, sem depender de streaming do backend', () => {
  const chat = read('product/chat-workspace.tsx');
  assert.match(chat, /message\.pending \? <PendingAnswer/);
  assert.match(chat, /<TypingIndicator label="Pensando na sua resposta…"/);
  assert.match(chat, /<SkeletonList rows=/);
  assert.match(chat, /useAnswerReveal\(fullText, animate/);
});
test('o reveal mantém o markdown inerte e usa cursor sólido da fundação', () => {
  const chat = read('product/chat-workspace.tsx');
  assert.match(chat, /inert={!reveal\.done}/);
  assert.match(chat, /<StreamingText state={reveal\.done \? "done" : "streaming"}/);
  assert.doesNotMatch(read('chat-workspace.css'), /@keyframes answer-caret/);
});
test('o menu de exportação devolve foco e desativa conteúdo durante saída', () => {
  const actions = read('answer-actions.tsx');
  assert.match(actions, /event\.key === "Escape"/);
  assert.match(actions, /trigger\.current\?\.focus/);
  assert.match(actions, /inert={!menu}/);
  assert.match(actions, /<Transition show={menu}/);
});
test('reduced motion reage a mudanças durante reveal e consulta às fontes', () => {
  assert.match(read('answer-reveal.tsx'), /const reduced = useReducedMotion\(\)/);
  assert.match(read('source-reading.tsx'), /const reduced = useReducedMotion\(\)/);
});
test('a grade da sidebar preserva a terceira coluna do viewer independente da ordem do CSS', () => {
  assert.match(read('tools-sidebar.css'), /grid-template-columns: var\(--tools-sidebar-width\) minmax\(0, 1fr\) var\(--file-viewer-col, 0px\)/);
});
