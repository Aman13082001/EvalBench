import * as React from "react";

/* ── Rule ──────────────────────────────────────────────────────
   The signature divider: a hairline with measurement ticks.     */
export function Rule({ label }: { label?: string }) {
  if (!label) return <div className="tick-rule" role="separator" />;
  return (
    <div className="flex items-center gap-3" role="separator">
      <span className="label-xs whitespace-nowrap">{label}</span>
      <div className="tick-rule flex-1" />
    </div>
  );
}

/* ── Panel ─────────────────────────────────────────────────────
   Bordered surface with an optional editorial caption (Fig. N).  */
export function Panel({
  title,
  fig,
  caption,
  right,
  children,
  className = "",
}: {
  title?: string;
  fig?: string;
  caption?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || fig || right) && (
        <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
          <div className="flex items-baseline gap-2">
            {fig && <span className="label-xs font-mono">{fig}</span>}
            {title && (
              <h3 className="font-display text-base leading-none">{title}</h3>
            )}
          </div>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
      {caption && (
        <p className="border-t border-line px-4 py-2 text-xs text-muted">
          {caption}
        </p>
      )}
    </section>
  );
}

/* ── Metric ────────────────────────────────────────────────────
   Small-caps label, mono value, unit, optional plain caption.    */
export function Metric({
  label,
  value,
  unit,
  sub,
  caption,
  tone = "text",
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  caption?: string;
  tone?: "text" | "success" | "warning" | "error" | "accent";
}) {
  const toneClass = {
    text: "text-text",
    success: "text-success",
    warning: "text-warning",
    error: "text-error",
    accent: "text-accent",
  }[tone];

  return (
    <div className="flex flex-col gap-1">
      <span className="label-xs">{label}</span>
      <span className={`font-mono text-2xl leading-none tnum ${toneClass}`}>
        {value}
        {unit && (
          <span className="ml-1 text-xs font-normal text-muted">{unit}</span>
        )}
      </span>
      {sub && <span className="font-mono text-xs text-muted tnum">{sub}</span>}
      {caption && <span className="text-xs leading-snug text-muted">{caption}</span>}
    </div>
  );
}

/* ── Disclosure ────────────────────────────────────────────────
   Progressive disclosure: plain sentence, technical detail on
   demand. The core pattern for making this legible to both a
   researcher and a casual visitor.                               */
export function Disclosure({
  plain,
  technical,
  defaultOpen = false,
}: {
  plain: React.ReactNode;
  technical: React.ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="group" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-baseline gap-2">
        <span className="flex-1">{plain}</span>
        <span className="label-xs shrink-0 border-b border-dotted border-line-strong text-muted group-open:hidden">
          detail
        </span>
        <span className="label-xs hidden shrink-0 border-b border-dotted border-line-strong text-muted group-open:inline">
          hide
        </span>
      </summary>
      <div className="mt-1.5 border-l-2 border-accent/40 pl-3 font-mono text-xs text-muted tnum">
        {technical}
      </div>
    </details>
  );
}

/* ── Status ────────────────────────────────────────────────────
   Square status marker — never a rounded pill.                   */
export function Status({
  state,
  children,
}: {
  state: "pass" | "fail" | "pending" | "warn";
  children?: React.ReactNode;
}) {
  const map = {
    pass: ["border-success text-success", "✓"],
    fail: ["border-error text-error", "✗"],
    warn: ["border-warning text-warning", "!"],
    pending: ["border-line-strong text-muted", "·"],
  }[state];

  return (
    <span
      className={`inline-flex items-center gap-1.5 border px-1.5 py-0.5 font-mono text-[11px] ${map[0]}`}
    >
      <span aria-hidden>{map[1]}</span>
      {children}
    </span>
  );
}

/* ── Mono ──────────────────────────────────────────────────────
   Inline technical token: model names, assertion types, ids.     */
export function Mono({ children }: { children: React.ReactNode }) {
  return (
    <code className="border border-line bg-surface-sunk px-1 py-0.5 font-mono text-[0.85em] text-text">
      {children}
    </code>
  );
}
