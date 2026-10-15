import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { toolGroup, mergeToolRoots, sameTool, providerKey, toolLabel } from "../app/tool-groups.ts";
import { providerLabel } from "../app/provider-labels.ts";
import { driveConnections, driveCardStatus, unifiedDriveFolders, driveCardActions } from "../app/product/drive-unified-logic.ts";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const NOW = Date.parse("2026-10-14T12:00:00Z");

test("google_drive e google_drive_sa são a mesma ferramenta", () => {
  for (const p of ["google", "google_drive", "google_drive_sa"]) assert.equal(toolGroup(p), "google_drive");
  assert.equal(toolGroup("onedrive"), "onedrive");
  assert.equal(sameTool("google_drive", "google_drive_sa"), true);
  assert.equal(sameTool("google_drive", "onedrive"), false);
});

test("chat: chave, rótulo e ícone únicos para as duas conexões", () => {
  assert.equal(providerKey("google_drive_sa"), providerKey("google_drive"));
  assert.equal(providerKey("google_drive_sa"), "google");
  for (const p of ["google", "google_drive", "google_drive_sa"]) { assert.equal(toolLabel(p), "Google Drive"); assert.equal(providerLabel(p), "Google Drive"); }
});

test("question-scope reexporta as funções únicas de tool-groups", () => {
  assert.match(read("../app/question-scope.tsx"), /from "\.\/tool-groups"/);
});

test("nenhum rótulo visível diz 'pasta compartilhada' como se fosse outra ferramenta", () => {
  assert.doesNotMatch(read("../app/question-scope.tsx"), /Google Drive \(pasta compartilhada\)/);
  assert.doesNotMatch(read("../app/product/integrations-screen.tsx"), /Pasta compartilhada/);
  assert.doesNotMatch(read("../app/product/drive-share-flow.tsx"), /Google Drive · Pasta compartilhada/);
});

const root = (id, source_id, provider, name = "Google Drive") => ({ id, kind: "source", name, source_id, source_provider: provider });

test("Biblioteca: raízes das duas conexões viram uma só fonte 'Google Drive'", () => {
  const roots = [root("r1", "s1", "google_drive"), root("r2", "s2", "google_drive_sa", "Google Drive (pasta compartilhada)"), root("r3", "s3", "notion", "Notion")];
  const merged = mergeToolRoots(roots);
  assert.equal(merged.length, 2);
  const drive = merged.find((r) => r.source_provider === "google_drive");
  assert.equal(drive.name, "Google Drive");
  assert.deepEqual(drive.merged_source_ids.sort(), ["s1", "s2"]);
  assert.deepEqual(drive.merged_root_ids.sort(), ["r1", "r2"]);
  assert.equal(merged.find((r) => r.id === "r3").merged_source_ids, undefined);
});

test("mergeToolRoots mantém uma raiz única intacta e não mistura raízes sem provider", () => {
  const one = [root("r1", "s1", "google_drive_sa")];
  assert.equal(mergeToolRoots(one)[0].name, "Google Drive");
  const unknown = [{ id: "a", kind: "source", name: "X", source_id: "1" }, { id: "b", kind: "source", name: "Y", source_id: "2" }];
  assert.equal(mergeToolRoots(unknown).length, 2);
});

const src = (id, provider, status = "connected", extra = {}) => ({ id, provider, status, account_email: null, ...extra });

test("driveConnections separa as conexões por método e ignora desconectadas antigas", () => {
  const { oauth, share } = driveConnections([src("1", "google_drive", "disconnected"), src("2", "google_drive_sa"), src("3", "notion")]);
  assert.equal(oauth, null); assert.equal(share.id, "2");
  assert.equal(driveConnections([]).share, null);
});

test("status do card: conectado se qualquer método conectado; reauth só quando nada conectado", () => {
  assert.equal(driveCardStatus({ oauth: src("1", "google_drive", "reauth_required"), share: src("2", "google_drive_sa") }).tone, "ok");
  assert.equal(driveCardStatus({ oauth: src("1", "google_drive", "reauth_required"), share: null }).label, "Reconexão necessária");
  assert.equal(driveCardStatus({ oauth: null, share: src("2", "google_drive_sa", "awaiting_share") }).tone, "pending");
  assert.equal(driveCardStatus({ oauth: null, share: null }).label, "Disponível");
  assert.equal(driveCardStatus({ oauth: null, share: src("2", "google_drive_sa", "access_lost") }).tone, "warning");
});

test("lista única de pastas: junta as duas conexões, preserva acesso removido e método", () => {
  const rows = unifiedDriveFolders({
    shareFolders: [{ id: "l1", link_id: "l1", folder_id: "d1", name: "Contratos", status: "verified", file_count: 12, last_synced_at: "2026-10-14T11:00:00Z" }, { id: "l2", link_id: "l2", folder_id: "d2", name: "Antiga", status: "purge_scheduled", purge_after: "2026-10-17T12:00:00Z" }],
    oauthFolders: [{ id: "w1", name: "Financeiro", status: "ready", last_synced_at: null, source_id: "1" }, { id: "w9", name: "Outra fonte", status: "ready", last_synced_at: null, source_id: "zzz" }],
    oauthSourceId: "1", now: NOW,
  });
  assert.deepEqual(rows.map((r) => r.name), ["Contratos", "Antiga", "Financeiro"]);
  assert.equal(rows[0].method, "share"); assert.equal(rows[0].canUnlink, true); assert.equal(rows[0].lost, false);
  assert.equal(rows[1].lost, true); assert.match(rows[1].meta, /apagando em 3 dias/);
  assert.equal(rows[2].method, "oauth"); assert.equal(rows[2].canUnlink, false);
});

test("ações coerentes: Conectar abre direto o compartilhamento; Adicionar pastas; desconectar por método", () => {
  assert.deepEqual(driveCardActions({ oauth: null, share: null }).primary, { kind: "start-share", label: "Conectar" });
  assert.equal(driveCardActions({ oauth: null, share: src("2", "google_drive_sa") }).primary.label, "Adicionar pastas");
  assert.equal(driveCardActions({ oauth: src("1", "google_drive"), share: null }).primary.label, "Adicionar pastas");
  const both = driveCardActions({ oauth: src("1", "google_drive"), share: src("2", "google_drive_sa") });
  assert.deepEqual(both.disconnect.map((d) => d.method), ["share", "oauth"]);
  assert.equal(driveCardActions({ oauth: src("1", "google_drive", "reauth_required"), share: null }).reconnectOauth, true);
});

test("fluxo: link discreto de OAuth e Conectar sem modal de método", () => {
  const flow = read("../app/product/drive-share-flow.tsx");
  assert.match(flow, /Prefere entrar com a conta Google\?/);
  const screen = read("../app/product/integrations-screen.tsx");
  assert.doesNotMatch(screen, /<DriveMethodModal/);
});
