import type { FieldOverlayData } from "../components/FieldOverlay";
export function SolversPanel(_props: { onOverlay: (f: FieldOverlayData | null) => void; overlay: FieldOverlayData | null;
  harness: { connected: boolean; url: string; detail: string } | null }) {
  return <div className="panel"><h2>Solvers</h2><p className="muted">next milestone.</p></div>;
}
