// Live telemetry. Every value is read from the recorded simulation frame. Values derived from uncertain
// engineering models (electrical power, energy, temperature) are tagged ESTIMATE with their model.
import type { SimResult, V3 } from "../api";
import { fmt } from "../api";
import { AttitudeIndicator } from "./Attitude";

const norm = (v: V3) => Math.hypot(v[0], v[1], v[2]);

function Row({ k, v, unit, tag }: { k: string; v: string; unit?: string; tag?: "est" | "hyp" | "ref" }) {
  return (
    <div className="dash-row">
      <span className="dash-k">{k}{tag === "est" && <span className="tag est">ESTIMATE</span>}
        {tag === "hyp" && <span className="tag hyp">HYPOTHETICAL</span>}{tag === "ref" && <span className="tag ref">SETPOINT</span>}</span>
      <span className="dash-v">{v}{unit && <span className="dash-u"> {unit}</span>}</span>
    </div>
  );
}

const vec = (v: V3, d = 4) => `${fmt(v[0], d)}, ${fmt(v[1], d)}, ${fmt(v[2], d)}`;

export function Dashboard({ res, idx }: { res: SimResult; idx: number }) {
  const tr = res.trajectory;
  const veh = res.vehicle;
  const hyp = veh.hypothetical || res.summary.mode === "ideal";
  const p = tr.pos[idx];
  const clearance = p[2] - (veh.cg_m[2] + veh.height_m / 2);
  const e = tr.euler_deg[idx];
  const weight = res.summary.weight_n as number;
  const lift = tr.F_act[idx][2];
  const ph = res.phases[tr.phase[idx]];
  const temps = tr.temp_c[idx];
  const modeCfg = res.mode_config;
  return (
    <div className="dashboard">
      <div className="dash-group">
        <div className="dash-title">Simulation</div>
        <Row k="sim time" v={fmt(tr.t[idx], 5)} unit="s" />
        <Row k="phase" v={ph ? ph.label : "—"} />
        <Row k="integrator" v={res.integrator} />
        <Row k="evidence" v={String(res.summary.evidence)} />
      </div>
      <div className="dash-group attitude-box">
        <AttitudeIndicator roll={e[0]} pitch={e[1]} yaw={e[2]} />
      </div>
      <div className="dash-group">
        <div className="dash-title">Kinematics (world frame, CG)</div>
        <Row k="position x,y,z" v={vec(p)} unit="m" />
        <Row k="altitude (ground clearance)" v={fmt(clearance, 4)} unit="m" />
        <Row k="velocity" v={vec(tr.vel[idx])} unit="m/s" />
        <Row k="|v|" v={fmt(norm(tr.vel[idx]))} unit="m/s" />
        <Row k="acceleration" v={vec(tr.acc[idx])} unit="m/s²" />
        <Row k="roll, pitch, yaw" v={`${e[0].toFixed(2)}, ${e[1].toFixed(2)}, ${e[2].toFixed(2)}`} unit="deg" />
        <Row k="ω body" v={vec(tr.omega[idx])} unit="rad/s" />
        <Row k="ω̇ body" v={vec(tr.omega_dot[idx])} unit="rad/s²" />
      </div>
      <div className="dash-group">
        <div className="dash-title">Forces & torques</div>
        <Row k="mass" v={fmt(veh.mass_kg * 1000, 5)} unit="g" />
        <Row k="gravity force m·g" v={fmt(-tr.F_grav[idx][2], 5)} unit="N" />
        <Row k={hyp ? "applied lift (actuators, z)" : "actuator lift (z)"} v={fmt(lift, 5)} unit="N" tag={hyp ? "hyp" : undefined} />
        <Row k="lift / weight" v={fmt(lift / weight, 5)} />
        {tr.f_act[idx].map((f, i) => (
          <Row key={i} k={`  actuator A${i} force`} v={fmt(f, 4)} unit="N" tag={hyp ? "hyp" : undefined} />
        ))}
        <Row k="ground contact force" v={vec(tr.F_contact[idx])} unit="N" />
        <Row k="aero drag" v={vec(tr.F_drag[idx])} unit="N" />
        <Row k="disturbance" v={vec(tr.F_ext[idx])} unit="N" />
        <Row k="net force" v={vec(tr.F_net[idx])} unit="N" />
        <Row k="net torque (body)" v={vec(tr.tau_net[idx])} unit="N·m" />
        <Row k="angular momentum |L|" v={fmt(norm(tr.L_world[idx]))} unit="kg·m²/s" />
      </div>
      <div className="dash-group">
        <div className="dash-title">Control</div>
        <Row k="setpoint" v={vec(tr.ref_pos[idx])} unit="m" tag="ref" />
        <Row k="position error" v={vec(tr.err_pos[idx])} unit="m" />
        <Row k="|error|" v={fmt(norm(tr.err_pos[idx]))} unit="m" />
        <Row k="tilt command" v={fmt(tr.tilt_cmd_deg[idx], 3)} unit="deg" />
        <Row k="yaw setpoint" v={fmt(tr.ref_yaw_deg[idx], 4)} unit="deg" tag="ref" />
        <Row k="armed / saturated" v={`${tr.armed[idx] ? "ARMED" : "disarmed"} / ${tr.saturated[idx] ? "SATURATED" : "ok"}`} />
      </div>
      <div className="dash-group">
        <div className="dash-title">Energy</div>
        <Row k="electrical power" v={fmt(tr.power_w[idx], 4)} unit="W" tag="est" />
        <Row k="consumed energy" v={fmt(tr.energy_j[idx], 4)} unit="J" tag="est" />
        <div className="dash-note">{res.power_model}</div>
        <Row k="kinetic energy" v={fmt(tr.ke_j[idx], 4)} unit="J" />
        <Row k="potential energy (z=0)" v={fmt(tr.pe_j[idx], 4)} unit="J" />
        {modeCfg?.thermal?.enabled && modeCfg.mode === "reality" && (
          <Row k="actuator temperature max" v={fmt(Math.max(...temps), 4)} unit="°C" tag="est" />
        )}
      </div>
    </div>
  );
}
