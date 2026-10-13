/** Variantes de botão [M56]. Tokens: --btn-* (globals.css), estilos: app/buttons.css, contrato: specs/design/surfaces-elevation.md §8. */
export type ButtonVariant = "primary" | "secondary" | "ghost" | "destructive" | "danger-soft" | "danger-ghost" | "success" | "info";
export type ButtonSize = "md" | "sm" | "icon";
/** `btn("primary")` → "btn btn-primary". Uma ação primária por contexto; carregando = aria-busy="true" + disabled. */
export function btn(variant: ButtonVariant, size: ButtonSize = "md", extra?: string): string {
  return ["btn", `btn-${variant}`, size === "sm" ? "btn-sm" : size === "icon" ? "btn-icon" : "", extra].filter(Boolean).join(" ");
}
