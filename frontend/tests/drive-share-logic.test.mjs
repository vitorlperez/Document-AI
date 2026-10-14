import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  driveShareEnabled, parseDriveFolderLink, verifyErrorMessage, verifyChecklist, checklistReach, firstSyncEstimate, itRequestText, ROLE_HINT,
  initialPollState, pollTick, resumePoll, POLL_MAX_MS, WORKSPACE_HINT_AFTER_MS, driveShareStatus, libraryAccessBadge, relativeSync, daysUntil,
} from "../app/product/drive-share-logic.ts";
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const ID = "1AbCdEfGhIjKlMnOpQrStUvWxYz";

test("flag: desligada por padrão, aceita 1/true/on/sim", () => {
  for (const off of [undefined, null, "", "0", "false", "no"]) assert.equal(driveShareEnabled(off), false);
  for (const on of ["1", "true", "TRUE", "on", "sim", true]) assert.equal(driveShareEnabled(on), true);
});

test("flag desligada = integrations-screen só muda por trás de DRIVE_SHARE_ENABLED", () => {
  const screen = read("../app/product/integrations-screen.tsx");
  assert.match(screen, /DRIVE_SHARE_ENABLED && !sourceId\) setDriveMethodOpen\(true\); else connect\(sourceId\)/);
  assert.match(screen, /DRIVE_SHARE_ENABLED && driveMethodOpen/);
  assert.match(screen, /DRIVE_SHARE_ENABLED && driveFlow/);
  assert.match(screen, /driveShare=\{DRIVE_SHARE_ENABLED\}/);
  assert.match(read("../app/product/integrations-screen.tsx"), /props\.driveShare \? props\.sources\.find/);
});

test("parser de links: variantes de pasta, arquivo, inválidos e injeção", () => {
  const folder = (u) => assert.deepEqual(parseDriveFolderLink(u), { kind: "folder", id: ID }, u);
  folder(`https://drive.google.com/drive/folders/${ID}`);
  folder(`https://drive.google.com/drive/folders/${ID}?usp=sharing`);
  folder(`https://drive.google.com/drive/u/0/folders/${ID}`);
  folder(`https://drive.google.com/drive/u/2/folders/${ID}?resourcekey=0-abc`);
  folder(`https://drive.google.com/drive/a/acme.com/folders/${ID}`);
  folder(`https://drive.google.com/drive/mobile/folders/${ID}`);
  folder(`drive.google.com/drive/folders/${ID}`);
  assert.deepEqual(parseDriveFolderLink(`https://drive.google.com/open?id=${ID}`), { kind: "ambiguous", id: ID });
  assert.deepEqual(parseDriveFolderLink(`https://drive.google.com/drive/folderview?id=${ID}`), { kind: "ambiguous", id: ID });
  assert.deepEqual(parseDriveFolderLink(ID), { kind: "ambiguous", id: ID });
  assert.deepEqual(parseDriveFolderLink(`https://drive.google.com/file/d/${ID}/view`), { kind: "invalid", code: "not_a_folder" });
  assert.deepEqual(parseDriveFolderLink(`https://docs.google.com/document/d/${ID}/edit`), { kind: "invalid", code: "not_a_folder" });
  for (const bad of ["", "   ", "javascript:alert(1)", "https://evil.example/drive/folders/" + ID, "https://drive.google.com/drive/my-drive", "https://drive.google.com/drive/folders/abc", `https://drive.google.com/drive/folders/${ID}'%20or%20'1'='1`, "x".repeat(300), "curto"]) {
    assert.equal(parseDriveFolderLink(bad).kind, "invalid", bad);
  }
});

