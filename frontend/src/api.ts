// Thin typed client for the research harness API (docs/API_CONTRACT.md).
/* eslint-disable @typescript-eslint/no-explicit-any */

export type Design = {
  name: string; length_mm: number; width_mm: number; board_height_mm: number; skin_mm: number; wall_mm: number;
  deck_material: string; propulsion: "ducted_rotor" | "open_rotor"; layout: "staggered" | "grid" | "inline";
  n_rotors: number; rotor_diameter_mm: number; lateral_offset_mm: number; tip_gap_mm: number; motor: string;
  battery: string; extra_payload_g: number; hover_altitude_m: number;
};

export type Constraint = { key: string; passed: boolean; value: number | null; limit: number | null; message: string; hard: boolean };

export type Scenario = {
  scenario: string; mass_g: number; weight_n: number; hover_thrust_per_rotor_n: number[]; max_thrust_per_rotor_n: number;
  thrust_to_weight: number; hover_shaft_power_w: number; hover_electrical_power_w: number; hover_current_a: number;
  hover_c_rate: number; battery_heat_w: number; endurance_s: number; power_loading_g_per_w: number;
  disk_loading_n_m2: number; tip_mach: number; rpm_hover: number; authority_rad_s2: Record<string, number>;
  bending_freq_hz: number; ground_effect_thrust_ratio: number; constraints: Constraint[]; feasible: boolean;
};

export type Geometry = {
  length_m: number; width_m: number; height_m: number; skin_m: number; wall_m: number; ducted: boolean;
  rotors: { pos: [number, number, number]; spin: number; r_rotor: number; r_in: number; r_out: number }[];
  battery: { size: [number, number, number]; pos: [number, number, number] };
  avionics: { size: [number, number, number]; pos: [number, number, number] };
  cg: [number, number, number];
};

export type SimResult = {
  t: number[]; pos: number[][]; quat: number[][]; vel: number[][]; omega: number[][]; thrusts: number[][];
  ref: number[][]; metrics: Record<string, number | boolean | string>;
};

export type Report = {
  design: Design; evidence: string; evidence_by_part: Record<string, string>; layout: any;
  mass_budget: { items: { name: string; group: string; mass_g: number; cost_usd: number; source: string }[];
    total_g: number; cg_m: number[]; inertia_kgm2: number[][]; by_group_g: Record<string, number>; cost_usd: number };
  scenarios: Record<"pessimistic" | "nominal" | "optimistic", Scenario>;
  verdict: string; verdict_reason: string; cost_usd: number; geometry: Geometry; sim: SimResult | null;
  experiment_id?: number;
};

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export const api = {
  health: () => j<any>("/api/health"),
  catalog: () => j<any>("/api/catalog"),
  solvers: () => j<any[]>("/api/solvers"),
  screening: () => j<any[]>("/api/screening"),
  evaluateRotor: (design: Design, run_sim: boolean, save = true) =>
    j<Report>("/api/evaluate/rotor", { method: "POST", body: JSON.stringify({ design, run_sim, save }) }),
  evaluateEad: (design: any) => j<any>("/api/evaluate/ead", { method: "POST", body: JSON.stringify({ design }) }),
  solveWire: (body: any) => j<any>("/api/solve/ehd_wire", { method: "POST", body: JSON.stringify(body) }),
  sensitivity: (design: Design) => j<any[]>("/api/sensitivity/rotor", { method: "POST", body: JSON.stringify(design) }),
  sweep: (design: Design, param: string, values: any[]) =>
    j<any[]>("/api/sweep/rotor", { method: "POST", body: JSON.stringify({ design, param, values }) }),
  experiments: (q = "") => j<any[]>(`/api/experiments${q}`),
  experiment: (id: number) => j<any>(`/api/experiments/${id}`),
  plan: (goal: string) => j<any>("/api/plan", { method: "POST", body: JSON.stringify({ goal }) }),
  createStudy: (kind: string, config: any, goal?: string) =>
    j<any>("/api/studies", { method: "POST", body: JSON.stringify({ kind, config, goal }) }),
  studies: () => j<any[]>("/api/studies"),
  compare: () => j<any>("/api/compare"),
};

export const fmt = (v: number | null | undefined, d = 2) =>
  v === null || v === undefined || !Number.isFinite(v) ? "—" : Math.abs(v) >= 1e4 || (Math.abs(v) < 1e-3 && v !== 0) ? v.toExponential(2) : v.toFixed(d);
