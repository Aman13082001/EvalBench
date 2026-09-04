import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      colors: {
        ink: "#0b1220",
        panel: "#111a2e",
        line: "#22304d",
        accent: "#5b9dff",
        good: "#3fb950",
        bad: "#f85149",
        warn: "#d29922",
      },
    },
  },
  plugins: [],
};

export default config;
