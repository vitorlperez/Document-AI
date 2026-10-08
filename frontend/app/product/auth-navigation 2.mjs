/** The same narrow invitation-only return policy enforced by the backend. */
export function safeInvitationReturnTo(value) {
  return typeof value === "string" && /^\/invitations\/[A-Za-z0-9_-]{20,128}(?![\s\S])/.test(value) ? value : undefined;
}

export function hostedLoginQuery(screenHint, returnTo) {
  const query = new URLSearchParams({ screen_hint: screenHint });
  const safe = safeInvitationReturnTo(returnTo);
  if (safe) query.set("return_to", safe);
  return query.toString();
}
