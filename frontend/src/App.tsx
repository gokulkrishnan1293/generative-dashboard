import { useEffect, useState } from "react";
import { Canvas } from "./components/Canvas";
import { ChatPanel } from "./components/ChatPanel";
import { DashboardList } from "./components/DashboardList";
import { MetadataView } from "./components/MetadataView";
import { useStore } from "./lib/store";
import type { Role } from "./lib/types";

const TAB_KEY = "gd.tab";

export default function App() {
  const init = useStore((s) => s.init);
  const ready = useStore((s) => s.ready);
  const loadError = useStore((s) => s.loadError);
  const role = useStore((s) => s.role);
  const setRole = useStore((s) => s.setRole);
  const config = useStore((s) => s.config);
  const sources = useStore((s) => s.sources);
  const activeSourceId = useStore((s) => s.activeSourceId);
  const setActive = useStore((s) => s.setActiveSource);
  const [tab, setTab] = useState<"canvas" | "metadata">(() => {
    try {
      return localStorage.getItem(TAB_KEY) === "metadata" ? "metadata" : "canvas";
    } catch {
      return "canvas";
    }
  });

  useEffect(() => {
    init();
  }, [init]);
  useEffect(() => {
    try {
      localStorage.setItem(TAB_KEY, tab);
    } catch {
      /* ignore */
    }
  }, [tab]);

  const active = sources.find((s) => s.id === activeSourceId);
  const noApproved = active && !(active.status_counts.approved > 0);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">◆ Generative Dashboard</div>
        <nav className="tabs">
          <button className={tab === "canvas" ? "active" : ""} onClick={() => setTab("canvas")}>Canvas</button>
          <button className={tab === "metadata" ? "active" : ""} onClick={() => setTab("metadata")}>
            Metadata{noApproved ? <span className="dot" title="Needs review" /> : null}
          </button>
        </nav>
        <span className="spacer" />
        <label className="top-field">Source
          <select value={activeSourceId ?? ""} onChange={(e) => setActive(e.target.value)}>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </select>
        </label>
        <label className="top-field" title="Demo identity sent as X-Role; the execution layer authorizes every request with it">Role
          <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {(config?.roles ?? ["admin", "analyst", "viewer"]).map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </label>
        <span className={`pill ${config?.llm_configured ? "ok" : "warn"}`} title={config ? `Gateway: ${config.gateway}` : ""}>
          {config ? (config.llm_configured ? `Model: ${config.model}` : "No model configured") : "…"}
        </span>
      </header>
      {!ready ? (
        <div className="center-fill muted">Loading…</div>
      ) : loadError ? (
        <div className="center-fill">
          <div className="notice error">Could not reach the API: {loadError}. Is the backend running on port 8000?</div>
        </div>
      ) : tab === "metadata" ? (
        <MetadataView />
      ) : (
        <div className="workspace">
          <DashboardList />
          <div className="canvas-wrap">
            {noApproved && (
              <div className="banner">
                The selected data source has no approved metadata yet, so the assistant can’t build dashboards.{" "}
                <button className="link" onClick={() => setTab("metadata")}>Review metadata →</button>
              </div>
            )}
            <Canvas />
          </div>
          <ChatPanel />
        </div>
      )}
    </div>
  );
}
