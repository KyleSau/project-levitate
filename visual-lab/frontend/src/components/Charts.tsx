// Small-multiple time-series charts drawn straight from the recorded trajectory channels.
import { useMemo } from "react";

export interface Series {
  name: string;
  color: string;
  data: number[];
  dashed?: boolean;
}

export function MiniChart({ title, unit, t, series, idx, onSeek, height = 92 }: {
  title: string; unit: string; t: number[]; series: Series[]; idx: number; onSeek: (i: number) => void; height?: number;
}) {
  const W = 300, H = height, padL = 38, padB = 14, padT = 14;
  const { paths, lo, hi } = useMemo(() => {
    let lo = Infinity, hi = -Infinity;
    for (const s of series) for (const v of s.data) if (Number.isFinite(v)) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
    if (hi - lo < 1e-12) { hi += 1e-6 + Math.abs(hi) * 0.05; lo -= 1e-6 + Math.abs(lo) * 0.05; }
    const pad = (hi - lo) * 0.08;
    lo -= pad; hi += pad;
    const T = t[t.length - 1] || 1;
    const step = Math.max(1, Math.floor(t.length / 600));
    const paths = series.map((s) => {
      let d = "";
      for (let i = 0; i < t.length; i += step) {
        const x = padL + (t[i] / T) * (W - padL - 4);
        const y = padT + (1 - (s.data[i] - lo) / (hi - lo)) * (H - padT - padB);
        d += (i === 0 ? "M" : "L") + x.toFixed(1) + "," + y.toFixed(1);
      }
      return d;
    });
    return { paths, lo, hi };
  }, [t, series, W, H]);
  const T = t[t.length - 1] || 1;
  const cx = padL + (t[idx] / T) * (W - padL - 4);
  const zeroY = padT + (1 - (0 - lo) / (hi - lo)) * (H - padT - padB);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" onClick={(e) => {
        const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
        const time = ((e.clientX - r.left) / r.width * W - padL) / (W - padL - 4) * T;
        let i = 0;
        while (i < t.length - 1 && t[i + 1] <= time) i++;
        onSeek(i);
      }}>
        <text x={4} y={10} className="chart-title">{title} [{unit}]</text>
        <text x={padL - 3} y={padT + 6} className="chart-tick" textAnchor="end">{fmtTick(hi)}</text>
        <text x={padL - 3} y={H - padB} className="chart-tick" textAnchor="end">{fmtTick(lo)}</text>
        {lo < 0 && hi > 0 && <line x1={padL} x2={W} y1={zeroY} y2={zeroY} stroke="#2c3946" strokeDasharray="2,2" />}
        {paths.map((d, i) => <path key={i} d={d} fill="none" stroke={series[i].color} strokeWidth={1.2}
          strokeDasharray={series[i].dashed ? "3,2" : undefined} vectorEffect="non-scaling-stroke" />)}
        <line x1={cx} x2={cx} y1={padT - 2} y2={H - padB} stroke="#ffffff" strokeOpacity={0.6} />
        {series.map((s, i) => (
          <text key={i} x={W - 4} y={10 + 0 * i} dx={-i * 70} className="chart-legend" textAnchor="end" fill={s.color}>
            {s.name}: {fmtTick(s.data[idx])}
          </text>
        ))}
      </svg>
    </div>
  );
}

function fmtTick(v: number | undefined): string {
  if (v === undefined || !Number.isFinite(v)) return "—";
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e4)) return v.toExponential(1);
  return v.toFixed(a < 1 ? 3 : a < 10 ? 2 : 1);
}
