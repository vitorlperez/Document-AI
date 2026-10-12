import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
const read = (file) => readFileSync(new URL(`../app/${file}`, import.meta.url), 'utf8');

test('lane 6 data loading has accessible skeletons instead of bare text', () => {
  for (const file of ['access-settings.tsx', 'product/developer-screen.tsx', 'product/team-staff.tsx', 'product/profile-screen.tsx']) {
    const source = read(file);
    assert.match(source, /<LoadingBlock/);
    assert.match(source, /<Skeleton/);
    assert.doesNotMatch(source, /<p[^>]*>Carregando/);
  }
});
test('secret dismissal clears sensitive state and restores focus with a safe fallback', () => {
  const source = read('access-settings.tsx');
  assert.match(source, /setSecret\(null\); setCopied\(false\);/);
  assert.match(source, /button && !button.disabled/);
  assert.match(source, /else heading.current\?\.focus\(\)/);
  assert.match(source, /Chave copiada para a área de transferência/);
});
test('login navigation avoids lazy next links and pending submit is announced', () => {
  const source = read('product/custom-login.tsx');
  assert.doesNotMatch(source, /next\/link|<Link/);
  assert.match(source, /<Enter key=\{mode\}/);
  assert.match(source, /<Spinner/);
  assert.match(source, /role="status"[^>]*>\{busy/);
});
test('tour spotlight only animates opacity and transform and keeps step controls mounted', () => {
  const source = read('conversation-tour.tsx');
  assert.match(source, /<Enter key=\{step.target\}/);
  assert.match(source, /<ProgressIndicator/);
  assert.match(source, /tour-highlight-fallback/);
  assert.doesNotMatch(source, /transition:.*(?:top|left|width|height)/);
  assert.match(source, /primary.current\?\.focus\(\)/);
});
