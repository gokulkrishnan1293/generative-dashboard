import { memo, useRef, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import type { Dashboard, Filter } from "../lib/types";
import { FilterChip } from "./FilterChip";
import { WidgetView } from "./WidgetView";

export const DashboardFrame = memo(function DashboardFrame({ dashboard, active, detailed }: {
  dashboard: Dashboard;
  active: boolean;
  detailed: boolean;
}) {
  const selected = useStore((s) => s.selection.dashboardIds.includes(dashboard.id));
  const select = useStore((s) => s.select);
  const updateLocal = useStore((s) => s.updateDashboardLocal);
  const upsert = useStore((s) => s.upsertDashboards);
  const removeDashboards = useStore((s) => s.removeDashboards);
  const refreshDashboard = useStore((s) => s.refreshDashboard);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(dashboard.name);
  const drag = useRef<{ mode: "move" | "resize"; sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);

  const onPointerDown = (mode: "move" | "resize") => (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    e.stopPropagation();
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    drag.current = {
      mode, sx: e.clientX, sy: e.clientY, moved: false,
      ox: mode === "move" ? dashboard.x : dashboard.width,
      oy: mode === "move" ? dashboard.y : dashboard.height,
    };
  };
  const onPointerMove = (e: React.PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const zoom = useStore.getState().viewport.zoom;
    const dx = (e.clientX - d.sx) / zoom;
    const dy = (e.clientY - d.sy) / zoom;
    if (Math.abs(dx) + Math.abs(dy) > 2) d.moved = true;
    if (d.mode === "move") updateLocal(dashboard.id, { x: Math.round(d.ox + dx), y: Math.round(d.oy + dy) });
    else updateLocal(dashboard.id, { width: Math.max(360, Math.round(d.ox + dx)), height: Math.max(240, Math.round(d.oy + dy)) });
  };
  const onPointerUp = (e: React.PointerEvent) => {
    const d = drag.current;
    drag.current = null;
    if (!d) return;
    if (!d.moved) {
      if (d.mode === "move") select("dashboard", dashboard.id, e.shiftKey || e.metaKey || e.ctrlKey);
      return;
    }
    const cur = useStore.getState().dashboards[dashboard.id];
    api.patchDashboard(dashboard.id, d.mode === "move" ? { x: cur.x, y: cur.y } : { width: cur.width, height: cur.height })
      .catch(() => undefined);
  };

  const rename = async () => {
    setRenaming(false);
    if (name.trim() && name !== dashboard.name) upsert([await api.patchDashboard(dashboard.id, { name: name.trim() })]);
  };
  const setFilters = async (filters: Filter[]) => {
    upsert([await api.patchDashboard(dashboard.id, { filters })]);
  };
  const remove = async () => {
    if (!confirm(`Delete dashboard “${dashboard.name}”? You can undo this from History.`)) return;
    await api.deleteDashboard(dashboard.id);
    removeDashboards([dashboard.id]);
  };

  return (
    <div
      className={`dashboard ${selected ? "selected" : ""}`}
      style={{ transform: `translate(${dashboard.x}px, ${dashboard.y}px)`, width: dashboard.width, height: dashboard.height }}
      data-dashboard-id={dashboard.id}
    >
      <div
        className="dashboard-head"
        onPointerDown={onPointerDown("move")}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        {renaming ? (
          <input
            className="rename"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={rename}
            onKeyDown={(e) => { if (e.key === "Enter") rename(); if (e.key === "Escape") setRenaming(false); }}
            onPointerDown={(e) => e.stopPropagation()}
          />
        ) : (
          <div className="dashboard-name" onDoubleClick={() => { setName(dashboard.name); setRenaming(true); }} title="Drag to move · double-click to rename · click to select">
            {dashboard.name}
          </div>
        )}
        <div className="dashboard-filters">
          {dashboard.filters.map((f, i) => (
            <FilterChip
              key={`${f.field}-${i}`}
              filter={f}
              onChange={(nf) => setFilters(dashboard.filters.map((x, j) => (j === i ? nf : x)))}
              onRemove={() => setFilters(dashboard.filters.filter((_, j) => j !== i))}
            />
          ))}
        </div>
        <div className="dashboard-actions" onPointerDown={(e) => e.stopPropagation()}>
          <button className="icon-btn" title="Refresh all widgets" onClick={() => refreshDashboard(dashboard.id)}>↻</button>
          <button className="icon-btn" title="Delete dashboard" onClick={remove}>🗑</button>
        </div>
      </div>
      {detailed ? (
        <div className="dashboard-body" data-scrollable>
          {dashboard.widgets.length === 0 && (
            <div className="empty-dashboard">Empty dashboard. Select it and ask the assistant to add widgets.</div>
          )}
          <div className="widget-grid">
            {dashboard.widgets.map((w) => <WidgetView key={w.id} widget={w} dashboard={dashboard} active={active} />)}
          </div>
        </div>
      ) : (
        <div className="dashboard-lod">
          <div className="lod-name">{dashboard.name}</div>
          <div className="lod-count">{dashboard.widgets.length} widgets</div>
        </div>
      )}
      <div className="resize-handle" onPointerDown={onPointerDown("resize")} onPointerMove={onPointerMove} onPointerUp={onPointerUp} />
    </div>
  );
});
