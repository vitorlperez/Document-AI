"use client";

import { CircleAlert, Trash2 } from "lucide-react";
import { useId } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import { libraryAccessBadge } from "./drive-share-logic";
import type { LibraryNode } from "./types-and-api";
import "./drive-share-flow.css";

/** "Acesso removido / apagando em N dias" — pasta do modo e-mail-robô que perdeu o compartilhamento. Sem `access_state`, não renderiza nada. */
export function LibraryAccessBadge({ item }: { item: LibraryNode }) {
  const badge = libraryAccessBadge(item);
  const id = useId();
  if (!badge) return null;
  const Icon = badge.tone === "error" ? Trash2 : CircleAlert;
  return <Popover>
    <PopoverTrigger asChild>
      <button type="button" className="library-access-trigger" aria-label={`${item.name}: ${badge.label}. Ver detalhes`} title={badge.description}>
        <span className="library-access-badge" data-tone={badge.tone}><Icon size={12} aria-hidden="true" /><span>{badge.label}</span></span>
      </button>
    </PopoverTrigger>
    <PopoverContent className="library-indexing-description" aria-labelledby={`${id}-title`}>
      <p id={`${id}-title`} className="font-semibold">{badge.label}</p>
      <p className="mt-1 text-muted-foreground">{badge.description}</p>
    </PopoverContent>
  </Popover>;
}
