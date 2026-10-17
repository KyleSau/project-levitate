import { useEffect, useState } from "react";
import { api } from "./api";
import Lab from "./pages/Lab";
import Explorer from "./pages/Explorer";
import ResearchConsole from "./pages/ResearchConsole";
import Survey from "./pages/Survey";
import EhdLab from "./pages/EhdLab";
import HumanLab from "./pages/HumanLab";

const TABS = [
  ["lab", "Testing Chamber"],
  ["human", "Human Scale"],
  ["ehd", "Ionic-Wind Lab"],
  ["survey", "Propulsion Survey"],
  ["explorer", "Experiment Explorer"],
  ["console", "AI Research Console"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function App() {
  const [tab, setTab] = useState<Tab>("lab");
  const [health, setHealth] = useState<any>(null);
  const [err, setErr] = useState(false);
  const [loadExp, setLoadExp] = useState<number | null>(null);

  useEffect(() => {
    const ping = () => api.health().then((h) => { setHealth(h); setErr(false); }).catch(() => setErr(true));
    ping();
    const id = setInterval(ping, 10000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">PROJECT <span>LEVITATE</span></div>
        <div className="tabs">
          {TABS.map(([k, label]) => (
            <button key={k} className={`tab ${tab === k ? "active" : ""}`} onClick={() => setTab(k)}>{label}</button>
          ))}
        </div>
        <div className="status">
          <span className="dot" style={{ background: err ? "var(--bad)" : health ? "var(--good)" : "var(--warn)" }} />
          {err ? "backend NOT CONNECTED (start backend on :8000)" : health ? `harness ${health.versions.levitate} · code ${health.versions.code_sha}` : "connecting…"}
        </div>
      </div>
      <div className="main">
        {tab === "lab" && <Lab loadExperiment={loadExp} />}
        {tab === "ehd" && <EhdLab />}
        {tab === "human" && <HumanLab />}
        {tab === "survey" && <Survey />}
        {tab === "explorer" && <Explorer onOpen={(id) => { setLoadExp(id); setTab("lab"); }} />}
        {tab === "console" && <ResearchConsole onOpen={(id) => { setLoadExp(id); setTab("lab"); }} />}
      </div>
    </div>
  );
}
