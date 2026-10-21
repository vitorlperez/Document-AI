"use client";

import { Check, ChevronDown, Layers } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { lookingInLabel } from "../question-spaces";
import { parseSpaceFilter } from "../spaces-model";
import type { SpaceRef } from "../spaces-model";
import { memberSpaces } from "./spaces-api";
import { spacesApi } from "./spaces-client";
import "../question-scope.css";

/** Espaços da pessoa para o filtro opcional do chat. `null` = ainda não carregou ou indisponível: a faixa some e a pergunta segue unificada. */
export function useChatSpaces(companyId: string) {
  const [spaces, setSpaces] = useState<SpaceRef[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    spacesApi.listSpaces(companyId).then((list) => { if (!alive) return; const mine = memberSpaces(list); setSpaces(mine); const fromBridge = parseSpaceFilter(window.location.search, mine); if (fromBridge.length) setSelected(fromBridge); }).catch(() => { if (alive) setSpaces(null); });
    return () => { alive = false; setSelected([]); };
  }, [companyId]);
  return { spaces, selected, setSelected };
}

/** Botão compacto “Espaços” ao lado de Ferramentas no composer. O clique abre o seletor (multi-seleção; vazio = todos). Com 1 Espaço só mostra o nome, sem seletor. */
export function SpaceScopeBar({ spaces, selected, onChange, disabled }: { spaces: SpaceRef[] | null; selected: string[]; onChange: (ids: string[]) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { setOpen(false); trigger.current?.focus(); } };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  if (!spaces || spaces.length === 0) return null;
  const label = lookingInLabel(selected, spaces);
  const chosen = selected.filter((id) => spaces.some((space) => space.id === id)).length;
  const summary = chosen === 0 || chosen >= spaces.length ? "Todos os Espaços" : chosen === 1 ? spaces.find((space) => space.id === selected[0])?.name ?? "1 Espaço" : `${chosen} Espaços`;
  const shortValue = chosen === 0 || chosen >= spaces.length ? "Todos" : chosen === 1 ? summary : `${chosen} selecionados`;
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
  if (spaces.length === 1) return <p className="space-scope-chip" role="status" title={`Procurando em: ${label}`}><Layers size={14} aria-hidden="true" /><span className="space-scope-label">{label}</span></p>;
  return <div ref={root} className="question-scope space-scope">
    <button ref={trigger} type="button" className="question-scope-trigger" data-active={chosen > 0 && chosen < spaces.length ? "true" : undefined} aria-label={`Espaços: ${summary}`} title={summary} aria-expanded={open} aria-controls="space-scope-menu" disabled={disabled} onClick={() => setOpen((value) => !value)}>
      <Layers size={14} aria-hidden="true" /><span className="question-scope-kind" aria-hidden="true">Espaços</span><span className="question-scope-summary question-scope-value space-scope-label">{shortValue}</span><ChevronDown size={12} aria-hidden="true" className="question-scope-chevron" />
    </button>
    {open && <div id="space-scope-menu" className="question-scope-menu" role="group" aria-label="Escolher Espaços da pergunta">
      <button type="button" className="question-scope-option" aria-pressed={selected.length === 0} onClick={() => onChange([])}><span className="question-scope-check">{selected.length === 0 && <Check size={16} />}</span>Todos os meus Espaços ({spaces.length})</button>
      {spaces.map((space) => <button type="button" key={space.id} className="question-scope-option" aria-pressed={selected.includes(space.id)} onClick={() => toggle(space.id)}><span className="question-scope-check">{selected.includes(space.id) && <Check size={16} />}</span>{space.name}</button>)}
    </div>}
  </div>;
}