test("mensagens de erro usam o texto do design §1.3", () => {
  assert.equal(verifyErrorMessage("invalid_link", null).title, "Esse link não parece ser de uma pasta do Google Drive.");
  assert.equal(verifyErrorMessage("not_a_folder", null).title, "Esse link não parece ser de uma pasta do Google Drive.");
  const shared = verifyErrorMessage("not_shared", "arq-k7m2x9qa@x.iam.gserviceaccount.com");
  assert.equal(shared.title, "Ainda não conseguimos abrir essa pasta. Ela precisa estar compartilhada com arq-k7m2x9qa@x.iam.gserviceaccount.com como Leitor.");
  assert.equal(shared.share, true);
  assert.match(verifyErrorMessage("download_blocked_partial", "r@x", 37).title, /^Encontramos 37 arquivos com download bloqueado pelo proprietário\./);
  assert.match(verifyErrorMessage("download_blocked_partial", "r@x", 37).hint, /por arquivo/);
  assert.equal(verifyErrorMessage("provider_error", "r@x").title, "Estamos com um problema técnico para acessar o Google Drive. Já fomos avisados.");
  assert.equal(verifyErrorMessage("provider_error", "r@x").share, false, "problema nosso: nunca pede ao cliente para reconectar");
  assert.equal(verifyErrorMessage("rate_limited", null).title, "O Google pediu para aguardarmos. Vamos tentar de novo automaticamente.");
  assert.match(verifyErrorMessage("public_link_blocked", "r@x").title, /qualquer pessoa com o link/);
  // não vaza se a pasta existe: not_shared não menciona "não existe"/"inexistente"
  assert.doesNotMatch(verifyErrorMessage("not_shared", "r@x").title + verifyErrorMessage("not_shared", "r@x").hint, /existe|inexistente/i);
});

test("papel: Leitor em destaque, mas Editor é aceito com dica", () => {
  assert.match(ROLE_HINT, /Leitor/);
  assert.match(ROLE_HINT, /Editor/);
  assert.match(ROLE_HINT, /tudo bem/);
  const flow = read("../app/product/drive-share-flow.tsx");
  assert.match(flow, /className="drive-role">Leitor/);
  assert.match(flow, /desmarque “Notificar pessoas”/);
});

test("checklist da verificação e quanto dele é alcançado por código", () => {
  const items = verifyChecklist({ code: "ok", folder_name: "Contratos 2026", file_count: 128, folder_count: 9 });
  assert.equal(items.length, 5);
  assert.match(items[1].label, /“Contratos 2026”/);
  assert.equal(items[4].label, "Contagem: 128 arquivos · 9 subpastas");
  assert.match(verifyChecklist({ code: "download_blocked_partial", blocked_download_count: 1, file_count: 1, folder_count: 1 })[3].label, /1 arquivo bloqueado/);
  assert.equal(checklistReach("ok"), 5);
  assert.equal(checklistReach("download_blocked_partial"), 5);
  assert.equal(checklistReach("invalid_link"), 0);
  assert.equal(checklistReach("not_shared"), 1);
});

test("tempo estimado da primeira sync: ~6 min por 1.000 arquivos", () => {
  assert.match(firstSyncEstimate(1000), /cerca de 6 minutos/);
  assert.match(firstSyncEstimate(128), /cerca de 1 minuto|cerca de 1 min/);
  assert.match(firstSyncEstimate(3000), /cerca de 18 minutos/);
  assert.match(firstSyncEstimate(0), /começa assim que/);
});

test("texto para o TI contém o e-mail, somente leitura e remoção", () => {
  const text = itRequestText("arq-1@p.iam.gserviceaccount.com", "Acme");
  assert.match(text, /arq-1@p\.iam\.gserviceaccount\.com/);
  assert.match(text, /somente permissão de leitura/);
  assert.match(text, /Acme/);
});

test("polling: 5 s, dica de Workspace aos 90 s, pausa aos 5 min, retomar", () => {
  let s = initialPollState();
  const ticks = [];
  while (s.phase === "polling") { s = pollTick(s, false); ticks.push(s); if (ticks.length > 100) break; }
  assert.equal(s.phase, "paused");
  assert.equal(s.elapsedMs, POLL_MAX_MS);
  assert.equal(ticks.length, 60);
  assert.equal(ticks.find((t) => t.emptyHint).elapsedMs, WORKSPACE_HINT_AFTER_MS + 5000 - (WORKSPACE_HINT_AFTER_MS % 5000 === 0 ? 5000 : 0));
  assert.equal(pollTick(s, false), s, "pausado não avança");
  const resumed = resumePoll(s);
  assert.equal(resumed.phase, "polling"); assert.equal(resumed.elapsedMs, 0); assert.equal(resumed.emptyHint, true);
  assert.equal(pollTick(initialPollState(), true).emptyHint, false, "achou pasta → sem aviso");
});

