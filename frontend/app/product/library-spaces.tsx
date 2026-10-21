"use client";

import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Layers } from "lucide-react";
import { btn } from "../ui";
import { parseSpaceFilter, scopeSummary, serializeSpaceFilter, spaceBadges, type SpaceRef } from "../spaces-model";
import { memberSpaces } from "./spaces-api";
import { spacesApi } from "./spaces-client";

const storageKey = (companyId: string) => `arquivio:library-spaces:${companyId}`;

/** Filtro por Espaço da biblioteca: estado na URL (`?spaces=a,b`) e, só por conveniência, em localStorage (sempre em try/catch). */
export function useLibrarySpaces(companyId: string) {
  const params = useSearchParams();
  const [spaces, setSpaces] = useState<SpaceRef[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const urlValue = params.get("spaces");
  // Sem filtro lembrado a biblioteca carrega já; com filtro, espera validá-lo contra os Espaços da pessoa (evita um 404 por id antigo).
  const [ready, setReady] = useState(() => {
    if (urlValue || typeof window === "undefined") return !urlValue;
    try { return !window.localStorage.getItem(storageKey(companyId)); } catch { return true; }
  });

  useEffect(() => {
    let alive = true;
    spacesApi.listSpaces(companyId).then((list) => {
      if (!alive) return;
      const mine = memberSpaces(list);
      let remembered = "";
      try { remembered = urlValue ?? window.localStorage.getItem(storageKey(companyId)) ?? ""; } catch { remembered = urlValue ?? ""; }
      setSpaces(mine); setSelected(parseSpaceFilter(remembered, mine)); setReady(true);
    }).catch(() => { if (alive) { setSpaces(null); setReady(true); } });
    return () => { alive = false; };
    // A seleção inicial vem da URL só uma vez; depois o estado local manda.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyId]);

  // Mantém a URL em sincronia (outras navegações da tela reescrevem a query e perderiam o filtro).
  useEffect(() => {
    if (!ready) return;
    const next = new URL(window.location.href);
    const wanted = serializeSpaceFilter(selected);
    if ((next.searchParams.get("spaces") ?? "") === wanted) return;
    if (wanted) next.searchParams.set("spaces", wanted); else next.searchParams.delete("spaces");
    window.history.replaceState(window.history.state, "", next.pathname + next.search);
  }, [selected, ready, urlValue]);

  const change = useCallback((next: string[]) => {
    setSelected(next);
    try { window.localStorage.setItem(storageKey(companyId), serializeSpaceFilter(next)); } catch { /* storage unavailable */ }
  }, [companyId]);
  return { spaces, selected, change, ready };
}

/** Chips (multi-seleção, `aria-pressed`) em telas largas; um seletor único em telas estreitas. */
export function SpaceChips({ spaces, selected, onChange }: { spaces: SpaceRef[]; selected: string[]; onChange: (ids: string[]) => void }) {
  const toggle = (id: string) => onChange(selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id]);
  return <div className="library-space-filter">
    <div role="group" aria-label="Filtrar por Espaço" className="library-space-chips">
      <button type="button" className="library-space-chip" aria-pressed={selected.length === 0} onClick={() => onChange([])}>Todos os meus Espaços ({spaces.length})</button>
      {spaces.map((space) => <button key={space.id} type="button" className="library-space-chip" aria-pressed={selected.includes(space.id)} onClick={() => toggle(space.id)}>{space.name}</button>)}
    </div>
    <label className="library-space-select">
      <span className="sr-only">Filtrar por Espaço</span>
      <select value={selected.length === 1 ? selected[0] : ""} onChange={(event) => onChange(event.target.value ? [event.target.value] : [])} aria-describedby="library-space-summary">
        <option value="">Todos os meus Espaços ({spaces.length})</option>
        {spaces.map((space) => <option key={space.id} value={space.id}>{space.name}</option>)}
        {selected.length > 1 && <option value="" disabled>{scopeSummary(selected, spaces)}</option>}
      </select>
    </label>
    <p id="library-space-summary" className="sr-only" role="status" aria-live="polite">Mostrando: {scopeSummary(selected, spaces)}</p>
  </div>;
}

/** Selo(s) de Espaço com texto (nunca só cor); mais de `max` colapsam em “+N”. Sem Espaços (backend antigo): nada. */
export function SpaceBadges({ spaces, max = 2 }: { spaces?: SpaceRef[]; max?: number }) {
  if (!spaces?.length) return null;
  const { visible, hiddenCount } = spaceBadges(spaces, max);
  const hidden = spaces.slice(max).map((space) => space.name).join(", ");
  return <span className="space-badges" aria-label={`Espaços: ${spaces.map((space) => space.name).join(", ")}`}>
    <Layers size={12} aria-hidden="true" />
    {visible.map((name) => <span key={name} className="space-badge" aria-hidden="true">{name}</span>)}
    {hiddenCount > 0 && <span className="space-badge" aria-hidden="true" title={hidden}>+{hiddenCount}</span>}
  </span>;
}

/** Alterna “Agrupar por Espaço” (mesma lista, com cabeçalhos por Espaço). */
export function SpaceGroupToggle({ pressed, onToggle }: { pressed: boolean; onToggle: () => void }) {
  return <button type="button" aria-pressed={pressed} onClick={onToggle} className={btn("secondary", "sm", "mt-3 shrink-0")}><Layers size={14} aria-hidden="true" />Agrupar por Espaço</button>;
}

/** Estados vazios próprios dos Espaços; `null` ⇒ vale o estado vazio comum da biblioteca. Nunca enumera Espaços que a pessoa não tem. */
export function spaceEmptyState({ spaces, selected, canManage, atRoot }: { spaces: SpaceRef[] | null; selected: string[]; canManage: boolean; atRoot: boolean }): { title: string; description: string } | null {
  if (spaces && spaces.length === 0 && !canManage) return { title: "Você ainda não está em nenhum Espaço", description: "Peça acesso a um administrador da organização." };
  if (selected.length > 0 && atRoot) return { title: "Nada nos Espaços escolhidos", description: "Escolha outro Espaço ou volte para “Todos os meus Espaços”." };
  return null;
}
