import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import {
  driveShareEnabled, parseDriveFolderLink, verifyErrorMessage, verifyChecklist, checklistReach, firstSyncEstimate, itRequestText, ROLE_HINT, verifyCodeFor,
  foundFoldersLabel, unlinkedFolders, knownAncestors, isSelected, nestedWarning, nestedWarningText, selectedIds, toggleAll, connectLabel, batchRowView, batchSummary, syncTargets, retryableIds, unlinkConfirmCopy,
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
  assert.match(screen, /onConnect=\{connect\} driveShare=\{DRIVE_SHARE_ENABLED\}/);
  assert.match(screen, /DRIVE_SHARE_ENABLED && driveFlow/);
  assert.match(screen, /if \(driveShare\) return <GoogleDriveCard/);
  assert.doesNotMatch(screen, /DriveMethodModal|driveMethodOpen/);
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
  assert.equal(verifyChecklist({ code: "not_shared" })[4].label, "Contagem de arquivos e subpastas", "sem números inventados quando a verificação falha");
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

test("Tela 0 removida: Conectar abre direto o compartilhamento; OAuth é link secundário no fluxo", () => {
  const flow = read("../app/product/drive-share-flow.tsx");
  assert.doesNotMatch(flow, /DriveMethodModal/);
  assert.match(flow, /Prefere entrar com a conta Google\?/);
  assert.ok(flow.indexOf("Prefere entrar com a conta Google?") > flow.indexOf("Já compartilhei todas as pastas"), "OAuth fica depois da ação principal");
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

test("contrato da API: códigos de erro do backend viram códigos de verificação da UI", () => {
  assert.equal(verifyCodeFor("not_shared", 404), "not_shared");
  assert.equal(verifyCodeFor("invalid_folder_link", 422), "invalid_link");
  assert.equal(verifyCodeFor("not_a_folder", 422), "not_a_folder");
  assert.equal(verifyCodeFor("rate_limited", 429), "rate_limited");
  for (const code of ["robot_unavailable", "provider_unavailable", "pool_empty", "robot_retired"]) assert.equal(verifyCodeFor(code, 503), "provider_error");
  assert.equal(verifyCodeFor(null, 404), "not_shared");
  assert.equal(verifyCodeFor("desconhecido", 500), "provider_error");
});

test("verificação sem folder_count (contrato) mostra só arquivos; rotas levam organization_id", () => {
  assert.equal(verifyChecklist({ code: "ok", name: "X", file_count: 12 })[4].label, "Contagem: 12 arquivos");
  assert.equal(verifyChecklist({ code: "ok", file_count: 1 })[4].label, "Contagem: 1 arquivo");
  const api = read("../app/product/drive-share-api.ts");
  assert.match(api, /organization_id=\$\{encodeURIComponent\(org\)\}/);
  assert.match(api, /\.folders/);
  assert.match(api, /url_or_id/);
});

test("e2e local: contrato final (GET folders com link_id, sync inicial, método sempre oferecido, URL sem validação nativa)", () => {
  const api = read("../app/product/drive-share-api.ts"), flow = read("../app/product/drive-share-flow.tsx"), screen = read("../app/product/integrations-screen.tsx");
  assert.match(api, /\$\{base\(sourceId\)\}\/folders`\);/);
  assert.match(api, /id: f\.link_id/);
  assert.doesNotMatch(api, /inbox\.filter\(\(f\) => f\.linked\)/);
  assert.match(api, /\/library\/workspaces\/\$\{encodeURIComponent\(workspaceFolderId\)\}\/reprocess/);
  assert.match(flow, /client\.startSync\(next\)/);
  assert.match(flow, /<form className="drive-paste" noValidate/);
  assert.match(screen, /onDriveShareStart=\{\(\) => setDriveFlow\(\{ source: null \}\)\}/);
});

test("robô sob demanda: enable é chamado uma vez, com polling de status e sem enable no state()", () => {
  const flow = read("../app/product/drive-share-flow.tsx");
  const api = read("../app/product/drive-share-api.ts");
  assert.match(flow, /enabledOnce\.current\) return; enabledOnce\.current = true; enable\(\)/);
  assert.match(flow, /client\.provisioning\(pendingSource\)/);
  assert.match(flow, /Preparando o e-mail exclusivo da sua empresa…/);
  assert.match(api, /`\$\{base\(sourceId\)\}\/status`/);
  assert.doesNotMatch(api.slice(api.indexOf("state: async")), /google-sa\/enable/);
  assert.equal(driveShareStatus("provisioning").tone, "pending");
});


// ---- multi-pasta ----
const F = (id, name, extra = {}) => ({ id, name, ...extra });
const tree = [F("root", "Contratos"), F("child", "2026", { parent_ids: ["root"] }), F("grand", "Q1", { parent_ids: ["child"] }), F("solo", "RH", { parent_ids: ["desconhecido"] }), F("old", "Antiga", { linked: true })];

test("contador do passo 1: singular, plural e vazio", () => {
  assert.equal(foundFoldersLabel(0), "Nenhuma pasta encontrada ainda");
  assert.equal(foundFoldersLabel(1), "1 pasta encontrada");
  assert.equal(foundFoldersLabel(3), "3 pastas encontradas");
  assert.deepEqual(unlinkedFolders(tree).map((f) => f.id), ["root", "child", "grand", "solo"]);
});

test("ancestrais: segue parent_ids pela lista, ignora pai desconhecido, usa nested_in do servidor", () => {
  assert.deepEqual(knownAncestors(tree[2], tree).map((a) => a.id), ["child", "root"]);
  assert.deepEqual(knownAncestors(tree[3], tree), [], "pai fora da lista não é ancestral conhecido");
  const server = F("x", "X", { nested_in: { id: "p", name: "P", linked: true } });
  assert.deepEqual(knownAncestors(server, [server]), [{ id: "p", name: "P", linked: true }]);
  const cycle = [F("a", "A", { parent_ids: ["b"] }), F("b", "B", { parent_ids: ["a"] })];
  assert.ok(knownAncestors(cycle[0], cycle).length <= 2, "ciclo não trava");
});

test("seleção padrão: tudo marcado, menos pasta dentro de outra detectada; escolha explícita vence", () => {
  const folders = unlinkedFolders(tree);
  assert.deepEqual(selectedIds(folders, {}), ["root", "solo"]);
  assert.equal(isSelected(folders[1], folders, { child: true }), true);
  assert.deepEqual(selectedIds(folders, { root: false }), ["solo"]);
});

test("aviso de pasta aninhada: dentro de vinculada ou de outra marcada; some se o pai é desmarcado", () => {
  const folders = [...unlinkedFolders(tree), F("inlinked", "Sub", { parent_ids: ["old"] })].map((f) => f);
  const all = [...folders, tree[4]];
  assert.equal(nestedWarning(all[1], all, {}), null, "desmarcada por padrão = sem aviso ativo");
  assert.deepEqual(nestedWarning(all[1], all, { child: true }), { id: "root", name: "Contratos" });
  assert.equal(nestedWarning(all[1], all, { child: true, root: false }), null, "pai desmarcado: a filha é a pasta raiz do vínculo");
  assert.deepEqual(nestedWarning(all[4], all, { inlinked: true }), { id: "old", name: "Antiga" }, "dentro de uma já vinculada");
  assert.equal(nestedWarningText("Contratos"), "Esta pasta está dentro de “Contratos” — os arquivos já serão incluídos.");
});

test("selecionar todas alterna entre tudo e nada; rótulo do botão concorda em número", () => {
  const folders = unlinkedFolders(tree);
  const all = toggleAll(folders, {});
  assert.deepEqual(selectedIds(folders, all), ["root", "child", "grand", "solo"], "desmarcadas por padrão também entram");
  assert.deepEqual(selectedIds(folders, toggleAll(folders, all)), []);
  assert.equal(connectLabel(0), "Conectar pastas"); assert.equal(connectLabel(1), "Conectar 1 pasta"); assert.equal(connectLabel(4), "Conectar 4 pastas");
});

test("resultado em lote: linha por pasta (ok / bloqueio parcial / aninhada / erro §1.3) e resumo", () => {
  const rows = [
    { folder_id: "a", name: "A", status: "ok", code: "ok", file_count: 12, workspace_folder_id: "w1" },
    { folder_id: "b", name: "B", status: "ok", code: "download_blocked_partial", blocked_download_count: 2, workspace_folder_id: "w2" },
    { folder_id: "c", name: "C", status: "nested", code: "nested_in_linked", parent_name: "A" },
    { folder_id: "d", status: "error", code: "not_shared" },
    { folder_id: "e", status: "error", code: "invalid_folder_link" },
    { folder_id: "f", status: "error", code: "provider_unavailable" },
  ];
  assert.deepEqual(batchRowView(rows[0]), { tone: "ok", label: "Conectada · 12 arquivos", retry: false });
  assert.equal(batchRowView(rows[1]).tone, "warn"); assert.match(batchRowView(rows[1]).label, /2 arquivos com download bloqueado/);
  assert.equal(batchRowView(rows[2]).tone, "info"); assert.match(batchRowView(rows[2]).label, /Já incluída em “A”/);
  assert.match(batchRowView(rows[3]).label, /precisa estar compartilhada/); assert.equal(batchRowView(rows[3]).retry, true);
  assert.equal(batchRowView(rows[4]).retry, false, "link inválido não adianta repetir");
  assert.equal(batchRowView(rows[5]).retry, true);
  assert.equal(batchSummary(rows).text, "2 pastas conectadas · sincronizando · 1 já incluída em outra · 3 com problema");
  assert.equal(batchSummary(rows.slice(0, 1)).text, "1 pasta conectada · sincronizando");
  assert.equal(batchSummary([rows[3]]).text, "Nenhuma pasta conectada · 1 com problema");
  assert.deepEqual(syncTargets([...rows, rows[0]]), ["w1", "w2"], "sync só das conectadas, sem repetir");
  assert.deepEqual(retryableIds(rows), ["d", "f"]);
});

test("desvincular: confirmação explica ocultar agora, apagar em 14 dias e oferece apagar agora", () => {
  const copy = unlinkConfirmCopy("Contratos");
  assert.match(copy.title, /“Contratos”/); assert.match(copy.body, /agora/); assert.match(copy.body, /14 dias/);
  assert.equal(copy.purge, "Apagar agora");
});

test("fluxo multi-pasta: passo 1 com contador ao vivo, botão principal e atalho; passo 2 com checkbox; passo 3 em lote; card com Desvincular", () => {
  const flow = read("../app/product/drive-share-flow.tsx"), api = read("../app/product/drive-share-api.ts"), css = read("../app/product/drive-share-flow.css");
  assert.match(flow, /Já compartilhei todas as pastas/);
  assert.match(flow, /Já compartilhei antes — escolher agora/);
  assert.match(flow, /QUANTAS|quantas pastas quiser/);
  assert.match(flow, /aria-live="polite"[^>]*>\{foundFoldersLabel/);
  assert.match(flow, /Selecionar todas/);
  assert.match(flow, /type="checkbox"/);
  assert.match(flow, /client\.linkBatch\(/);
  assert.doesNotMatch(flow, /client\.link\(/, "o fluxo usa o endpoint em lote");
  assert.match(flow, /Ver na Biblioteca/); assert.match(flow, />Concluir</);
  assert.match(flow, /Use o mesmo e-mail para todas as pastas/);
  assert.match(flow, /"Apagar agora" : "Desvincular"/);
  assert.match(api, /folders\/batch/); assert.match(api, /folder_ids/);
  assert.match(css, /\.drive-pick-list/); assert.match(css, /prefers-reduced-motion/);
});
