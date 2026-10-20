import type { Role } from "./types-and-api";

/** Uppercase initial for the avatar: name first, then e-mail; "?" when neither has a letter or digit. */
export function avatarInitial(name: string | null | undefined, email: string | null | undefined): string {
  for (const source of [name, email]) {
    const match = source?.trim().match(/[\p{L}\p{N}]/u);
    if (match) return match[0].toLocaleUpperCase("pt-BR");
  }
  return "?";
}

/** The API exposes no display name yet: derive a readable one from the e-mail local part. */
export function displayNameFromEmail(email: string | null | undefined): string {
  const local = (email ?? "").split("@")[0]?.replace(/[._+-]+/g, " ").trim() ?? "";
  if (!local) return "";
  return local.split(/\s+/).map((word) => word.charAt(0).toLocaleUpperCase("pt-BR") + word.slice(1)).join(" ");
}

/** Same rule as the former Administração/Desenvolvedor tabs: only owners and admins. */
export const canManageOrganization = (role: Role) => role !== "member";

export type AccountMenuItem = { key: "profile"; label: string; suffix: string };

/** Personal items only ("eu"): everything that belongs to the organization lives in `orgMenuItems`. */
export function accountMenuItems(role: Role): AccountMenuItem[] {
  void role;
  return [{ key: "profile", label: "Perfil", suffix: "/profile" }];
}

export type OrgMenuItemKey = "spaces" | "automations" | "integrations" | "team" | "admin" | "developer";
export type OrgMenuItem = { key: OrgMenuItemKey; label: string; suffix: string };
export type OrgMenuSection = { key: "work" | "manage"; label: string; items: OrgMenuItem[] };

/**
 * Org menu sections by role. Same rules the former tabs/avatar items had: Espaços and Automações for everyone;
 * Integrações, Uso e limites and API e MCP for owners/admins; Equipe for owners only. A section with no items is dropped
 * (a member never sees "Gerenciar").
 */
export function orgMenuSections(role: Role): OrgMenuSection[] {
  const sections: OrgMenuSection[] = [
    { key: "work", label: "Trabalho", items: [
      { key: "spaces", label: "Espaços", suffix: "/spaces" },
      { key: "automations", label: "Automações", suffix: "/automations" },
    ] },
    { key: "manage", label: "Gerenciar", items: [
      ...(canManageOrganization(role) ? [{ key: "integrations" as const, label: "Integrações", suffix: "/integrations" }] : []),
      ...(role === "owner" ? [{ key: "team" as const, label: "Equipe", suffix: "/team" }] : []),
      ...(canManageOrganization(role) ? [
        { key: "admin" as const, label: "Uso e limites", suffix: "/admin" },
        { key: "developer" as const, label: "API e MCP", suffix: "/developer" },
      ] : []),
    ] },
  ];
  return sections.filter((section) => section.items.length > 0);
}

export const orgMenuItems = (role: Role): OrgMenuItem[] => orgMenuSections(role).flatMap((section) => section.items);

export type PaletteDestination = { key: string; label: string; suffix: string; hint?: string };

/** Everything ⌘K can jump to for this role: the two main screens, the personal profile and the org menu items. */
export function paletteDestinations(role: Role): PaletteDestination[] {
  return [
    { key: "chat", label: "Conversa", suffix: "" },
    { key: "library", label: "Biblioteca", suffix: "/library" },
    ...orgMenuItems(role),
    { key: "profile", label: "Perfil", suffix: "/profile" },
  ];
}

/** Case/accent-insensitive filter for the palette destinations. */
export function filterDestinations(destinations: PaletteDestination[], query: string): PaletteDestination[] {
  const fold = (text: string) => text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLocaleLowerCase("pt-BR");
  const needle = fold(query.trim());
  return needle ? destinations.filter((item) => fold(item.label).includes(needle)) : destinations;
}

/** Route suffixes that are not the chat: the shell treats them as "outside the two primary tabs". */
export const SECONDARY_SUFFIXES = ["/team", "/integrations", "/automations", "/developer", "/admin", "/profile", "/spaces"] as const;

/** Which primary tab is active: chat, library or none (secondary pages). */
export function activePrimaryTab(pathname: string): "chat" | "library" | null {
  const clean = pathname.replace(/\/$/, "");
  if (clean.endsWith("/library")) return "library";
  if (SECONDARY_SUFFIXES.some((suffix) => clean.endsWith(suffix))) return null;
  return "chat";
}

export const TOUR_REPLAY_KEY = "arquivio:replay-tour";
