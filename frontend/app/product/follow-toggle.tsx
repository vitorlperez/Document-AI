"use client";

import { BellRing } from "lucide-react";
import { useState } from "react";
import { api, messageFor } from "./types-and-api";

/** "Seguir" switch for a saved query; drop it next to any saved-query row (needs organizationId). */
export function FollowToggle({ organizationId, savedQueryId, followed, onChange, onError }: { organizationId: string; savedQueryId: string; followed: boolean; onChange?: (followed: boolean) => void; onError?: (message: string) => void }) {
  const [value, setValue] = useState(followed);
  const [busy, setBusy] = useState(false);
  async function toggle() {
    setBusy(true);
    try { const saved = await api<{ followed: boolean }>(`/saved-queries/${savedQueryId}/follow?organization_id=${organizationId}`, { method: "PUT", body: JSON.stringify({ followed: !value }) }); setValue(saved.followed); onChange?.(saved.followed); }
    catch (caught) { onError?.(messageFor(caught)); } finally { setBusy(false); }
  }
  return <button type="button" role="switch" aria-checked={value} disabled={busy} onClick={() => void toggle()} title={value ? "Parar de seguir" : "Seguir: avisar quando a resposta mudar"} className={`inline-flex min-h-9 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-semibold ${value ? "border-primary text-primary" : "border-line text-muted-foreground"}`}><BellRing size={14} aria-hidden="true" />{value ? "Seguindo" : "Seguir"}</button>;
}
