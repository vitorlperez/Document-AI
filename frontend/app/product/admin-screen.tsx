"use client";

import { Enter } from "../ui";
import { type Company } from "./types-and-api";
import { InsightsPanel } from "./insights-panel";
import { UsagePanel } from "./usage-panel";

export function AdminScreen({ company, setNotice, setError }: { company: Company; setNotice?: (message: string | null) => void; setError?: (message: string | null) => void }) {
  return <Enter variant="fade" className="space-y-6">
    <header><h1 className="text-2xl font-semibold">Administração</h1><p className="mt-1 text-sm text-muted-foreground">Uso, cotas e qualidade das respostas de {company.name}.</p></header>
    <UsagePanel company={company} />
    <InsightsPanel company={company} setNotice={setNotice} setError={setError} />
  </Enter>;
}
