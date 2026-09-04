import { Disclosure, Metric, Mono, Panel, Rule, Status } from "@/components/ui";

const SWATCHES: [string, string][] = [
  ["background", "bg-bg"],
  ["surface", "bg-surface"],
  ["surface-sunk", "bg-surface-sunk"],
  ["line", "bg-line"],
  ["text", "bg-text"],
  ["muted", "bg-muted"],
  ["primary", "bg-primary"],
  ["accent", "bg-accent"],
  ["success", "bg-success"],
  ["warning", "bg-warning"],
  ["error", "bg-error"],
];

export default function Styleguide() {
  return (
    <div className="space-y-10">
      <header className="space-y-2">
        <p className="label-xs">§0 · Design system</p>
        <h1 className="font-display text-3xl">Laboratory Notebook</h1>
        <p className="max-w-2xl text-sm text-muted">
          Warm neutrals, ink typography, pine and oxide. Hairline rules instead
          of shadows, tabular numerals, editorial captions. Deliberately not the
          cool gradient palette every AI product ships with.
        </p>
      </header>

      <Rule label="Colour" />
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
        {SWATCHES.map(([name, cls]) => (
          <div key={name} className="space-y-1">
            <div className={`h-12 border border-line ${cls}`} />
            <p className="font-mono text-[10px] text-muted">{name}</p>
          </div>
        ))}
      </div>

      <Rule label="Typography" />
      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Display — Newsreader" fig="Fig. 1">
          <p className="font-display text-3xl leading-tight">
            An instrument for measuring model behaviour
          </p>
          <p className="mt-2 font-display text-sm text-muted">
            Editorial serif for headlines and prose. Carries the
            research-journal register.
          </p>
        </Panel>
        <Panel title="Technical — JetBrains Mono" fig="Fig. 2">
          <p className="font-mono text-sm tnum">
            groq / openai:gpt-oss-20b
            <br />
            pass_rate 0.9140 · latency 0.812s
            <br />
            cost $0.000204 · tokens 336/248
          </p>
          <p className="mt-2 text-sm text-muted">
            Every number, model name, score and identifier. Tabular figures so
            columns align.
          </p>
        </Panel>
      </div>

      <Rule label="Metrics" />
      <Panel fig="Fig. 3" caption="Small-caps label, mono value, plain-language caption underneath.">
        <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
          <Metric
            label="Pass rate"
            value="91.4"
            unit="%"
            sub="44/48 [87.1–94.2]"
            caption="Share of answers that passed every check."
          />
          <Metric
            label="Faithfulness"
            value="0.872"
            caption="Claims backed by the source material."
            tone="success"
          />
          <Metric
            label="Latency"
            value="812"
            unit="ms"
            caption="Average time the model took to answer."
          />
          <Metric
            label="Est. cost"
            value="$0.0002"
            sub="336/248 tok"
            caption="At the model's list price."
            tone="accent"
          />
        </div>
      </Panel>

      <Rule label="Status" />
      <div className="flex flex-wrap gap-2">
        <Status state="pass">exact</Status>
        <Status state="pass">semantic</Status>
        <Status state="fail">faithfulness</Status>
        <Status state="warn">rate-limited</Status>
        <Status state="pending">llm-rubric</Status>
      </div>

      <Rule label="Progressive disclosure" />
      <Panel
        fig="Fig. 4"
        caption="Plain sentence by default; the statistics are one click away. Both audiences served without dumbing anything down."
      >
        <div className="space-y-3 text-sm">
          <Disclosure
            plain="91% of responses passed."
            technical="95% bootstrap CI 87.1–94.2% · n=48 · 2000 resamples"
          />
          <Disclosure
            plain="Model quality decreased against the baseline."
            technical="paired t-test p=0.033 · Cohen's d −0.94 · McNemar 4↓/0↑ (p=0.125)"
          />
          <Disclosure
            plain="This suite is too small to detect changes under 5 points."
            technical="min_samples_for_5pt_mde = 225 at the observed variance"
          />
        </div>
      </Panel>

      <Rule label="Controls" />
      <div className="flex flex-wrap items-center gap-3">
        <button className="btn btn-primary">Run suite</button>
        <button className="btn btn-secondary">View example</button>
        <button className="btn btn-ghost">Cancel</button>
        <button className="btn btn-primary" disabled>
          Running…
        </button>
      </div>
      <input className="field max-w-md" placeholder="provider API key — never stored" />

      <Rule label="Inline technical tokens" />
      <p className="max-w-2xl text-sm leading-relaxed">
        The suite ran on <Mono>groq</Mono> against <Mono>openai/gpt-oss-20b</Mono>{" "}
        with a <Mono>faithfulness</Mono> assertion at threshold{" "}
        <Mono>0.8</Mono>, promoted from baseline run <Mono>6a9a6a41</Mono>.
      </p>
    </div>
  );
}
