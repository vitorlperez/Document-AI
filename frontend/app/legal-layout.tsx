import type { ReactNode } from "react";
import Link from "next/link";
import { Brand } from "./brand";
import "./legal.css";

export function LegalLayout({ title, children }: { title: string; children: ReactNode }) {
  return <div className="legal-page">
    <header className="legal-header legal-shell">
      <Link href="/" aria-label="Arquivio, página inicial"><Brand /></Link>
      <nav aria-label="Páginas legais"><Link href="/privacidade">Privacidade</Link><Link href="/termos">Termos de uso</Link></nav>
    </header>
    <main className="legal-main legal-shell" id="conteudo">
      <p className="legal-eyebrow">Arquivio · Informações legais</p>
      <h1>{title}</h1>
      <p className="legal-updated">Última atualização: 28 de setembro de 2026</p>
      {children}
    </main>
    <footer className="legal-footer legal-shell"><span>© {new Date().getFullYear()} Arquivio</span><nav aria-label="Links do rodapé"><Link href="/">Início</Link><Link href="/privacidade">Privacidade</Link><Link href="/termos">Termos de uso</Link></nav></footer>
  </div>;
}
