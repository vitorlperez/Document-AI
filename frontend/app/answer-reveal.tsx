"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useReducedMotion } from "./ui";
import { revealDurationMs, revealPlan, revealedText, revealedUnits } from "./answer-reveal-logic";

/** Upper bound of a reveal, so callers that wait for it can always give up. */
export const REVEAL_MAX_MS = 3600;

/**
 * Shows `text` progressively when `animate` is on (a live answer), instantly otherwise (restored history,
 * reduced motion). `onProgress` fires after each visible growth so the transcript can follow the text.
 */
export function useAnswerReveal(text: string, animate: boolean, { onProgress, onDone }: { onProgress?: () => void; onDone?: () => void } = {}) {
  const plan = useMemo(() => revealPlan(text), [text]);
  const reduced = useReducedMotion();
  const instant = !animate || reduced;
  const [revealed, setUnits] = useState(0);
  const units = instant ? plan.length : revealed;
  const callbacks = useRef({ onProgress, onDone });
  useEffect(() => { callbacks.current = { onProgress, onDone }; });
  useEffect(() => {
    if (instant || plan.length === 0) {
      callbacks.current.onDone?.();
      return;
    }
    const duration = revealDurationMs(plan.length);
    const start = performance.now();
    let frame = 0;
    let shown = 0;
    const tick = (now: number) => {
      const next = revealedUnits(plan.length, now - start, duration);
      if (next !== shown) { shown = next; setUnits(next); }
      if (next >= plan.length) { callbacks.current.onDone?.(); return; }
      frame = window.requestAnimationFrame(tick);
    };
    frame = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frame);
  }, [plan, instant]);
  useEffect(() => { if (units > 0) callbacks.current.onProgress?.(); }, [units]);
  const done = units >= plan.length;
  return { text: done ? text : revealedText(text, plan, units), done };
}
