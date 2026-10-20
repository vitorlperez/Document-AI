"use client";

import { Check, ChevronDown, Layers } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { lookingInLabel } from "../question-spaces";
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
    spacesApi.listSpaces(companyId).then((list) => { if (alive) setSpaces(memberSpaces(list)); }).catch(() => { if (alive) setSpaces(null); });
    return () => { alive = false; setSelected([]); };
  }, [companyId]);
  return { spaces, selected, setSelected };
}

/** Faixa fixa sob o composer: “Procurando em: todos os meus Espaços (3)”. O clique abre o seletor (multi-seleção; vazio = todos). */
export function SpaceScopeBar({ spaces, selected, onChange, disabled }: { spaces: SpaceRef[] | null; selected: string[]; onChange: (ids: string[]) => void; disabled: boolean }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", close); document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", escape); };
  }, [open]);
  if (!spaces || spaces.length === 0) return null;
  const label = lookingInLabel(selected, spaces);
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
  if (spaces.length === 1) return <p className="space-scope-bar" role="status"><Layers size={13} aria-hidden="true" />Procurando em: <b>{label}</b></p>;
  return <div ref={root} className="question-scope space-scope-bar">
    <button type="button" className="space-scope-trigger" aria-expanded={open} aria-controls="space-scope-menu" disabled={disabled} onClick={() => setOpen((value) => !value)}>
      <Layers size={13} aria-hidden="true" /><span>Procurando em: <b>{label}</b></span><ChevronDown size={14} aria-hidden="true" />
    </button>
    {open && <div id="space-scope-menu" className="question-scope-menu" role="group" aria-label="Escolher Espaços da pergunta">
      <button type="button" className="question-scope-option" aria-pressed={selected.length === 0} onClick={() => onChange([])}><span className="question-scope-check">{selected.length === 0 && <Check size={15} />}</span>Todos os meus Espaços ({spaces.length})</button>
      {spaces.map((space) => <button type="button" key={space.id} className="question-scope-option" aria-pressed={selected.includes(space.id)} onClick={() => toggle(space.id)}><span className="question-scope-check">{selected.includes(space.id) && <Check size={15} />}</span>{space.name}</button>)}
    </div>}
  </div>;
}
