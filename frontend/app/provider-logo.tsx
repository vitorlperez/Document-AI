import type { CSSProperties } from "react";

export type ProviderLogoName = "google" | "google_drive" | "notion" | "onedrive" | "sharepoint" | "github" | "teams";

const labels: Record<ProviderLogoName, string> = { google: "Google Drive", google_drive: "Google Drive", notion: "Notion", onedrive: "OneDrive", sharepoint: "SharePoint", github: "GitHub", teams: "Microsoft Teams" };

export function ProviderLogo({ provider, size = 24, decorative = true, className = "" }: { provider: ProviderLogoName; size?: number; decorative?: boolean; className?: string }) {
  const key = provider === "google_drive" ? "google" : provider;
  const accessibility = decorative ? { "aria-hidden": true as const } : { role: "img", "aria-label": labels[provider] };
  return <span {...accessibility} className={`provider-logo provider-logo-${key} ${className}`.trim()} style={{ "--provider-logo-size": `${size}px` } as CSSProperties}>
    {key === "google" && <svg viewBox="0 0 24 24"><path fill="#0F9D58" d="M8.1 3h5.2l7.5 13h-5.2z"/><path fill="#F4B400" d="M8.1 3 .6 16h5.2l7.5-13z"/><path fill="#4285F4" d="M5.8 16h15l-2.6 4.5h-15z"/></svg>}
    {key === "notion" && <svg viewBox="0 0 24 24"><rect x="2.5" y="2.5" width="19" height="19" rx="1.5" fill="#fff" stroke="#151b18" strokeWidth="1.5"/><path fill="#151b18" d="M7 17V7.5l2.4-.3 5.7 8V8.5l-1.8-.3V7h4.8v1.2l-1.5.3V17h-2.2L8.6 8.9v6.8l1.9.3v1z"/></svg>}
    {key === "onedrive" && <svg viewBox="0 0 24 24"><path fill="#1686D9" d="M9.5 7.2a5.4 5.4 0 0 1 9.8 2.2 4 4 0 0 1 .7 7.9H7.2A4.7 4.7 0 0 1 9.5 7.2Z"/><path fill="#075CAD" d="M3.9 16.9a3.8 3.8 0 0 1 4.5-6 5.3 5.3 0 0 1 7.6 4.8c0 .5-.1.9-.2 1.3Z"/></svg>}
    {key === "sharepoint" && <svg viewBox="0 0 24 24"><circle cx="10" cy="8" r="6" fill="#036C70"/><circle cx="16.5" cy="13.5" r="4.5" fill="#1A9BA1"/><circle cx="10.5" cy="18" r="3.5" fill="#37C6D0"/><rect x="2" y="7" width="10" height="10" rx="1.5" fill="#038387"/><path fill="#fff" d="M9.3 9.4c-.5-.3-1.1-.5-1.8-.5-1.3 0-2.1.7-2.1 1.7 0 .9.6 1.3 1.6 1.7.8.3 1 .5 1 .9s-.4.7-1 .7c-.7 0-1.3-.3-1.8-.7v1.3c.5.3 1.1.5 1.8.5 1.4 0 2.3-.7 2.3-1.8 0-.9-.5-1.4-1.6-1.8-.8-.3-1-.5-1-.8 0-.4.3-.6.8-.6s1.1.2 1.6.5Z"/></svg>}
    {key === "github" && <svg viewBox="0 0 24 24"><path fill="#24292F" d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.69c-2.78.61-3.37-1.18-3.37-1.18-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.9 1.53 2.35 1.09 2.92.83.09-.65.35-1.09.64-1.34-2.22-.25-4.56-1.11-4.56-4.94 0-1.09.39-1.98 1.03-2.68-.1-.25-.45-1.27.1-2.64 0 0 .84-.27 2.75 1.02A9.6 9.6 0 0 1 12 7.7a9.6 9.6 0 0 1 2.5.34c1.91-1.29 2.75-1.02 2.75-1.02.55 1.37.2 2.39.1 2.64.64.7 1.03 1.59 1.03 2.68 0 3.84-2.34 4.69-4.57 4.94.36.31.68.92.68 1.86v2.76c0 .27.18.58.69.48A10 10 0 0 0 12 2Z"/></svg>}
    {key === "teams" && <svg viewBox="0 0 24 24"><path fill="#5059C9" d="M9 5.5h7.5a2 2 0 0 1 2 2V16a4 4 0 0 1-4 4H9Z"/><path fill="#7B83EB" d="M5.5 7.5h8A1.5 1.5 0 0 1 15 9v7.5a2.5 2.5 0 0 1-2.5 2.5h-7Z"/><circle cx="17.5" cy="4.5" r="2.5" fill="#7B83EB"/><circle cx="6.5" cy="5" r="3" fill="#4B53BC"/><path fill="#fff" d="M4.2 8.8h6.3v1.5H8.2v6H6.5v-6H4.2Z"/></svg>}
  </span>;
}
