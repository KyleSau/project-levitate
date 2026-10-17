// 2-D preview of a real solver field with a colour bar; hover shows the exact grid value.
import { useEffect, useRef, useState } from "react";
import { fmt } from "../api";
import type { FieldOverlayData } from "./FieldOverlay";
import { colormap, fieldRange, isDiverging } from "./FieldOverlay";

export function Heatmap({ field, width = 520 }: { field: FieldOverlayData; width?: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const nu = field.u.length, nv = field.v.length;
  const spanU = field.u[nu - 1] - field.u[0], spanV = field.v[nv - 1] - field.v[0];
  const height = Math.round(width * Math.min(1.2, Math.max(0.3, spanV / spanU)));
  const [lo, hi] = fieldRange(field);
  const div = isDiverging(field);
  const [hover, setHover] = useState<{ i: number; j: number } | null>(null);
  useEffect(() => {
    const c = ref.current;
    if (!c) return;
    const ctx = c.getContext("2d")!;
    const img = ctx.createImageData(nu, nv);
    for (let j = 0; j < nv; j++) for (let i = 0; i < nu; i++) {
      const v = field.values[j][i];
      const o = 4 * ((nv - 1 - j) * nu + i); // v increases upward
      if (v === null || !Number.isFinite(v)) { img.data[o] = 30; img.data[o + 1] = 30; img.data[o + 2] = 30; img.data[o + 3] = 255; continue; }
      const [r, g, b] = colormap((v - lo) / (hi - lo || 1), div);
      img.data[o] = r; img.data[o + 1] = g; img.data[o + 2] = b; img.data[o + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [field, lo, hi, div, nu, nv]);
  const val = hover ? field.values[hover.j][hover.i] : null;
  return (
    <div>
      <div style={{ position: "relative", width: "100%", maxWidth: width, aspectRatio: `${width} / ${height}` }}>
        <canvas ref={ref} width={nu} height={nv} style={{ width: "100%", height: "100%", imageRendering: "auto", borderRadius: 3 }}
          onMouseMove={(e) => {
            const r = e.currentTarget.getBoundingClientRect();
            const i = Math.min(nu - 1, Math.max(0, Math.round(((e.clientX - r.left) / r.width) * (nu - 1))));
            const j = Math.min(nv - 1, Math.max(0, Math.round((1 - (e.clientY - r.top) / r.height) * (nv - 1))));
            setHover({ i, j });
          }} onMouseLeave={() => setHover(null)} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4, fontSize: 11 }}>
        <span>{fmt(lo, 3)}</span>
        <div style={{ width: 200, height: 8, borderRadius: 2,
          background: `linear-gradient(90deg, ${[0, 0.25, 0.5, 0.75, 1].map((t) => `rgb(${colormap(t, div).map(Math.round).join(",")})`).join(",")})` }} />
        <span>{fmt(hi, 3)} {field.unit}</span>
        <span className="muted">{div ? "diverging (0 = grey)" : "sequential"} · grey = outside fluid domain / no data</span>
      </div>
      <div className="muted" style={{ fontSize: 11 }}>
        {hover ? `u = ${(field.u[hover.i] * 1000).toFixed(2)} mm, v = ${(field.v[hover.j] * 1000).toFixed(2)} mm: ${field.quantity} = ${val === null ? "— (body/outside)" : fmt(val, 5)} ${field.unit}`
          : `${nu} × ${nv} grid, extent ${(spanU * 1000).toFixed(1)} × ${(spanV * 1000).toFixed(1)} mm — hover for values`}
      </div>
    </div>
  );
}
