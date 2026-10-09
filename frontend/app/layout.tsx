import type { Metadata } from "next";
import "./globals.css";
import "./theme-toggle.css";
import { ThemeProvider } from "./theme-provider";
export const metadata: Metadata = {
  metadataBase: new URL("https://www.arquivio.com.br"),
  alternates: { canonical: "/" },
  referrer: "no-referrer",
  title: "Arquivio — O conhecimento da sua equipe, com fontes",
  description: "Conecte Google Drive, OneDrive, Notion e SharePoint para encontrar respostas com IA e referências verificáveis nos documentos da sua equipe.",
  icons: { icon: "/favicon.svg" },
  openGraph: {
    title: "Arquivio — Sua equipe sabe. Encontre a resposta.",
    description: "Reúna documentos de Google Drive, OneDrive, Notion e SharePoint em uma base de conhecimento para sua equipe. Pergunte, encontre e confira as fontes.",
    locale: "pt_BR",
    type: "website",
    url: "/",
    siteName: "Arquivio",
  },
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="pt-BR" suppressHydrationWarning><body><ThemeProvider>{children}</ThemeProvider></body></html>; }
