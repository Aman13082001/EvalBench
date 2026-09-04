import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EvalBench Playground",
  description:
    "Run an LLM evaluation suite in your browser — assertions, cost, and regression stats.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen font-mono antialiased">
        <header className="border-b border-line">
          <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
            <a href="/" className="text-lg font-bold">
              Eval<span className="text-accent">Bench</span>
              <span className="ml-2 text-xs text-slate-400">playground</span>
            </a>
            <a
              href="https://github.com/Aman13082001/EvalBench"
              className="text-sm text-slate-400 hover:text-slate-200"
            >
              GitHub
            </a>
          </div>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
