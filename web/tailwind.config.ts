import type { Config } from "tailwindcss";

/** Tokens live as CSS custom properties in app/globals.css so light/dark
 *  swaps without a class rewrite. Alpha still works via <alpha-value>. */
const c = (v: string) => `rgb(var(${v}) / <alpha-value>)`;

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: c("--bg"),
        surface: c("--surface"),
        "surface-sunk": c("--surface-sunk"),
        line: c("--line"),
        "line-strong": c("--line-strong"),
        text: c("--text"),
        muted: c("--muted"),
        primary: c("--primary"),
        "primary-soft": c("--primary-soft"),
        accent: c("--accent"),
        "accent-soft": c("--accent-soft"),
        success: c("--success"),
        warning: c("--warning"),
        error: c("--error"),
      },
      fontFamily: {
        display: ["var(--font-display)", "Georgia", "serif"],
        mono: ["var(--font-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: {
        DEFAULT: "2px",
      },
      maxWidth: {
        page: "72rem",
      },
    },
  },
  plugins: [],
};

export default config;
