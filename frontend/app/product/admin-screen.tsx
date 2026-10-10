"use client";

import { type Company } from "./types-and-api";
import { UsagePanel } from "./usage-panel";

export function AdminScreen({ company }: { company: Company }) {
  return <div className="space-y-6">
    <header><h1 className="text-2xl font-semibold">Administração</h1><p className="mt-1 text-sm text-muted-foreground">Uso, cotas e qualidade das respostas de {company.name}.</p></header>
    <UsagePanel company={company} />
  </div>;
}
