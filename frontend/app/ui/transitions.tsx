"use client";

import { useEffect, useState, type CSSProperties, type ElementType, type ReactNode } from "react";
import { exitDelayMs, joinClass, MOTION_MS, staggerStyle, type EnterVariant, type StaggerStep } from "./motion-logic";
import { useReducedMotion } from "./use-reduced-motion";

type Common = { as?: ElementType; className?: string; style?: CSSProperties; children?: ReactNode };

/** Entrada na montagem (fade/slide/scale/pop). `origin` ancora o pop no canto da "cauda" da bolha. */
export function Enter({ as, variant = "slide", delay = 0, origin, className, style, children }: Common & { variant?: EnterVariant; delay?: number; origin?: "user" | "assistant" }) {
  const Tag = (as ?? "div") as ElementType;
  return <Tag className={joinClass("mo-enter", className)} data-variant={variant} data-origin={origin} style={{ "--mo-delay": `${delay}ms`, ...style } as CSSProperties}>{children}</Tag>;
}

/**
 * Entrada E saída: mantém o nó montado até a animação de saída terminar.
 * `show` controla; a saída usa `exitMs` (default --motion-fast). Reduced motion: desmonta já.
 */
export function Transition({ show, variant = "fade", exitMs = MOTION_MS.fast, origin, as, className, style, children }: Common & { show: boolean; variant?: EnterVariant; exitMs?: number; origin?: "user" | "assistant" }) {
  const reduced = useReducedMotion();
  const [mounted, setMounted] = useState(show);
  if (show && !mounted) setMounted(true);
  useEffect(() => {
    if (show) return;
    const timer = window.setTimeout(() => setMounted(false), exitDelayMs(reduced, exitMs));
    return () => window.clearTimeout(timer);
  }, [show, reduced, exitMs]);
  if (!show && !mounted) return null;
  const Tag = (as ?? "div") as ElementType;
  return <Tag className={joinClass("mo-enter", className)} data-variant={variant} data-origin={origin} data-state={show ? "open" : "closed"} style={style}>{children}</Tag>;
}

/** Item de lista com stagger. Passe o índice; acima de STAGGER_MAX todos entram juntos. */
export function StaggerItem({ index, step = "sm", as, className, style, children }: Common & { index: number; step?: StaggerStep }) {
  const Tag = (as ?? "div") as ElementType;
  return <Tag className={joinClass("mo-stagger-item", className)} data-step={step === "sm" ? undefined : step} style={{ ...staggerStyle(index), ...style } as CSSProperties}>{children}</Tag>;
}

/** Reveal ao rolar (CSS nativo view()); sem suporte ou com reduced motion o conteúdo já aparece. */
export function Reveal({ variant = "slide", as, className, style, children }: Common & { variant?: "slide" | "fade" }) {
  const Tag = (as ?? "div") as ElementType;
  return <Tag className={joinClass("mo-reveal", className)} data-variant={variant} style={style}>{children}</Tag>;
}

/** Entrada de tela. Use `screenKey` = identificador da tela; a troca remonta e reanima. Só entrada. */
export function ScreenTransition({ screenKey, as, className, style, children }: Common & { screenKey: string }) {
  const Tag = (as ?? "div") as ElementType;
  return <Tag key={screenKey} className={joinClass("mo-screen", className)} style={style}>{children}</Tag>;
}
