/* Every answer, every judge. One column per frozen answer, sorted by its
   average score; a dot per judge at that judge's mean over repeats, a
   bar for the range across repeats. Where the columns are unanimous the
   judge is invisible; where the colours split, it is the judge you are
   looking at. Drawn from the study data with theme tokens, like
   PowerCurve, so it reads in both light and dark. */

type JudgeCell = { mean: number; min: number; max: number };
type Answer = { set: string; test: string; category: string; judges: JudgeCell[] };

/* Literal class names: Tailwind only ships what it can read in source. */
const SERIES = [
  { stroke: "stroke-accent", fill: "fill-accent", swatch: "bg-accent" },
  { stroke: "stroke-success", fill: "fill-success", swatch: "bg-success" },
  { stroke: "stroke-warning", fill: "fill-warning", swatch: "bg-warning" },
];

export default function JudgeSpread({
  spread,
  judges,
  cutoff = 0.6,
}: {
  spread: Answer[];
  judges: string[];
  cutoff?: number;
}) {
  const W = 900;
  const H = 300;
  const L = 44;
  const R = 12;
  const T = 14;
  const B = 28;
  const pw = W - L - R;
  const ph = H - T - B;
  const n = spread.length;
  const step = pw / n;
  const py = (s: number) => T + ph * (1 - s);

  const short = (j: string) => j.split("/").pop();

  return (
    <div className="space-y-3">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        role="img"
        aria-label={`${n} answers scored by ${judges.length} judges; the judges agree on the clearly good and clearly bad answers and split on the ones in between.`}
      >
        {/* weak model's answers, as a faint band */}
        {spread.map((a, i) =>
          a.set === "weak" ? (
            <rect
              key={`w${i}`}
              x={L + step * i}
              y={T}
              width={step}
              height={ph}
              className="fill-line"
              opacity={0.35}
            />
          ) : null
        )}

        {/* gridlines */}
        {[0.2, 0.4, 0.6, 0.8, 1].map((v) => (
          <g key={v}>
            <line x1={L} y1={py(v)} x2={W - R} y2={py(v)} className="stroke-line" strokeWidth={1} />
            <text x={L - 8} y={py(v) + 4} textAnchor="end" className="fill-muted font-mono" fontSize={11}>
              {v.toFixed(1)}
            </text>
          </g>
        ))}

        {/* the pass line */}
        <line
          x1={L}
          y1={py(cutoff)}
          x2={W - R}
          y2={py(cutoff)}
          className="stroke-error"
          strokeWidth={1.25}
          strokeDasharray="5 4"
        />
        <text x={W - R} y={py(cutoff) - 6} textAnchor="end" className="fill-error font-mono" fontSize={11}>
          pass line
        </text>

        {/* one column per answer, one series per judge */}
        {spread.map((a, i) => {
          const cx = L + step * (i + 0.5);
          return a.judges.map((j, k) => {
            const dx = (k - (judges.length - 1) / 2) * step * 0.28;
            const tone = SERIES[k % SERIES.length];
            return (
              <g key={`${i}-${k}`}>
                <line
                  x1={cx + dx}
                  x2={cx + dx}
                  y1={py(j.max)}
                  y2={py(j.min)}
                  className={tone.stroke}
                  strokeWidth={1.5}
                  opacity={0.55}
                />
                <circle cx={cx + dx} cy={py(j.mean)} r={2.4} className={tone.fill} />
              </g>
            );
          });
        })}

        <text x={L} y={H - 8} className="fill-muted font-mono" fontSize={11}>
          ← lower-scoring answers
        </text>
        <text x={W - R} y={H - 8} textAnchor="end" className="fill-muted font-mono" fontSize={11}>
          higher-scoring answers →
        </text>
      </svg>

      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 font-mono text-[11px] text-muted">
        {judges.map((j, k) => (
          <span key={j} className="inline-flex items-center gap-1.5">
            <span className={`inline-block h-2.5 w-2.5 rounded-sm ${SERIES[k % SERIES.length].swatch}`} />
            {short(j)}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm border border-line bg-line/40" />
          weak model&rsquo;s answer
        </span>
      </div>
    </div>
  );
}
