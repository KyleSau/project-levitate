// Generic single-axis XY chart (lines and/or points) with legend and hover tooltip.
import { useMemo, useState } from "react";
import { fmt } from "../api";

export interface XYSeries {
  name: string;
  color: string;
  points: { x: number; y: number; label?: string; ring?: boolean; hollow?: boolean }[];
  line?: boolean;
  dashed?: boolean;
}

export function XYChart({ series, xLabel, yLabel, width = 520, height = 260, logX = false }: {
  series: XYSeries[]; xLabel: string; yLabel: string; width?: number; height?: number; logX?: boolean;
}) {
  const padL = 52, padR = 10, padT = 26, padB = 34;
  const [hover, setHover] = useState<{ s: number; i: number } | null>(null);
  const tx = (x: number) => (logX ? Math.log10(x) : x);
  const { x0, x1, y0, y1 } = useMemo(() => {
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const s of series) for (const p of s.points) {
      if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
      x0 = Math.min(x0, tx(p.x)); x1 = Math.max(x1, tx(p.x)); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y);
    }
    if (!Number.isFinite(x0)) { x0 = 0; x1 = 1; y0 = 0; y1 = 1; }
    if (x1 - x0 < 1e-12) { x1 += 1; x0 -= 1; }
    if (y1 - y0 < 1e-12) { y1 += 1e-6 + Math.abs(y1) * 0.1; y0 -= 1e-6 + Math.abs(y0) * 0.1; }
    const py = (y1 - y0) * 0.06, px = (x1 - x0) * 0.03;
    return { x0: x0 - px, x1: x1 + px, y0: y0 - py, y1: y1 + py };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [series, logX]);
  const X = (x: number) => padL + ((tx(x) - x0) / (x1 - x0)) * (width - padL - padR);
  const Y = (y: number) => padT + (1 - (y - y0) / (y1 - y0)) * (height - padT - padB);
  const ticks = (a: number, b: number, n = 5) => Array.from({ length: n }, (_, i) => a + ((b - a) * i) / (n - 1));
  const hp = hover ? series[hover.s].points[hover.i] : null;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", maxWidth: width, height: "auto", background: "var(--panel2)", borderRadius: 4 }}
      onMouseLeave={() => setHover(null)}>
      {series.map((s, k) => (
        <g key={k} transform={`translate(${padL + k * 150} 12)`}>
          <rect width={10} height={3} y={-3} fill={s.color} />
          <text x={14} y={1} fontSize={10} fill="var(--text)">{s.name}</text>
        </g>
      ))}
      {ticks(y0, y1).map((v, i) => (
        <g key={i}>
          <line x1={padL} x2={width - padR} y1={Y(v)} y2={Y(v)} stroke="#1f2a36" />
          <text x={padL - 4} y={Y(v) + 3} fontSize={9} fill="var(--muted)" textAnchor="end">{fmt(v, 3)}</text>
        </g>
      ))}
      {ticks(x0, x1).map((v, i) => (
        <text key={i} x={padL + ((v - x0) / (x1 - x0)) * (width - padL - padR)} y={height - padB + 12} fontSize={9}
          fill="var(--muted)" textAnchor="middle">{fmt(logX ? 10 ** v : v, 3)}</text>
      ))}
      <text x={(padL + width) / 2} y={height - 6} fontSize={10} fill="var(--muted)" textAnchor="middle">{xLabel}</text>
      <text x={12} y={(padT + height - padB) / 2} fontSize={10} fill="var(--muted)" textAnchor="middle"
        transform={`rotate(-90 12 ${(padT + height - padB) / 2})`}>{yLabel}</text>
      {series.map((s, k) => {
        const pts = s.points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
        return (
          <g key={k}>
            {s.line && pts.length > 1 && (
              <path d={pts.map((p, i) => `${i ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join("")} fill="none"
                stroke={s.color} strokeWidth={2} strokeDasharray={s.dashed ? "4,3" : undefined} />
            )}
            {pts.map((p, i) => (
              <g key={i}>
                {p.ring && <circle cx={X(p.x)} cy={Y(p.y)} r={8} fill="none" stroke="#ffffff" strokeWidth={1.5} />}
                <circle cx={X(p.x)} cy={Y(p.y)} r={4.5} fill={p.hollow ? "var(--panel2)" : s.color} stroke={p.hollow ? s.color : "var(--panel2)"}
                  strokeWidth={2} />
                <circle cx={X(p.x)} cy={Y(p.y)} r={10} fill="transparent" onMouseEnter={() => setHover({ s: k, i: s.points.indexOf(p) })} />
              </g>
            ))}
          </g>
        );
      })}
      {hp && (
        <g transform={`translate(${Math.min(X(hp.x) + 10, width - 230)} ${Math.max(Y(hp.y) - 40, padT)})`} pointerEvents="none">
          <rect width={220} height={hp.label ? 46 : 32} rx={3} fill="#0b0f14" stroke="#34506b" />
          <text x={6} y={13} fontSize={10} fill="var(--text)">{series[hover!.s].name}</text>
          <text x={6} y={26} fontSize={10} fill="var(--text)">{xLabel}: {fmt(hp.x, 4)} · {yLabel}: {fmt(hp.y, 4)}</text>
          {hp.label && <text x={6} y={39} fontSize={9} fill="var(--muted)">{hp.label.slice(0, 44)}</text>}
        </g>
      )}
    </svg>
  );
}
