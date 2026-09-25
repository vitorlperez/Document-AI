import { Layers3 } from "lucide-react";
import "./brand.css";

/** The same wordmark appears in the landing, entry screens, and workspace. */
export function Brand({ compact = false }: { compact?: boolean }) {
  return <span className={`arquivio-brand${compact ? " arquivio-brand-compact" : ""}`}><Layers3 size={23} strokeWidth={1.7} aria-hidden="true" /><span>arquivio<span className="arquivio-brand-period">.</span></span></span>;
}
