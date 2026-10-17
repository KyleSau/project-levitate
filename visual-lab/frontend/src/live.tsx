// Live real-time session: the backend steps the RK4 plant paced to wall-clock time and streams every recorded
// frame; this hook assembles them into a growing SimResult so the same 3D scene / dashboard render it.
import { useCallback, useRef, useState } from "react";
import type { ModeConfig, SimResult } from "./api";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Msg = Record<string, any>;

export interface LiveState {
  active: boolean;
  paused: boolean;
  speed: number;
  notice: string | null;
}

export function useLive(onResult: (r: SimResult, live: boolean) => void) {
  const wsRef = useRef<WebSocket | null>(null);
  const resRef = useRef<SimResult | null>(null);
  const [state, setState] = useState<LiveState>({ active: false, paused: false, speed: 1, notice: null });

  const start = useCallback((mode: ModeConfig | undefined, gains: Record<string, unknown> | undefined) => {
    wsRef.current?.close();
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/live`);
    wsRef.current = ws;
    resRef.current = null;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "start", speed: 1, request: { mode, gains } }));
      setState({ active: true, paused: false, speed: 1, notice: null });
    };
    ws.onmessage = (ev) => {
      const m: Msg = JSON.parse(ev.data);
      if (m.type === "header") {
        const { type: _t, ...rest } = m; // eslint-disable-line @typescript-eslint/no-unused-vars
        resRef.current = { ...(rest as unknown as SimResult), trajectory: {} as SimResult["trajectory"] };
      } else if (m.type === "frames" && resRef.current) {
        const r = resRef.current;
        if (m.channels) {
          const tr = r.trajectory as unknown as Record<string, unknown[]>;
          for (const [k, v] of Object.entries(m.channels as Record<string, unknown[]>)) {
            if (!tr[k]) tr[k] = [];
            for (const x of v) tr[k].push(x);
          }
        }
        if (m.events) r.events = [...r.events, ...m.events];
        if (m.phases) r.phases = m.phases;
        r.summary = { ...r.summary, failures: r.events.filter((e) => /FAILED|DEFICIT|DEPLETED|LOSS|ABORT|DIVERGED/.test(e.kind)).map((e) => e.kind) };
        setState((s) => ({ ...s, paused: m.paused, speed: m.speed }));
        if ((r.trajectory.t?.length ?? 0) > 0) onResult({ ...r, trajectory: { ...r.trajectory } }, true);
      } else if (m.type === "notice") {
        setState((s) => ({ ...s, notice: m.message }));
      } else if (m.type === "error") {
        setState((s) => ({ ...s, active: false, notice: m.message }));
      } else if (m.type === "package") {
        onResult(m.result as SimResult, false);
        setState((s) => ({ ...s, active: false, notice: "live session ended — full recording loaded for replay" }));
      }
    };
    ws.onclose = () => setState((s) => ({ ...s, active: false }));
    ws.onerror = () => setState((s) => ({ ...s, active: false, notice: "live connection failed (is the lab API on 8100 running?)" }));
  }, [onResult]);

  const send = useCallback((m: Msg) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify(m));
  }, []);

  return { state, start, send };
}

export function LivePad({ send, state, yawDeg }: { send: (m: Msg) => void; state: LiveState; yawDeg: number }) {
  const go = (rel: [number, number, number], yaw?: number) => send({ type: "cmd", cmd: "goto", rel, yaw_deg: yaw });
  return (
    <div className="live-pad">
      <div className="live-title">LIVE · real-time RK4 stream</div>
      <div className="muted" style={{ fontSize: 10 }}>commands move the controller set-point (world axes); motion = integrated forces</div>
      <div className="pad-grid">
        <span />
        <button onClick={() => go([0.2, 0, 0])} title="+x 0.2 m">▲ +x</button>
        <span />
        <button onClick={() => go([0, 0.2, 0])} title="+y (left) 0.2 m">◀ +y</button>
        <button onClick={() => send({ type: "push", force_n: [0, 0.04, 0], duration_s: 0.1 })} title="0.04 N lateral gust for 0.1 s">gust</button>
        <button onClick={() => go([0, -0.2, 0])} title="−y (right) 0.2 m">−y ▶</button>
        <span />
        <button onClick={() => go([-0.2, 0, 0])} title="−x 0.2 m">▼ −x</button>
        <span />
      </div>
      <div className="pad-row">
        <button onClick={() => go([0, 0, 0.1])}>up 0.1</button>
        <button onClick={() => go([0, 0, -0.1])}>down 0.1</button>
        <button onClick={() => go([0, 0, 0], yawDeg + 45)}>yaw +45°</button>
        <button onClick={() => go([0, 0, 0], yawDeg - 45)}>yaw −45°</button>
      </div>
      <div className="pad-row">
        <button onClick={() => send({ type: "cmd", cmd: "land" })}>land</button>
        <button onClick={() => send({ type: "cmd", cmd: "takeoff", alt_m: 0.25 })}>take off</button>
        {state.paused ? <button onClick={() => send({ type: "resume" })}>resume</button> : <button onClick={() => send({ type: "pause" })}>pause</button>}
        <select value={state.speed} onChange={(e) => send({ type: "speed", value: parseFloat(e.target.value) })}>
          {[0.1, 0.25, 0.5, 1, 2].map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
      </div>
      <button className="primary" onClick={() => send({ type: "stop" })}>stop & keep recording</button>
      {state.notice && <div className="muted">{state.notice}</div>}
    </div>
  );
}
