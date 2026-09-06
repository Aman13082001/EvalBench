import type { Metadata } from "next";
import { JetBrains_Mono, Newsreader } from "next/font/google";
import Link from "next/link";
import { AuthProvider } from "@/components/AuthProvider";
import Nav from "@/components/Nav";
import "./globals.css";

const display = Newsreader({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "EvalBench — an instrument for measuring LLM behaviour",
  description:
    "Run evaluation suites against any model. Composable assertions, RAG faithfulness, cost tracking, and statistical regression detection.",
};


export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${display.variable} ${mono.variable}`}>
      <body className="min-h-screen font-display antialiased">
        <AuthProvider>
        <header className="border-b border-line">
          <div className="mx-auto flex max-w-page items-center justify-between gap-4 px-5 py-3">
            <Link href="/" className="flex items-baseline gap-2">
              <span className="font-display text-lg font-semibold tracking-tight">
                EvalBench
              </span>
              <span className="label-xs hidden sm:inline">
                instrument for LLM measurement
              </span>
            </Link>
            <Nav />
          </div>
        </header>

        <main className="mx-auto max-w-page px-5 py-8">{children}</main>

        <footer className="mt-16 border-t border-line">
          <div className="mx-auto flex max-w-page flex-wrap items-center justify-between gap-2 px-5 py-6 font-mono text-[11px] text-muted">
            <span>EvalBench · open source · MIT</span>
            <a
              href="https://github.com/Aman13082001/EvalBench"
              className="hover:text-text"
            >
              github.com/Aman13082001/EvalBench
            </a>
          </div>
        </footer>
        </AuthProvider>
      </body>
    </html>
  );
}
