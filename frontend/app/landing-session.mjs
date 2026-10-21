/** Which CTA set the landing shows: neutral placeholder while the session loads, app shortcut when signed in. */
export function landingCtaMode(session) {
  if (session?.status === "authenticated") return "app";
  if (session?.status === "loading") return "loading";
  return "anonymous";
}

/**
 * The landing lives at "/" and is visible to everyone. Only the app entry routes
 * (/login, also the post-login destination) auto-enter the single organization.
 */
export function shouldAutoEnterOrganization({ screen, pathname, membershipCount, hasResetToken }) {
  return screen === "home" && pathname !== "/" && membershipCount === 1 && !hasResetToken;
}

/** Name of the organization to show next to the account: the last one entered, else the only one. */
export function landingOrganizationName(companies, activeId) {
  if (!companies.length) return null;
  return (companies.find((item) => item.id === activeId) ?? (companies.length === 1 ? companies[0] : null))?.name ?? null;
}
