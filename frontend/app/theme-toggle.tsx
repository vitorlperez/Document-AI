"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

const options = [
  { value: "light", label: "Tema claro", short: "Claro", icon: Sun },
  { value: "dark", label: "Tema escuro", short: "Escuro", icon: Moon },
  { value: "system", label: "Seguir o sistema", short: "Sistema", icon: Monitor },
] as const;

const subscribe = () => () => undefined;

/** `showLabels` prints the option name next to the icon (mobile drawer, where there is room and touch needs a clearer state). */
export function ThemeToggle({ className = "", showLabels = false }: { className?: string; showLabels?: boolean }) {
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const current = mounted ? (theme ?? "system") : "system";
  return <div role="radiogroup" aria-label="Aparência" className={`theme-toggle ${className}`.trim()}>
    {options.map(({ value, label, short, icon: Icon }) => <button key={value} type="button" role="radio" aria-checked={current === value} aria-label={label} title={label} onClick={() => setTheme(value)} className="theme-toggle-option mo-interactive"><Icon size={16} aria-hidden="true" />{showLabels && <span>{short}</span>}</button>)}
  </div>;
}
