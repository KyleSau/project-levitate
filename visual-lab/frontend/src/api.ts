// Types mirror visual-lab/backend/vlab/sim.py output. Every displayed number comes from these arrays.
export type V3 = [number, number, number];

export interface Trajectory {
  t: number[];
  pos: V3[];
  vel: V3[];
  acc: V3[];
  quat: [number, number, number, number][];
  euler_deg: V3[];
  omega: V3[];
  omega_dot: V3[];
  f_act: number[][];
  f_cmd: number[][];
  F_grav: V3[];
  F_act: V3[];
  F_drag: V3[];
  F_contact: V3[];
  F_ext: V3[];
  F_net: V3[];
  tau_act: V3[];
  tau_drag: V3[];
  tau_contact: V3[];
  tau_net: V3[];
  contact_n: number[];
  contact_pts: number[];
  ref_pos: V3[];
  ref_vel: V3[];
  ref_yaw_deg: number[];
  err_pos: V3[];
  power_w: number[];
  energy_j: number[];
  temp_c: number[][];
  ke_j: number[];
  pe_j: number[];
  L_world: V3[];
  phase: number[];
  tilt_cmd_deg: number[];
  saturated: boolean[];
  armed: boolean[];
  kge: number[][];
}

export interface Phase {
  index: number;
  segment: string;
  kind: string;
  label: string;
}

export interface SimEvent {
  t: number;
  kind: string;
  message: string;
}

export interface Metric {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  basis: "calculated" | "estimate" | "hypothetical";
  unbounded: boolean;
  note: string;
}

export interface Constraint {
  key: string;
  label: string;
  passed: boolean;
  value: number | null;
  limit: number | null;
  unit: string;
  toggle: string;
  hard: boolean;
  message: string;
}

export interface Feasibility {
  verdict: string;
  metrics: Metric[];
  constraints: Constraint[];
  failing: string[];
  marginal: string[];
  limiting_toggles: string[];
  hover_forces_n: number[];
  power_model: string;
  evidence: string;
  labels: string[];
}

export interface ActuatorInfo {
  name: string;
  pos_m: V3;
  axis: V3;
  max_force_n: number | null;
  min_force_n: number | null;
  spin: number;
  torque_ratio_m: number;
  time_constant_s: number;
  mechanism: string;
  radius_m: number;
}

export interface ComponentInfo {
  name: string;
  mass_kg: number;
  pos_m: V3;
  size_m: V3;
  group: string;
  cg_trim: boolean;
}

export interface VehicleInfo {
  name: string;
  length_m: number;
  width_m: number;
  height_m: number;
  mass_kg: number;
  cg_m: V3;
  inertia_kgm2: number[][];
  principal_moments_kgm2: V3;
  inertia_valid: boolean;
  components: ComponentInfo[];
  actuators: ActuatorInfo[];
  added_mass_kg: V3;
  hypothetical: boolean;
}

export interface SimResult {
  name: string;
  summary: Record<string, unknown>;
  events: SimEvent[];
  phases: Phase[];
  feasibility: Feasibility;
  vehicle: VehicleInfo;
  labels: string[];
  power_model: string;
  air: { rho: number; mu: number; source: string };
  settings: Record<string, unknown>;
  gains: Record<string, unknown>;
  mode_config: ModeConfig;
  integrator: string;
  trajectory: Trajectory;
}

// ModeConfig is kept loosely typed: the parameter editor edits it generically.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ModeConfig = Record<string, any>;

export async function getJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try {
      const j = await r.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail ?? j);
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

export const postJSON = <T,>(url: string, body: unknown) =>
  getJSON<T>(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export function fmt(v: number | null | undefined, digits = 4): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (!Number.isFinite(v)) return v > 0 ? "∞" : "-∞";
  const a = Math.abs(v);
  if (a !== 0 && (a < 1e-3 || a >= 1e5)) return v.toExponential(digits - 1);
  return v.toFixed(Math.max(0, digits - Math.max(0, Math.floor(Math.log10(a || 1)) + 1)));
}

export function frameAt(t: number[], time: number): number {
  let lo = 0;
  let hi = t.length - 1;
  if (time <= t[0]) return 0;
  if (time >= t[hi]) return hi;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (t[mid] <= time) lo = mid;
    else hi = mid;
  }
  return lo;
}
