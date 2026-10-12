import type { CSSProperties, ReactNode } from "react";
import { joinClass, skeletonLineWidths } from "./motion-logic";

type SkeletonProps = { className?: string; style?: CSSProperties; width?: CSSProperties["width"]; height?: CSSProperties["height"] };

const dims = (p: SkeletonProps): CSSProperties => ({ width: p.width, height: p.height, ...p.style });

/** Bloco base com shimmer. Decorativo (aria-hidden): envolva a área em <LoadingBlock>. */
export function Skeleton({ className, ...p }: SkeletonProps) {
  return <span aria-hidden="true" className={joinClass("mo-skeleton", className)} style={dims(p)} />;
}
export function SkeletonLine({ className, ...p }: SkeletonProps) {
  return <span aria-hidden="true" data-shape="line" className={joinClass("mo-skeleton", className)} style={dims(p)} />;
}
export function SkeletonBlock({ height = "6rem", className, ...p }: SkeletonProps) {
  return <span aria-hidden="true" className={joinClass("mo-skeleton", className)} style={dims({ ...p, height })} />;
}
export function SkeletonAvatar({ size = 40, className, style }: { size?: number; className?: string; style?: CSSProperties }) {
  return <span aria-hidden="true" data-shape="circle" className={joinClass("mo-skeleton", className)} style={{ width: size, height: size, ...style }} />;
}
/** Parágrafo: `lines` linhas com larguras determinísticas (última mais curta). */
export function SkeletonText({ lines = 3, className }: { lines?: number; className?: string }) {
  return <span aria-hidden="true" className={joinClass("mo-skeleton-stack", className)}>{skeletonLineWidths(lines).map((w, i) => <SkeletonLine key={i} width={w} />)}</span>;
}
/** Card: título + texto + bloco opcional de mídia. */
export function SkeletonCard({ media = false, lines = 2, className }: { media?: boolean; lines?: number; className?: string }) {
  return <span aria-hidden="true" className={joinClass("mo-skeleton-card", className)}>{media && <SkeletonBlock height="7rem" />}<SkeletonLine width="55%" /><SkeletonText lines={lines} /></span>;
}
/** Lista: `rows` linhas com avatar/ícone + 2 linhas de texto. */
export function SkeletonList({ rows = 5, avatar = true, className }: { rows?: number; avatar?: boolean; className?: string }) {
  return <span aria-hidden="true" className={joinClass("mo-skeleton-stack", className)} style={{ gap: "0.875rem" }}>{Array.from({ length: rows }, (_, i) => <span key={i} className="mo-skeleton-row">{avatar && <SkeletonAvatar size={32} />}<span className="mo-skeleton-stack"><SkeletonLine width={i % 2 ? "70%" : "85%"} /><SkeletonLine width="45%" /></span></span>)}</span>;
}

/** Envelope acessível: role=status + aria-busy + texto só para leitor de tela. Coloque os skeletons dentro. */
export function LoadingBlock({ label = "Carregando…", children, className }: { label?: string; children?: ReactNode; className?: string }) {
  return <div role="status" aria-live="polite" aria-busy="true" className={className}><span className="sr-only">{label}</span>{children}</div>;
}
