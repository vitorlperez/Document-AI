import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Arquivio — O conhecimento da sua equipe, com fontes",
  description: "Conecte o Google Drive, escolha os documentos da sua equipe e encontre respostas com IA e referências verificáveis. Conhecimento compartilhado para agências, consultorias e empresas.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Arquivio — Sua equipe sabe. Encontre a resposta.",
    description: "Transforme documentos do Google Drive em uma base de conhecimento para sua equipe. Pergunte, encontre e confira as fontes.",
    locale: "pt_BR",
    type: "website",
  },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="pt-BR"><body>{children}</body></html>; }
