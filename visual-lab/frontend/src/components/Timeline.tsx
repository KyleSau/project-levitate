import type { Phase, SimEvent } from "../api";

const SEG_COLORS: Record<string, string> = {
  A: "#4fa3ff", B: "#35d0ba", C: "#9be15d", D: "#f5a524", E: "#d36cff", F: "#ff7a59", G: "#4fa3ff", X: "#ff3b5c",
};

export function Timeline(props: {
  t: number[]; idx: number; playing: boolean; speed: number; phases: Phase[]; phaseIdx: number[]; events: SimEvent[];
  onSeek: (i: number) => void; onPlay: () => void; onPause: () => void; onRestart: () => void; onStep: (d: number) => void;
  onSpeed: (s: number) => void;
}) {
  const { t, idx, phases, phaseIdx } = props;
  const T = t[t.length - 1] || 1;
  // phase spans from the recorded phase index channel
  const spans: { start: number; end: number; ph: Phase }[] = [];
  let s0 = 0;
  for (let i = 1; i <= phaseIdx.length; i++) {
    if (i === phaseIdx.length || phaseIdx[i] !== phaseIdx[s0]) {
      const ph = phases[phaseIdx[s0]];
      if (ph) spans.push({ start: t[s0], end: t[Math.min(i, t.length - 1)], ph });
      s0 = i;
    }
  }
  const cur = phases[phaseIdx[idx]];
  return (
    <div className="timeline">
      <div className="tl-buttons">
        <button onClick={props.onRestart} title="restart">⏮</button>
        <button onClick={() => props.onStep(-1)} title="previous frame">◀|</button>
        {props.playing ? <button onClick={props.onPause} title="pause">⏸</button> : <button onClick={props.onPlay} title="play">▶</button>}
        <button onClick={() => props.onStep(1)} title="next frame">|▶</button>
        <select value={props.speed} onChange={(e) => props.onSpeed(parseFloat(e.target.value))} title="playback speed">
          {[0.05, 0.1, 0.25, 0.5, 1, 2, 4].map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
        <span className="tl-time">t = {t[idx]?.toFixed(3)} s / {T.toFixed(2)} s · frame {idx}/{t.length - 1}</span>
        <span className="tl-phase" style={{ color: SEG_COLORS[cur?.segment] ?? "#ccc" }}>{cur?.label ?? ""}</span>
      </div>
      <div className="tl-track" onMouseDown={(e) => {
        const el = e.currentTarget;
        const seek = (cx: number) => {
          const r = el.getBoundingClientRect();
          const time = Math.min(1, Math.max(0, (cx - r.left) / r.width)) * T;
          let lo = 0;
          while (lo < t.length - 1 && t[lo + 1] <= time) lo++;
          props.onSeek(lo);
        };
        seek(e.clientX);
        const mv = (ev: MouseEvent) => seek(ev.clientX);
        const up = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", up); };
        window.addEventListener("mousemove", mv);
        window.addEventListener("mouseup", up);
      }}>
        {spans.map((s, i) => (
          <div key={i} className="tl-span" title={s.ph.label}
            style={{ left: `${(s.start / T) * 100}%`, width: `${((s.end - s.start) / T) * 100}%`, background: SEG_COLORS[s.ph.segment] ?? "#555" }}>
            {s.end - s.start > T * 0.04 ? s.ph.segment : ""}
          </div>
        ))}
        {props.events.map((e, i) => (
          <div key={i} className={`tl-event ${/FAIL|DEFICIT|DEPLETED|LOSS|ABORT|DIVERGED/.test(e.kind) ? "bad" : ""}`}
            style={{ left: `${(e.t / T) * 100}%` }} title={`${e.t.toFixed(3)} s ${e.kind}: ${e.message}`} />
        ))}
        <div className="tl-cursor" style={{ left: `${(t[idx] / T) * 100}%` }} />
      </div>
    </div>
  );
}