test("status do card: awaiting_share, access_lost, provider_error", () => {
  assert.equal(driveShareStatus("connected").label, "Conectado");
  assert.equal(driveShareStatus("awaiting_share").label, "Aguardando compartilhamento");
  assert.equal(driveShareStatus("access_lost").label, "Acesso removido");
  assert.equal(driveShareStatus("provider_error").tone, "error");
  assert.match(driveShareStatus("provider_error").description, /não precisa reconectar/);
});

test("badge da Biblioteca: acesso removido / apagando em N dias", () => {
  const now = Date.parse("2026-10-14T12:00:00Z");
  assert.equal(libraryAccessBadge({}, now), null);
  assert.equal(libraryAccessBadge({ access_state: "connected" }, now), null);
  assert.equal(libraryAccessBadge({ access_state: "access_lost" }, now).label, "Acesso removido");
  const in9 = libraryAccessBadge({ access_state: "purge_scheduled", purge_after: "2026-10-23T12:00:00Z" }, now);
  assert.equal(in9.label, "Acesso removido · apagando em 9 dias"); assert.equal(in9.tone, "warning");
  assert.equal(libraryAccessBadge({ access_state: "purge_scheduled", purge_after: "2026-10-15T12:00:00Z" }, now).label, "Acesso removido · apagando em 1 dia");
  const soon = libraryAccessBadge({ access_state: "access_lost", purge_after: "2026-10-14T13:00:00Z" }, now);
  assert.equal(soon.label, "Acesso removido · apagando em 1 dia");
  assert.equal(libraryAccessBadge({ access_state: "access_lost", purge_after: "2026-10-10T00:00:00Z" }, now).label, "Acesso removido · apagando hoje");
  assert.equal(daysUntil("lixo", now), null);
});

test("relativeSync", () => {
  const now = Date.parse("2026-10-14T12:00:00Z");
  assert.equal(relativeSync("2026-10-14T11:56:00Z", now), "sync há 4 min");
  assert.equal(relativeSync(null, now), "ainda não sincronizada");
});

test("Tela 0: modal de método com recomendado pré-selecionado e OAuth como 2ª opção", () => {
  const flow = read("../app/product/drive-share-flow.tsx");
  const modal = flow.slice(flow.indexOf("export function DriveMethodModal"), flow.indexOf("// ---- fluxo em 3 passos"));
  assert.match(modal, /useState<DriveMethod>\("share"\)/);
  assert.match(modal, /Conectar Google Drive/);
  assert.match(modal, /Compartilhar pastas com o ArquivIO/);
  assert.match(modal, /Recomendado/);
  assert.match(modal, /Entrar com a conta Google/);
  assert.match(modal, /role="radiogroup"/);
  assert.match(modal, />Cancelar</); assert.match(modal, />Continuar</);
  assert.ok(modal.indexOf("Recomendado") < modal.indexOf("Entrar com a conta Google"), "OAuth fica como segunda opção");
});

test("copiar tem fallback e anuncia por aria-live; polling isolado do módulo de API", () => {
  const flow = read("../app/product/drive-share-flow.tsx");
  assert.match(flow, /navigator\.clipboard\.writeText/);
  assert.match(flow, /execCommand\("copy"\)/);
  assert.match(flow, /role="status" aria-live="polite"/);
  assert.match(flow, /Copiar texto para o TI/);
  assert.match(flow, /Retomar/);
  const api = read("../app/product/drive-share-api.ts");
  assert.match(api, /\/data-sources\/google-sa\//);
  assert.doesNotMatch(flow, /\/data-sources\/google-sa/, "endpoints só no módulo de API");
});
