import { useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";

/** Left rail: every dashboard on the canvas, for quick navigation. */
export function DashboardList() {
  const order = useStore((s) => s.order);
  const dashboards = useStore((s) => s.dashboards);
  const selection = useStore((s) => s.selection.dashboardIds);
  const focus = useStore((s) => s.focus);
  const select = useStore((s) => s.select);
  const upsert = useStore((s) => s.upsertDashboards);
  const activeSourceId = useStore((s) => s.activeSourceId);
  const viewport = useStore((s) => s.viewport);
  const size = useStore((s) => s.canvasSize);
  const [open, setOpen] = useState(true);

  const addBlank = async () => {
    if (!activeSourceId) return;
    const x = (size.width / 2 - viewport.x) / viewport.zoom - 300;
    const y = (size.height / 2 - viewport.y) / viewport.zoom - 200;
    const d = await api.createDashboard("Untitled dashboard", activeSourceId, Math.round(x), Math.round(y));
    upsert([d]);
    select("dashboard", d.id, false);
  };

  return (
    <nav className={`dash-list ${open ? "" : "collapsed"}`}>
      <div className="dash-list-head">
        {open && <span>Dashboards</span>}
        <button className="icon-btn" onClick={() => setOpen((o) => !o)} title={open ? "Collapse" : "Expand"}>{open ? "‹" : "›"}</button>
      </div>
      {open && (
        <>
          <div className="dash-items">
            {order.length === 0 && <div className="muted pad small">None yet</div>}
            {order.map((id) => dashboards[id] && (
              <button
                key={id}
                className={`dash-item ${selection.includes(id) ? "selected" : ""}`}
                onClick={() => { focus([id]); select("dashboard", id, false); }}
                title={dashboards[id].description || dashboards[id].name}
              >
                <span className="dash-item-name">{dashboards[id].name}</span>
                <span className="muted small">{dashboards[id].widgets.length}</span>
              </button>
            ))}
          </div>
          <button className="btn small block" onClick={addBlank} disabled={!activeSourceId}>+ Blank dashboard</button>
        </>
      )}
    </nav>
  );
}
