"use client";

import { useEffect, useState } from "react";

type Mode = "light" | "dark" | "system";

export default function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("system");

  useEffect(() => {
    const saved = (localStorage.getItem("eb-theme") as Mode) || "system";
    setMode(saved);
  }, []);

  useEffect(() => {
    const root = document.documentElement;
    if (mode === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", mode);
    try {
      localStorage.setItem("eb-theme", mode);
    } catch {
      /* private mode */
    }
  }, [mode]);

  const next: Record<Mode, Mode> = {
    system: "light",
    light: "dark",
    dark: "system",
  };

  return (
    <button
      className="btn btn-ghost px-2 py-1 font-mono text-[11px]"
      onClick={() => setMode(next[mode])}
      aria-label={`Theme: ${mode}. Click to change.`}
      title={`Theme: ${mode}`}
    >
      {mode}
    </button>
  );
}
