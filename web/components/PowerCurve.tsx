type Point = { n: number; power: number };

/** Empirical power curve. Drawn from the study data with theme tokens so
 *  it reads correctly in both light and dark, unlike a baked image. */
export default function PowerCurve({
  curve,
  target = 0.8,
  nAt80,
}: {
  curve: Point[];
  target?: number;
  nAt80?: number | null;
}) {
  const W = 720;
  const H = 320;
  const L = 52;
  const R = 16;
  const T = 16;
  const B = 40;
  const pw = W - L - R;
  const ph = H - T - B;

  const xs = curve.map((c) => c.n);
  const xmin = Math.min(...xs);
  const xmax = Math.max(...xs);

  const px = (n: number) => L + (pw * (n - xmin)) / (xmax - xmin);
  const py = (p: number) => T + ph * (1 - p);

  const pts = curve.map((c) => `${px(c.n)},${py(c.power)}`).join(" ");
  const area =
    `${L},${py(0)} ` + pts + ` ${px(xmax)},${py(0)}`;

  const labelled = [4, 10, 20, 30, 60, 100];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      role="img"
      aria-label={`Statistical power rises from 1% at 4 tests to 99% at 100 tests, crossing 80% around ${nAt80} tests.`}
    >
      {/* horizontal gridlines */}
      {[0, 0.25, 0.5, 0.75, 1].map((v) => (
        <g key={v}>
          <line
            x1={L}
            y1={py(v)}
            x2={W - R}
            y2={py(v)}
            className="stroke-line"
            strokeWidth={1}
          />
          <text
            x={L - 8}
            y={py(v) + 4}
            textAnchor="end"
            className="fill-muted font-mono"
            fontSize={11}
          >
            {Math.round(v * 100)}%
          </text>
        </g>
      ))}

      {/* 80% power target */}
      <line
        x1={L}
        y1={py(target)}
        x2={W - R}
        y2={py(target)}
        className="stroke-accent"
        strokeWidth={1.5}
        strokeDasharray="5 4"
      />
      <text
        x={W - R}
        y={py(target) - 7}
        textAnchor="end"
        className="fill-accent font-mono"
        fontSize={11}
      >
        80% power — the conventional bar
      </text>

      {/* where the curve crosses it */}
      {nAt80 && (
        <>
          <line
            x1={px(nAt80)}
            y1={T}
            x2={px(nAt80)}
            y2={H - B}
            className="stroke-accent"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
          <text
            x={px(nAt80) + 6}
            y={T + 12}
            className="fill-accent font-mono"
            fontSize={11}
          >
            n≈{nAt80}
          </text>
        </>
      )}

      <polygon points={area} className="fill-primary" opacity={0.08} />
      <polyline
        points={pts}
        fill="none"
        className="stroke-primary"
        strokeWidth={2}
      />
      {curve.map((c) => (
        <circle
          key={c.n}
          cx={px(c.n)}
          cy={py(c.power)}
          r={3}
          className="fill-primary"
        />
      ))}

      {/* x axis */}
      {curve
        .filter((c) => labelled.includes(c.n))
        .map((c) => (
          <text
            key={c.n}
            x={px(c.n)}
            y={H - B + 18}
            textAnchor="middle"
            className="fill-muted font-mono"
            fontSize={11}
          >
            {c.n}
          </text>
        ))}
      <text
        x={L}
        y={H - 6}
        className="fill-muted font-mono"
        fontSize={11}
      >
        tests in the suite (n)
      </text>
    </svg>
  );
}
