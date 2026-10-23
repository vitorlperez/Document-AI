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

/**
 * Specific, honest copy for the login/sign-up/verify/reset calls. Never "Você não tem permissão":
 * on these routes a 403 is a request the server could not validate (origin / proxy context), not
 * a lack of rights, and existing accounts are intentionally indistinguishable from new ones.
 */
export function authErrorMessage(error) {
  const status = typeof error?.status === "number" ? error.status : undefined;
  if (status === undefined) {
    return error instanceof TypeError
      ? "Não conseguimos nos conectar ao serviço. Confira sua conexão e tente novamente."
      : "Não foi possível concluir agora. Tente novamente.";
  }
  const detail = typeof error.message === "string" ? error.message.trim() : "";
  if (status === 400) return detail || "Confira os dados informados e tente novamente.";
  if (status === 401) return "Sua sessão de acesso expirou. Recarregue a página e tente novamente.";
  if (status === 403) return "Não conseguimos validar este acesso. Recarregue a página e tente novamente; se continuar, fale com o suporte.";
  if (status === 422) return "Confira os dados informados e tente novamente.";
  if (status === 429) return "Muitas tentativas. Aguarde um minuto e tente novamente.";
  if (status >= 500) return "O acesso está temporariamente indisponível. Tente novamente em instantes.";
  return "Não foi possível concluir agora. Tente novamente.";
}

const CALLBACK_MESSAGES = {
  state: "Sua tentativa de acesso expirou ou foi aberta em outro navegador. Entre novamente.",
  denied: "O acesso foi cancelado. Entre novamente quando quiser.",
  missing_code: "Não recebemos a confirmação do acesso. Entre novamente.",
  rejected: "Este link de acesso já foi usado ou expirou. Entre novamente com seu e-mail e senha.",
  unavailable: "O acesso está temporariamente indisponível. Tente novamente em instantes.",
  rate_limited: "Muitas tentativas. Aguarde um minuto e tente novamente.",
  verification_required: "Falta confirmar seu e-mail. Entre com e-mail e senha para receber o código de confirmação.",
  additional_step: "Sua conta precisa de uma etapa adicional de segurança. Use “Continuar com SSO ou outro método” para concluir o acesso.",
};

/** Friendly copy for `/login?auth_error=<reason>` set by the API when the OAuth callback fails. */
export function authCallbackMessage(reason) {
  if (typeof reason !== "string" || !reason) return undefined;
  return Object.hasOwn(CALLBACK_MESSAGES, reason) ? CALLBACK_MESSAGES[reason] : "Não foi possível concluir o acesso. Entre novamente.";
}
