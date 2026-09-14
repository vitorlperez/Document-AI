import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Arquivio — Conhecimento com evidências", description: "Pergunte à sua pasta de trabalho e verifique as fontes.", icons: { icon: "/favicon.svg" } };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="pt-BR"><body>{children}</body></html>; }
