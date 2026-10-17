import type { SimResult } from "../api";
export function ExperimentsPanel(_props: { current: SimResult | null; onLoad: (r: SimResult) => void }) {
  return <div className="panel"><h2>Experiments</h2><p className="muted">next milestone.</p></div>;
}
