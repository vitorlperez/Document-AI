"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

const options = [
  { value: "light", label: "Tema claro", icon: Sun },
  { value: "dark", label: "Tema escuro", icon: Moon },
  { value: "system", label: "Seguir o sistema", icon: Monitor },
] as const;

const subscribe = () => () => undefined;

export function ThemeToggle({ className = "" }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const current = mounted ? (theme ?? "system") : "system";
  return <div role="radiogroup" aria-label="Aparência" className={`theme-toggle ${className}`.trim()}>
    {options.map(({ value, label, icon: Icon }) => <button key={value} type="button" role="radio" aria-checked={current === value} aria-label={label} title={label} onClick={() => setTheme(value)} className="theme-toggle-option"><Icon size={16} aria-hidden="true" /></button>)}
  </div>;
}
