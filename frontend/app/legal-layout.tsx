import type { ReactNode } from "react";
import { Brand } from "./brand";
import "./legal.css";
import { ThemeToggle } from "./theme-toggle";

export function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  return <div className="legal-page">
    <header className="legal-header legal-shell">
      <a href="/" aria-label="Arquivio, página inicial"><Brand /></a>
      <ThemeToggle /><nav aria-label="Páginas legais"><a href="/privacidade">Privacidade</a><a href="/termos">Termos de uso</a></nav>
    </header>
    <main className="legal-main legal-shell" id="conteudo">
      <p className="legal-eyebrow">Arquivio · Informações legais</p>
      <h1>{title}</h1>
      <p className="legal-updated">Última atualização: 28 de setembro de 2026</p>
      {children}
    </main>
    <footer className="legal-footer legal-shell"><span>© {new Date().getFullYear()} Arquivio</span><nav aria-label="Links do rodapé"><a href="/">Início</a><a href="/privacidade">Privacidade</a><a href="/termos">Termos de uso</a></nav></footer>
  </div>;
}
