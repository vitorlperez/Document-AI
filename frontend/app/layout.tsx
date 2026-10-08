import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  referrer: "no-referrer",
  title: "Arquivio — O conhecimento da sua equipe, com fontes",
  description: "Conecte Google Drive, OneDrive, Notion e SharePoint para encontrar respostas com IA e referências verificáveis nos documentos da sua equipe.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Arquivio — Sua equipe sabe. Encontre a resposta.",
    description: "Reúna documentos de Google Drive, OneDrive, Notion e SharePoint em uma base de conhecimento para sua equipe. Pergunte, encontre e confira as fontes.",
    locale: "pt_BR",
    type: "website",
  },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="pt-BR"><body>{children}</body></html>; }
