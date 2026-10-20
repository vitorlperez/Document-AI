import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { accountMenuItems, activePrimaryTab, avatarInitial, displayNameFromEmail, filterDestinations, orgMenuItems, orgMenuSections, paletteDestinations } from "../app/product/account-helpers.ts";

const read = (path) => readFileSync(new URL(`../app/${path}`, import.meta.url), "utf8");

test("avatarInitial prefers the name, falls back to the e-mail, then to ?", () => {
  assert.equal(avatarInitial("ana souza", "x@y.z"), "A");
  assert.equal(avatarInitial("", "vitor@x.com"), "V");
  assert.equal(avatarInitial(null, "  émerson@x.com"), "É");
  assert.equal(avatarInitial("", ""), "?");
  assert.equal(avatarInitial(undefined, undefined), "?");
});

test("displayNameFromEmail humanises the local part", () => {
  assert.equal(displayNameFromEmail("maria.silva@x.com"), "Maria Silva");
  assert.equal(displayNameFromEmail(""), "");
});

test("avatar menu only carries personal items (Perfil)", () => {
  for (const role of ["member", "admin", "owner"]) assert.deepEqual(accountMenuItems(role).map((item) => item.key), ["profile"]);
});

test("org menu: member sees Trabalho only, never Gerenciar", () => {
  assert.deepEqual(orgMenuSections("member").map((section) => section.key), ["work"]);
  assert.deepEqual(orgMenuItems("member").map((item) => item.key), ["spaces", "automations"]);
});

test("org menu: Integrações, Uso e limites and API e MCP are owner/admin; Equipe is owner only", () => {
  assert.deepEqual(orgMenuItems("owner").map((item) => item.key), ["spaces", "automations", "integrations", "team", "admin", "developer"]);
  assert.deepEqual(orgMenuItems("admin").map((item) => item.key), ["spaces", "automations", "integrations", "admin", "developer"]);
  assert.deepEqual(orgMenuSections("admin").map((section) => section.label), ["Trabalho", "Gerenciar"]);
});

test("org menu keeps the existing routes", () => {
  const suffixes = Object.fromEntries(orgMenuItems("owner").map((item) => [item.key, item.suffix]));
  assert.deepEqual(suffixes, { spaces: "/spaces", automations: "/automations", integrations: "/integrations", team: "/team", admin: "/admin", developer: "/developer" });
});

test("command palette destinations follow the role and filter without accents/case", () => {
  assert.deepEqual(paletteDestinations("member").map((item) => item.key), ["chat", "library", "spaces", "automations", "profile"]);
  assert.ok(paletteDestinations("owner").some((item) => item.key === "team"));
  assert.ok(!paletteDestinations("admin").some((item) => item.key === "team"));
  assert.deepEqual(filterDestinations(paletteDestinations("owner"), "AUTOMACOES").map((item) => item.key), ["automations"]);
  assert.deepEqual(filterDestinations(paletteDestinations("member"), "integ"), []);
  assert.equal(filterDestinations(paletteDestinations("member"), "  ").length, 5);
});

test("only Conversa and Biblioteca are primary tabs; demoted routes activate none", () => {
  assert.equal(activePrimaryTab("/companies/x"), "chat");
  assert.equal(activePrimaryTab("/companies/x/library/"), "library");
  for (const suffix of ["spaces", "automations", "integrations", "team", "admin", "developer", "profile"]) assert.equal(activePrimaryTab(`/companies/x/${suffix}`), null);
});

test("desktop header: org chip, two tabs, ⌘K, no role badge / theme buttons / admin tabs; avatar owns theme, tour, shortcuts, staff", () => {
  const shell = read("product/shell.tsx");
  assert.match(shell, /<OrgMenu /);
  assert.doesNotMatch(shell, /roleLabel|ThemeToggle|label: "Automações"|label: "Espaços"|label: "Integrações"|Suporte/);
  const menu = read("product/account-menu.tsx");
  assert.match(menu, /<ThemeToggle /);
  for (const label of ["Conhecer o app", "Atalhos", "Suporte", "Sair"]) assert.match(menu, new RegExp(label));
});

test("org menu is an accessible menu with org switching on desktop", () => {
  const menu = read("product/org-menu.tsx");
  assert.match(menu, /role="menu"/);
  assert.match(menu, /role="menuitemradio"/);
  assert.match(menu, /event\.key === "Escape"/);
  assert.match(menu, /onCompanyChange/);
  assert.match(menu, /orgMenuSections\(company\.role\)/);
});

test("mobile: bottom tab bar + Mais sheet, no hamburger/drawer", () => {
  const nav = read("mobile-nav.tsx");
  assert.doesNotMatch(nav, /Menu,|mobile-drawer"|ToolsSidebar|<select/);
  assert.match(nav, /export function MobileTabBar/);
  for (const label of ["Conversa", "Biblioteca", "Nova", "Mais"]) assert.match(nav, new RegExp(`<span>${label}</span>`));
  assert.match(nav, /orgMenuSections\(company\.role\)/);
  assert.match(read("mobile-chat.css"), /\.mobile-tab-bar \{[^}]*env\(safe-area-inset-bottom\)/);
});

test("chat has no Ferramentas column and no tour button in the topbar", () => {
  const chat = read("product/chat-workspace.tsx");
  assert.doesNotMatch(chat, /ToolsSidebar|Rever tour do app/);
  assert.match(chat, /<ConversationHistory docked /);
});
