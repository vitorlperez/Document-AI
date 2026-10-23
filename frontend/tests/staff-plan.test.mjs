import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { canManageComps, staffPlanTitle, buildCompBody, buildLimitsOverride, expiryToIso, extendBody, plansForAccountType, compWarningMessage, seatsLabel } from '../app/product/staff-plan-logic.mjs';
const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), 'utf8');
const now = new Date('2026-10-23T00:00:00Z');
test('plano filtrado pelo tipo da conta', () => {
  const plans = [{ plan_key: 'personal_pro', account_type: 'personal' }, { plan_key: 'business_team', account_type: 'business' }];
  assert.deepEqual(plansForAccountType(plans, 'business').map((p) => p.plan_key), ['business_team']);
});
test('motivo obrigatório, ≤240, validade ou permanente explícito', () => {
  assert.match(buildCompBody({ planKey: 'business_team', reason: ' ', permanent: true, now }).error, /motivo/);
  assert.match(buildCompBody({ planKey: 'business_team', reason: 'x'.repeat(241), permanent: true, now }).error, /240/);
  assert.match(buildCompBody({ planKey: 'business_team', reason: 'ok', permanent: false, expiresDate: '', now }).error, /validade/);
  assert.match(buildCompBody({ planKey: 'business_team', reason: 'ok', expiresDate: '2026-01-01', now }).error, /futura/);
  assert.deepEqual(buildCompBody({ planKey: 'business_team', reason: 'ok', permanent: true, now }).body, { plan_key: 'business_team', reason: 'ok', permanent: true });
  const dated = buildCompBody({ planKey: 'business_team', reason: 'ok', expiresDate: '2026-12-31', now }).body;
  assert.equal(dated.expires_at, '2026-12-31T23:59:59.000Z'); assert.equal(dated.permanent, undefined);
});
test('overrides: número, ilimitado, vazio e erro', () => {
  assert.deepEqual(buildLimitsOverride({ max_members: '10', max_spaces: 'ilimitado', max_api_keys: '' }).value, { max_members: 10, max_spaces: 'unlimited' });
  assert.equal(buildLimitsOverride({}).value, null);
  assert.match(buildLimitsOverride({ max_members: 'abc' }).error, /inteiro/);
  assert.match(buildLimitsOverride({ max_members: '-1' }).error, /inteiro/);
});
test('estender, aviso e assentos', () => {
  assert.equal(expiryToIso('x'), null);
  assert.ok(extendBody('2026-12-31', now).body.expires_at);
  assert.match(compWarningMessage('active_subscription'), /assinatura ativa/);
  assert.equal(compWarningMessage(null), null);
  assert.equal(seatsLabel({ effective: { max_members: null } }), 'ilimitados');
  assert.equal(seatsLabel({ effective: { max_members: 5 } }), '5');
});
test('a tela chama as rotas do contrato e trata 403 do support', () => {
  const src = read('product/staff-plan.tsx');
  for (const route of ['/entitlement`', '/comps`', '/comps/${comp.id}`', '/platform/comps?expiring_within=30']) assert.ok(src.includes(route), route);
  assert.match(src, /method: "PATCH"/); assert.match(src, /method: "DELETE"/); assert.match(src, /window\.confirm/);
  assert.match(src, /isSupportDenied/); assert.match(src, /ReadOnlyNotice/);
  const staff = read('product/team-staff.tsx');
  assert.match(staff, /<StaffPlanPanel/); assert.match(staff, /<StaffExpiringComps/); assert.match(staff, /<StaffOrgPlans/);
});

test('nomes amigáveis: estados internos + catálogo, nunca a plan_key crua', () => {
  const catalog = [{ plan_key: 'personal_basic', title: 'Pessoal Básico' }, { plan_key: 'personal_pro', title: 'Pessoal Pro' }, { plan_key: 'business_team', title: 'Empresa Team' }, { plan_key: 'business_scale', title: 'Empresa Scale' }];
  const titles = Object.fromEntries(['personal_basic', 'personal_pro', 'business_team', 'business_scale', 'personal_trial', 'business_trial', 'legacy', 'expired'].map((key) => [key, staffPlanTitle(key, catalog)]));
  assert.deepEqual(titles, { personal_basic: 'Pessoal Básico', personal_pro: 'Pessoal Pro', business_team: 'Empresa Team', business_scale: 'Empresa Scale', personal_trial: 'Teste Pessoal', business_trial: 'Teste Empresa', legacy: 'Legado', expired: 'Expirado' });
  assert.equal(staffPlanTitle('business_team', []), 'business_team', 'sem catálogo cai para a chave');
  assert.equal(staffPlanTitle(null, catalog), '—');
});
test('support lê mas não gerencia cortesias; a tela usa os nomes e esconde as ações', () => {
  assert.equal(canManageComps('admin'), true); assert.equal(canManageComps('support'), false); assert.equal(canManageComps(undefined), false);
  const src = read('product/staff-plan.tsx');
  assert.match(src, /canManageComps\(state\.staff_role\)/); assert.match(src, /\{manage && <GrantForm/); assert.match(src, /readOnly=\{!manage\}/);
  assert.match(src, /staffPlanTitle\(ent\.plan_key, plans\)/); assert.doesNotMatch(src, /\{state\.plan_key\}|\{ent\.plan_key\}|\{item\.plan_key\}|\{comp\.plan_key\}/);
  assert.doesNotMatch(src, /SupportNotice/, 'o 403 do support não existe mais');
});
