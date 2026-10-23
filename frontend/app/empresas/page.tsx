import type { Metadata } from "next";
import { ProductApp } from "../product-app";

export const metadata: Metadata = {
  title: "Arquivio para empresas | O conhecimento do time, em uma só pergunta",
  description: "Seu time pergunta, o Arquivio responde e mostra de qual documento veio. Conecte Drive, OneDrive, Notion, SharePoint e ClickUp em leitura. Teste grátis por 14 dias.",
};

export default function BusinessLandingRoute() {
  return <ProductApp screen="home" />;
}
