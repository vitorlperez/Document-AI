"use client";

import { CheckCircle2, CircleAlert, Clock3, FileQuestion, FileX2, LockKeyhole, TriangleAlert } from "lucide-react";
import { useId } from "react";
import { Popover, PopoverContent, PopoverTrigger } from "../../components/ui/popover";
import { libraryIndexingPresentation } from "../library-indexing-status";
import type { LibraryNode } from "./types-and-api";

const ICONS = { check: CheckCircle2, clock: Clock3, warning: TriangleAlert, error: CircleAlert, file: FileQuestion, lock: LockKeyhole, missing: FileX2 };

/** A separate button: pointer tooltip plus a keyboard/touch-accessible explanation. */
export function LibraryIndexingBadge({ item }: { item: LibraryNode }) {
  const status = libraryIndexingPresentation(item);
  const Icon = ICONS[status.icon];
  const id = useId();
  return <Popover>
    <PopoverTrigger asChild>
      <button type="button" className="library-indexing-trigger" aria-label={`${item.name}: ${status.label}. Ver detalhes da indexação`} aria-describedby={`${id}-description`} title={status.description}>
        <span className="library-indexing-badge" data-tone={status.tone}><Icon size={12} aria-hidden="true" /><span>{status.label}</span></span>
      </button>
    </PopoverTrigger>
    <span id={`${id}-description`} className="sr-only">{status.description}</span>
    <PopoverContent className="library-indexing-description" aria-labelledby={`${id}-title`}>
      <p id={`${id}-title`} className="font-semibold">{status.label}</p>
      <p className="mt-1 text-muted-foreground">{status.description}</p>
    </PopoverContent>
  </Popover>;
}
