// Lógica pura dos primitives de motion (sem React/DOM): testável com node --test.
// Os números espelham app/ui/motion-tokens.css; tests/ui-primitives.test.mjs garante que não divergem.

export const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

/** Durações em ms (espelho de --motion-*). Usadas só para temporizar o desmonte após a saída. */
export const MOTION_MS = { instant: 80, fast: 120, base: 180, medium: 280, slow: 420, enter: 600 } as const;

/** Itens além deste índice entram junto com o último (evita cascata longa). */
export const STAGGER_MAX = 8;
export const STAGGER_STEPS = ["sm", "md", "lg"] as const;
export type StaggerStep = (typeof STAGGER_STEPS)[number];

export const ENTER_VARIANTS = ["fade", "slide", "slide-x", "scale", "pop"] as const;
export type EnterVariant = (typeof ENTER_VARIANTS)[number];

/** Índice efetivo do stagger: inteiro >= 0, limitado a STAGGER_MAX. */
export function staggerIndex(index: number): number {
  if (!Number.isFinite(index) || index < 0) return 0;
  return Math.min(Math.floor(index), STAGGER_MAX);
}

/** Estilo inline do item de lista: só define a variável CSS; o atraso real vem dos tokens. */
export function staggerStyle(index: number): Record<"--mo-i", number> {
  return { "--mo-i": staggerIndex(index) };
}

/** Quanto esperar antes de desmontar um nó em saída. Reduced motion = 0 (sem animação de saída). */
export function exitDelayMs(reduced: boolean, exitMs: number = MOTION_MS.fast): number {
  return reduced ? 0 : Math.max(0, exitMs);
}

/** Percentual de progresso seguro para aria-valuenow e scaleX (0–100, inteiro). */
export function clampProgress(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.round(Math.min(100, Math.max(0, value)));
}

/** Larguras variadas e determinísticas para linhas de skeleton (sem Math.random: SSR estável). */
export function skeletonLineWidths(count: number, last = "60%"): string[] {
  const pattern = ["100%", "92%", "96%", "88%"];
  const total = Math.max(1, Math.floor(count));
  return Array.from({ length: total }, (_, i) => (i === total - 1 && total > 1 ? last : pattern[i % pattern.length]));
}

/** Classe CSS de variantes, sem depender de clsx nos testes. */
export function joinClass(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}
