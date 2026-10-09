"use client";

import { ArrowLeft, ArrowRight, Check, Eye, EyeOff, FileText, LockKeyhole, Quote, ShieldCheck } from "lucide-react";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { Brand } from "../brand";
import { ThemeToggle } from "../theme-toggle";
import { safeInvitationReturnTo } from "./auth-navigation.mjs";
import { ApiError, api, messageFor } from "./types-and-api";
import "../custom-login.css";

type Mode = "sign-in" | "sign-up" | "forgot" | "reset" | "verify";
type AuthResult = { status: "authenticated" | "email_verification_required" | "hosted_authentication_required" | "registration_pending"; redirect_url?: string };

export function SignIn({ onLogin, initialMode = "sign-in", resetToken, returnTo, passwordReset = false }: {
  onLogin: () => void; initialMode?: "sign-in" | "sign-up"; resetToken?: string; returnTo?: string; passwordReset?: boolean;
}) {
  const [mode, setMode] = useState<Mode>(resetToken ? "reset" : initialMode);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(passwordReset ? "Senha atualizada. Entre com sua nova senha." : null);
  const [hostedRequired, setHostedRequired] = useState(false);
  const [resendAfter, setResendAfter] = useState(0);
  const changeMode = (next: Mode) => { setMode(next); setPassword(""); setCode(""); setError(null); setNotice(null); setHostedRequired(false); setVisible(false); };
  const copy = {
    "sign-in": { eyebrow: "Seu conhecimento, de volta à mão", title: "Bem-vindo de volta.", description: "Entre no seu espaço e encontre a próxima resposta.", action: "Entrar" },
    "sign-up": { eyebrow: "Um lugar para o que sua equipe sabe", title: "Comece pelo conhecimento.", description: "Confirme seu e-mail pelo link que enviaremos. Depois, escolha sua senha.", action: "Criar minha conta" },
    forgot: { eyebrow: "Vamos recuperar seu acesso", title: "Esqueceu a senha?", description: "Informe seu e-mail. Enviaremos um link para você criar uma nova senha.", action: "Enviar link de recuperação" },
    reset: { eyebrow: "Um novo começo", title: "Escolha uma nova senha.", description: "Use uma senha de pelo menos 8 caracteres para proteger sua conta.", action: "Salvar nova senha" },
    verify: { eyebrow: "Falta só confirmar", title: "Confira seu e-mail.", description: `Digite o código de 6 dígitos enviado para ${email}.`, action: "Confirmar e entrar" },
  }[mode];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError(null); setNotice(null); setHostedRequired(false);
    try {
      if (mode === "forgot") {
        await api("/auth/password-reset", { method: "POST", body: JSON.stringify({ email }) });
        setNotice("Se este e-mail tiver uma conta, você receberá um link para redefinir a senha. Confira também o spam.");
      } else if (mode === "reset") {
        const result = await api<{ return_to?: string }>("/auth/password-reset/confirm", { method: "POST", body: JSON.stringify({ token: resetToken, password }) });
        const query = new URLSearchParams({ password_reset: "1" });
        const destination = safeInvitationReturnTo(result.return_to ?? returnTo);
        if (destination) query.set("return_to", destination);
        window.location.replace(`/login?${query.toString()}`);
      } else {
        const result = await api<AuthResult>(mode === "verify" ? "/auth/verify-email" : mode === "sign-up" ? "/auth/register" : "/auth/password", {
          method: "POST", body: JSON.stringify(mode === "verify" ? { code, return_to: returnTo } : mode === "sign-up" ? { email, return_to: returnTo } : { email, password, return_to: returnTo }),
        });
        setPassword("");
        if (result.status === "registration_pending") setNotice("Confira seu e-mail para confirmar o endereço e escolher sua senha. Se você já tem conta, o link permite recuperar seu acesso.");
        else if (result.status === "authenticated" && result.redirect_url) window.location.replace(result.redirect_url);
        else if (result.status === "email_verification_required") { setMode("verify"); setCode(""); }
        else if (result.status === "hosted_authentication_required") { setHostedRequired(true); setNotice("Sua conta precisa de uma etapa adicional de segurança. Continue para concluir o acesso."); }
      }
    } catch (caught) {
      setError(caught instanceof ApiError && caught.status === 422 ? "Confira os dados informados e tente novamente." : messageFor(caught));
    } finally { setBusy(false); }
  }

  async function resendCode() {
    if (busy) return;
    setBusy(true); setError(null); setNotice(null);
    try {
      if (Date.now() < resendAfter) { setNotice("Aguarde um minuto antes de solicitar outro código."); return; }
      await api("/auth/verify-email/resend", { method: "POST" });
      setResendAfter(Date.now() + 60_000);
      setNotice("Novo código solicitado. Confira seu e-mail e use o código mais recente.");
    } catch (caught) { setError(messageFor(caught)); }
    finally { setBusy(false); }
  }

  return <main className="login-page">
    <aside className="login-story" aria-label="Conheça o Arquivio">
      <Link href="/" className="login-story-brand" aria-label="Arquivio — início"><Brand /></Link>
      <div className="login-story-content"><p className="login-eyebrow">Conhecimento que conecta</p><h2>Sua equipe sabe.<br />Encontre a resposta.</h2><p>Transforme o que está nos seus documentos em clareza para o próximo passo.</p>
        <div className="login-preview" aria-hidden="true"><div className="login-preview-file"><FileText size={18} /><span>Conhecimento da equipe</span><Check size={16} /></div><div className="login-preview-answer"><Quote size={21} /><p>A resposta certa começa<br />com uma fonte confiável.</p><span><span className="login-source-dot" /> Fontes conectadas · Contexto preservado</span></div></div>
      </div>
      <p className="login-story-footer"><ShieldCheck size={17} /> Os originais permanecem nas fontes conectadas.</p>
    </aside>
    <section className="login-form-side"><ThemeToggle className="theme-toggle-floating" /><Link href="/" className="login-mobile-brand"><Brand /></Link><div className="login-form-container">
      <p className="login-eyebrow">{copy.eyebrow}</p><h1>{copy.title}</h1><p className="login-description">{copy.description}</p>
      <form onSubmit={(event) => { void submit(event); }} className="login-form" aria-busy={busy}>
        {mode !== "reset" && mode !== "verify" && <div className="login-field"><label htmlFor="login-email">E-mail</label><input id="login-email" type="email" autoComplete="email" name="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="voce@empresa.com" disabled={busy} /></div>}
        {(mode === "sign-in" || mode === "reset") && <div className="login-field"><div className="login-label-row"><label htmlFor="login-password">{mode === "reset" ? "Nova senha" : "Senha"}</label>{mode === "sign-in" && <button type="button" onClick={() => changeMode("forgot")} disabled={busy} className="login-text-button">Esqueceu a senha?</button>}</div><div className="login-password"><input id="login-password" name="password" type={visible ? "text" : "password"} autoComplete={mode === "sign-in" ? "current-password" : "new-password"} required minLength={mode === "sign-in" ? 1 : 8} maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} disabled={busy} aria-describedby={mode !== "sign-in" ? "login-password-hint" : undefined} /><button type="button" onClick={() => setVisible(!visible)} className="login-eye" aria-label={visible ? "Ocultar senha" : "Mostrar senha"} aria-pressed={visible} disabled={busy}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>{mode !== "sign-in" && <p id="login-password-hint" className="login-hint">Pelo menos 8 caracteres.</p>}</div>}
        {mode === "verify" && <div className="login-field"><label htmlFor="login-code">Código de confirmação</label><input id="login-code" className="login-code" name="code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} required value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, ""))} disabled={busy} /></div>}
        {error && <p role="alert" className="login-error">{error}</p>}{notice && <p role="status" className="login-notice">{notice}</p>}
        {hostedRequired ? <button type="button" onClick={onLogin} className="login-primary">Continuar com segurança <ArrowRight size={17} /></button> : <button type="submit" disabled={busy} className="login-primary">{busy ? "Aguarde…" : copy.action}<ArrowRight size={17} aria-hidden="true" /></button>}
      </form>
      {mode === "verify" && <button type="button" disabled={busy} onClick={() => { void resendCode(); }} className="login-text-button">Reenviar código</button>}
      {(mode === "sign-in" || mode === "sign-up") ? <><div className="login-divider"><span>ou</span></div><button type="button" onClick={onLogin} disabled={busy} className="login-secondary"><ShieldCheck size={18} aria-hidden="true" /> Continuar com SSO ou outro método</button><p className="login-switch">{mode === "sign-in" ? "Ainda não tem uma conta?" : "Já tem uma conta?"} <button type="button" disabled={busy} onClick={() => changeMode(mode === "sign-in" ? "sign-up" : "sign-in")} className="login-text-button">{mode === "sign-in" ? "Criar conta" : "Entrar"}</button></p></> : <button type="button" disabled={busy} onClick={() => changeMode("sign-in")} className="login-back"><ArrowLeft size={16} /> Voltar para entrar</button>}
      <p className="login-security"><LockKeyhole size={13} aria-hidden="true" /> Acesso protegido para o conhecimento da sua equipe.</p>
    </div></section>
  </main>;
}
