import type { SimResult } from "../api";
export function ParameterEditor(_props: { onResult: (r: SimResult) => void; current: SimResult | null }) {
  return <div className="panel"><h2>Parameters</h2><p className="muted">Parameter editor: next milestone.</p></div>;
}
