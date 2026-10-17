import { useEffect, useRef } from "react";

// Renders solver field data (nested arrays, null = outside domain) without resampling or smoothing.
export default function Heatmap({ values, xs, ys, log = false, label, unit }: {
  values: (number | null)[][]; xs: number[]; ys: number[]; log?: boolean; label: string; unit: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const flat = values.flat().filter((v): v is number => v !== null && Number.isFinite(v) && (!log || v > 0));
  const tr = (v: number) => (log ? Math.log10(v) : v);
  const hi = flat.length ? Math.max(...flat.map(tr)) : 1;
  // log maps show the top 4 decades; values below are drawn at the floor colour (not hidden)
  const lo = flat.length ? Math.max(Math.min(...flat.map(tr)), log ? hi - 4 : -Infinity) : 0;
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const nx = values.length, ny = values[0]?.length ?? 0;
    c.width = ny; c.height = nx;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(ny, nx);
    for (let i = 0; i < nx; i++) {
      for (let j = 0; j < ny; j++) {
        const v = values[i][j];
        const k = ((nx - 1 - i) * ny + j) * 4; // x (height above collector) upward
        if (v === null || !Number.isFinite(v) || (log && v <= 0)) { img.data[k + 3] = 0; continue; }
        const t = Math.max(0, Math.min(1, (tr(v) - lo) / (hi - lo || 1)));
        // perceptual-ish dark->cyan->white ramp
        img.data[k] = 255 * Math.min(1, Math.max(0, 2.2 * t - 1.1));
        img.data[k + 1] = 255 * Math.min(1, 1.25 * t);
        img.data[k + 2] = 255 * Math.min(1, 0.35 + 0.9 * t);
        img.data[k + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [values, lo, hi]);
  return (
    <div>
      <div className="row"><span className="muted">{label}</span>
        <span className="mono muted">{log ? `10^${lo.toFixed(1)} … 10^${hi.toFixed(1)}` : `${lo.toExponential(2)} … ${hi.toExponential(2)}`} {unit}</span></div>
      <canvas ref={ref} style={{ width: "100%", imageRendering: "pixelated", background: "#05080e", borderRadius: 6 }} />
      <div className="row note"><span>y = {(ys[0] * 1000).toFixed(0)} mm</span><span>lateral</span><span>{(ys[ys.length - 1] * 1000).toFixed(0)} mm</span></div>
      <div className="note">vertical: height above collector 0 → {(xs[xs.length - 1] * 1000).toFixed(0)} mm (wire at top third)</div>
    </div>
  );
}
