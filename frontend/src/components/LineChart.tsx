type Series = { name: string; color: string; ys: number[] };

export default function LineChart({ xs, series, height = 140, xLabel, yLabel, cursor }: {
  xs: number[]; series: Series[]; height?: number; xLabel?: string; yLabel?: string; cursor?: number;
}) {
  const W = 320, H = height, pad = { l: 40, r: 8, t: 8, b: 22 };
  const all = series.flatMap((s) => s.ys).filter(Number.isFinite);
  if (!xs.length || !all.length) return <div className="note">no data</div>;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi - lo < 1e-12) { hi += 1; lo -= 1; }
  const x0 = xs[0], x1 = xs[xs.length - 1] || 1;
  const sx = (x: number) => pad.l + ((x - x0) / (x1 - x0 || 1)) * (W - pad.l - pad.r);
  const sy = (y: number) => H - pad.b - ((y - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const ticks = [lo, (lo + hi) / 2, hi];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" style={{ display: "block", maxHeight: H * 1.6 }}>
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={pad.l} x2={W - pad.r} y1={sy(t)} y2={sy(t)} stroke="#1e2b40" />
          <text x={pad.l - 4} y={sy(t) + 3} fontSize="9" fill="#7d8da6" textAnchor="end">{Math.abs(t) < 0.01 && t !== 0 ? t.toExponential(1) : t.toFixed(2)}</text>
        </g>
      ))}
      {series.map((s) => (
        <polyline key={s.name} fill="none" stroke={s.color} strokeWidth="1.5"
          points={xs.map((x, i) => (Number.isFinite(s.ys[i]) ? `${sx(x)},${sy(s.ys[i])}` : "")).join(" ")} />
      ))}
      {cursor !== undefined && <line x1={sx(cursor)} x2={sx(cursor)} y1={pad.t} y2={H - pad.b} stroke="#38d6ff" strokeDasharray="3 3" />}
      <text x={W - pad.r} y={H - 6} fontSize="9" fill="#7d8da6" textAnchor="end">{xLabel}</text>
      <text x={4} y={10} fontSize="9" fill="#7d8da6">{yLabel}</text>
      {series.length > 1 && series.map((s, i) => (
        <text key={s.name} x={pad.l + 6 + i * 70} y={pad.t + 10} fontSize="9" fill={s.color}>{s.name}</text>
      ))}
    </svg>
  );
}
