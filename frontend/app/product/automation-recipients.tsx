"use client";

import { useState } from "react";
import { filterRecipients } from "./automation-delivery-model";
import { LoadingBlock, SkeletonList } from "../ui";

export type RecipientOption = { user_id: string; name: string | null; email: string; has_access: boolean | null; is_you: boolean };
export function AutomationRecipients({ items, selected, loading, error, onChange, onRetry }: { items: RecipientOption[]; selected: string[]; loading: boolean; error: string | null; onChange: (ids: string[]) => void; onRetry: () => void }) {
  const [query, setQuery] = useState("");
  const filtered = filterRecipients(items, query);
  const unavailable = selected.filter((id) => !items.some((item) => item.user_id === id));
  return <fieldset className="min-w-0 space-y-3">
    <legend className="font-semibold">Destinatários da organização</legend>
    <label className="block text-sm">Buscar por nome ou e-mail<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} className="mt-2 min-h-11 w-full rounded-lg border border-line bg-panel px-3 py-2 focus-visible:outline-2 focus-visible:outline-primary" /></label>
    <p className="text-sm text-muted-foreground">Quem não tiver acesso a todas as pastas selecionadas será ignorado na execução e não receberá o resultado.</p>
    {loading ? <LoadingBlock label="Carregando destinatários e permissões…"><SkeletonList rows={3} /></LoadingBlock> : error ? <div role="alert"><p className="text-sm text-rose-700">Não foi possível consultar os destinatários: {error}</p><button type="button" onClick={onRetry} className="mt-2 min-h-11 rounded-lg border border-line px-3 focus-visible:outline-2 focus-visible:outline-primary">Tentar novamente</button></div> : <>
      <p role="status" className="text-sm text-muted-foreground">{filtered.length} destinatário(s) encontrado(s) · {selected.length} selecionado(s)</p>
      <div className="max-h-80 space-y-2 overflow-y-auto">{filtered.map((recipient) => <label key={recipient.user_id} className="flex min-h-11 items-start gap-3 rounded-lg border border-line p-3">
        <input type="checkbox" className="mt-1 shrink-0" checked={selected.includes(recipient.user_id)} onChange={(event) => onChange(event.target.checked ? [...selected, recipient.user_id] : selected.filter((id) => id !== recipient.user_id))} />
        <span className="min-w-0 text-sm"><span className="block break-words font-semibold">{recipient.email}{recipient.is_you ? " (você)" : ""}</span>{recipient.name && <span className="block break-all text-muted-foreground">{recipient.name}</span>}{recipient.has_access === false && <span className="mt-1 block text-amber-800">Sem acesso a todas as pastas: não receberá este resultado.</span>}</span>
      </label>)}</div>
      {!filtered.length && <p className="text-sm">{items.length ? "Nenhum destinatário corresponde à busca." : "Nenhum destinatário disponível."}</p>}
      {!!unavailable.length && <div className="rounded-lg border border-amber-200 p-3 text-sm"><p>Há {unavailable.length} destinatário(s) salvo(s) que não está(ão) no catálogo atual. Remova-os se já saíram da organização.</p><button type="button" className="mt-2 min-h-11 underline focus-visible:outline-2 focus-visible:outline-primary" onClick={() => onChange(selected.filter((id) => !unavailable.includes(id)))}>Remover destinatários indisponíveis</button></div>}
    </>}
  </fieldset>;
}
