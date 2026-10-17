// Shared browser physics: the SAME files the static phone page uses (sim/propulsion/site), validated against the
// Python reference by sim/propulsion/test_propulsion.js. They are classic scripts that attach globals.
/* eslint-disable @typescript-eslint/no-explicit-any */
import "../../../../sim/propulsion/site/rom_data.js";
import "../../../../sim/propulsion/site/propulsion.js";

export const PP: any = (globalThis as any).PropulsionPhysics;
export const ROM: any = (globalThis as any).PROP_ROM;
export const G0 = 9.80665;
export type Mode = "skate" | "cghover" | "rocket";

export const fmt = (v: number | null | undefined, d = 1) =>
  v === null || v === undefined || !Number.isFinite(v) ? "–" : v.toFixed(d);
