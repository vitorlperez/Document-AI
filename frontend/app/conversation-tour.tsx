"use client";

import { useEffect, useRef, useState } from "react";
import "./onboarding.css";
import "./interface-motion.css";
import { playSurfaceEntry } from "./interface-motion";

const steps = [
  { target: "composer", title: "Pergunte aos seus documentos", description: "Escreva uma pergunta em linguagem natural e envie. A resposta usa conteúdo já indexado e traz fontes para você conferir. Digite @ para mencionar um arquivo ou pasta." },
  { target: "tools", title: "Escolha onde procurar", description: "Use o seletor de ferramentas para limitar as fontes da pergunta. As menções a arquivos e pastas refinam ainda mais esse escopo." },
  { target: "new-conversation", title: "Um novo assunto, uma nova conversa", description: "Nova conversa limpa o contexto do assunto anterior. Use-a quando quiser começar uma consulta independente." },
  { target: "tool-sidebar", title: "Seu conhecimento, organizado", description: "Escolha uma ferramenta na barra lateral ou na aba Biblioteca para abrir a Biblioteca já com ela selecionada e acompanhar as sincronizações. Responsáveis e administradores também encontram Integrações para conectar fontes." },
  { target: "navigation", title: "Navegue pelo seu espaço", description: "Use as abas no topo — ou o menu no celular — para alternar entre Conversa e Biblioteca. Conforme sua permissão, Integrações conecta fontes, Equipe gerencia os membros e Desenvolvedor configura o acesso por API e MCP." },
];

export type TourExit = "finished" | "dismissed";

export function ConversationTour({ onComplete }: { onComplete: (exit: TourExit) => Promise<void> }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const primary = useRef<HTMLButtonElement>(null);
  const [index, setIndex] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rect, setRect] = useState<{ top: number; left: number; width: number; height: number } | null>(null);
  const [position, setPosition] = useState({ top: 80, left: 16 });
  const step = steps[index];
  const card = useRef<HTMLElement>(null);
  const shownIndex = useRef(index);
  useEffect(() => {
    // Step changes keep the same dialog/card/buttons; only the step text gets a short visual entry.
    if (shownIndex.current === index) return;
    shownIndex.current = index;
    const text = card.current ? Array.from(card.current.querySelectorAll<HTMLElement>(":scope > .onboarding-eyebrow, :scope > #tour-title, :scope > #tour-description")) : [];
    return playSurfaceEntry(text, { offsetY: 6 });
  }, [index]);
  useEffect(() => {
    const modal = dialog.current;
    const previous = document.activeElement as HTMLElement | null;
    modal?.showModal();
    return () => { modal?.close(); if (previous?.isConnected) previous.focus(); };
  }, []);
  useEffect(() => {
    const findVisibleTarget = () => {
      const targetName = step.target === "tool-sidebar" && window.innerWidth < 768 ? "navigation" : step.target;
      const visible = (name: string) => Array.from(document.querySelectorAll<HTMLElement>(`[data-tour="${name}"]`)).find((element) => {
        const bounds = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return bounds.width > 0 && bounds.height > 0 && style.visibility !== "hidden" && style.display !== "none";
      });
      return visible(targetName) ?? (step.target === "tool-sidebar" ? visible("navigation") : undefined);
    };
    findVisibleTarget()?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
    const update = () => {
      const bounds = findVisibleTarget()?.getBoundingClientRect();
      const card = dialog.current?.querySelector<HTMLElement>(".tour-card");
      const cardWidth = Math.min(360, window.innerWidth - 32);
      const cardHeight = card?.offsetHeight ?? 300;
      const visible = bounds && bounds.width > 0 && bounds.height > 0;
      setRect(visible ? { top: Math.max(4, bounds.top - 5), left: Math.max(4, bounds.left - 5), width: Math.min(bounds.width + 10, window.innerWidth - 8), height: Math.min(bounds.height + 10, window.innerHeight - 8) } : null);
      const preferredTop = visible ? bounds.bottom + 14 : 80;
      // Tall targets (the sidebar) would be covered by a card below/above them: place the card beside the target instead.
      if (visible && bounds.height > window.innerHeight * 0.5 && bounds.right + 14 + cardWidth <= window.innerWidth - 16) {
        setPosition({ top: Math.max(16, Math.min(bounds.top + 16, window.innerHeight - cardHeight - 16)), left: bounds.right + 14 });
        return;
      }
      setPosition({
        top: Math.max(16, Math.min(preferredTop + cardHeight > window.innerHeight - 16 && visible ? bounds.top - cardHeight - 14 : preferredTop, window.innerHeight - cardHeight - 16)),
        left: Math.max(16, Math.min(visible ? bounds.left : (window.innerWidth - cardWidth) / 2, window.innerWidth - cardWidth - 16)),
      });
    };
    const frame = window.requestAnimationFrame(() => { update(); primary.current?.focus(); });
    const observer = new ResizeObserver(update);
    for (const target of document.querySelectorAll<HTMLElement>(`[data-tour="${step.target}"], [data-tour="navigation"]`)) observer.observe(target);
    const card = dialog.current?.querySelector<HTMLElement>(".tour-card");
    if (card) observer.observe(card);
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => { window.cancelAnimationFrame(frame); observer.disconnect(); window.removeEventListener("resize", update); window.removeEventListener("scroll", update, true); };
  }, [step.target]);
  async function finish(exit: TourExit = "dismissed") {
    if (busy) return;
    setBusy(true); setError(null);
    try { await onComplete(exit); }
    catch (caught) { setError(caught instanceof Error ? caught.message : "Não foi possível salvar. Tente novamente."); }
    finally { setBusy(false); }
  }
  return <dialog ref={dialog} className="conversation-tour" data-arquivio-motion-root="" aria-labelledby="tour-title" aria-describedby="tour-description" onCancel={(event) => { event.preventDefault(); void finish(); }} onClick={(event) => { if (!busy && !(event.target as HTMLElement).closest(".tour-card")) void finish(); }}>
    <div className={`tour-highlight ${rect ? "" : "tour-highlight-fallback"}`} style={rect ?? undefined} aria-hidden="true" />
    <section ref={card} className="tour-card" style={position} aria-busy={busy} data-arquivio-motion="tour-card">
      <p className="onboarding-eyebrow">Conheça seu espaço · {index + 1} de {steps.length}</p>
      <h2 id="tour-title">{step.title}</h2>
      <p id="tour-description">{step.description}</p>
      {error && <p role="alert" className="onboarding-error">{error}</p>}
      <div className="tour-actions">
        <button disabled={busy} onClick={() => { void finish(); }} className="onboarding-text-button">Pular tour</button>
        {index > 0 && <button disabled={busy} onClick={() => setIndex(index - 1)} className="onboarding-text-button">Voltar</button>}
        <button ref={primary} disabled={busy} onClick={() => { if (index === steps.length - 1) void finish("finished"); else setIndex(index + 1); }} className="onboarding-primary">{busy ? "Salvando…" : index === steps.length - 1 ? "Começar a conversar" : "Próximo"}</button>
      </div>
    </section>
  </dialog>;
}
