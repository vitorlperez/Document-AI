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

export type AccountMenuItem = { key: "profile" | "admin" | "developer"; label: string; suffix: string };

export function accountMenuItems(role: Role): AccountMenuItem[] {
  return [
    { key: "profile", label: "Perfil", suffix: "/profile" },
    ...(canManageOrganization(role) ? [
      { key: "admin" as const, label: "Administração", suffix: "/admin" },
      { key: "developer" as const, label: "Desenvolvedor", suffix: "/developer" },
    ] : []),
  ];
}
