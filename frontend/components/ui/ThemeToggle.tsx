"use client";

import { useState, useSyncExternalStore } from "react";
import clsx from "clsx";
import { MoonIcon, SunIcon, SystemThemeIcon } from "./icons";

type ThemePref = "light" | "dark" | "system";

const STORAGE_KEY = "agentabi_theme";

function applyTheme(pref: ThemePref) {
  const root = document.documentElement;
  if (pref === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", pref);
  }
}

function readStoredTheme(): ThemePref {
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // localStorage unavailable — use system theme.
  }
  return "system";
}

function subscribeMounted() {
  return () => {};
}

function getClientMounted() {
  return true;
}

function getServerMounted() {
  return false;
}

/** Light / dark / system control. Persisted in localStorage (a per-viewer
 * UI preference, not app data) and applied by setting `data-theme` on
 * <html> — the attribute globals.css's dark-mode selectors already key
 * off. "system" removes the attribute so the existing
 * prefers-color-scheme media query takes back over. */
export function ThemeToggle() {
  const mounted = useSyncExternalStore(
    subscribeMounted,
    getClientMounted,
    getServerMounted,
  );

  const [pref, setPref] = useState<ThemePref>(() => {
    if (typeof window === "undefined") {
      return "system";
    }
    return readStoredTheme();
  });

  function choose(next: ThemePref) {
    setPref(next);
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // best effort only
    }
  }

  // Avoid a hydration flash of the wrong control state before the stored
  // preference is read.
  if (!mounted) {
    return <div className="h-8 w-24" aria-hidden />;
  }

  const options: { value: ThemePref; label: string; Icon: typeof SunIcon }[] = [
    { value: "light", label: "Light theme", Icon: SunIcon },
    { value: "system", label: "Match system theme", Icon: SystemThemeIcon },
    { value: "dark", label: "Dark theme", Icon: MoonIcon },
  ];

  return (
    <div
      role="radiogroup"
      aria-label="Theme"
      className="inline-flex items-center gap-0.5 rounded-md border border-border bg-surface-sunken p-0.5"
    >
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={pref === value}
          aria-label={label}
          title={label}
          onClick={() => choose(value)}
          className={clsx(
            "flex h-7 w-7 items-center justify-center rounded transition-colors",
            pref === value
              ? "bg-surface text-ink shadow-sm ring-1 ring-border"
              : "text-ink-faint hover:text-ink-muted",
          )}
        >
          <Icon className="h-4 w-4" />
        </button>
      ))}
    </div>
  );
}

/** Inline script (rendered via next/script beforeInteractive by the root
 * layout) that applies the stored theme before first paint, so there is
 * no flash of the wrong theme. Kept tiny and defensive — storage or DOM
 * access failing here must never throw and break the whole page. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${STORAGE_KEY}");if(t==="light"||t==="dark"){document.documentElement.setAttribute("data-theme",t);}}catch(e){}})();`;
