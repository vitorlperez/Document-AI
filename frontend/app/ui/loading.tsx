import type { CSSProperties, ElementType, ReactNode } from "react";
import { clampProgress, joinClass } from "./motion-logic";

/** Spinner único (substitui sync-spin / ts-turn / library-card-spin). Reduced motion: anel estático. */
export function Spinner({ size = 16, label, className }: { size?: number; label?: string; className?: string }) {
  const svg = <svg className={joinClass("mo-spinner", className)} width={size} height={size} viewBox="0 0 24 24" aria-hidden="true"><circle className="mo-spinner-track" cx="12" cy="12" r="9" /><circle className="mo-spinner-arc" cx="12" cy="12" r="9" /></svg>;
  return label ? <span role="status" aria-live="polite" className="inline-flex items-center gap-2">{svg}<span>{label}</span></span> : svg;
}

/** Barra de progresso. `value` 0–100 = determinada; omitido/null = indeterminada. */
export function ProgressIndicator({ value, label, className }: { value?: number | null; label: string; className?: string }) {
  const determinate = typeof value === "number";
  const pct = determinate ? clampProgress(value) : undefined;
  const style = determinate ? ({ "--mo-progress": (pct as number) / 100 } as CSSProperties) : undefined;
  return <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} {...(determinate ? {} : { "data-indeterminate": "" })} className={joinClass("mo-progress", className)}><div className="mo-progress-bar" style={style} /></div>;
}

/** Shimmer de superfície (default) ou de texto (variant="text"), p.ex. "Consultando os arquivos…". */
export function Shimmer({ as, variant = "surface", className, style, children }: { as?: ElementType; variant?: "surface" | "text"; className?: string; style?: CSSProperties; children?: ReactNode }) {
  const Tag = (as ?? "span") as ElementType;
  return <Tag data-variant={variant} className={joinClass("mo-shimmer", className)} style={style}>{children}</Tag>;
}
