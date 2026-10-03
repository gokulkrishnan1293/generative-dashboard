import { memo, useEffect, useState } from "react";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useStore } from "../lib/store";
import { useChartTheme } from "../lib/theme";
import type { Dashboard, Filter, Widget, WidgetType } from "../lib/types";
import { WidgetBody } from "./Charts";
import { FilterChip } from "./FilterChip";

const TYPES: WidgetType[] = ["kpi", "table", "bar", "line", "area", "pie"];

function useTicker(active: boolean, ms = 1000) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setTick((x) => x + 1), ms);
    return () => clearInterval(t);
  }, [active, ms]);
}

export const WidgetView = memo(function WidgetView({ widget, dashboard, active }: {
  widget: Widget;
  dashboard: Dashboard;
  active: boolean;
}) {
  const runtime = useStore((s) => s.runtime[widget.id]);
  const result = useStore((s) => (runtime?.hash ? s.results[runtime.hash] : undefined));
  const selected = useStore((s) => s.selection.widgetIds.includes(widget.id));
  const select = useStore((s) => s.select);
  const ensureData = useStore((s) => s.ensureData);
  const upsert = useStore((s) => s.upsertDashboards);
  const theme = useChartTheme();
  const [asTable, setAsTable] = useState(false);
  const [menu, setMenu] = useState(false);
  const status = runtime?.status ?? "idle";
  useTicker(status === "loading" || status === "success", status === "loading" ? 1000 : 30000);

  useEffect(() => {
    if (active) ensureData(widget);
  }, [active, widget.effective_query_hash, widget.id, ensureData, widget]);

  const replaceWidget = (w: Widget) =>
    upsert([{ ...dashboard, widgets: dashboard.widgets.map((x) => (x.id === w.id ? w : x)) }]);

  const updateFilters = async (filters: Filter[]) => {
    replaceWidget(await api.patchWidget(widget.id, { filters }));
  };

  const changeType = async (type: WidgetType) => {
    setMenu(false);
    replaceWidget(await api.patchWidget(widget.id, { type }));
  };

  const remove = async () => {
    setMenu(false);
    const res = await api.deleteWidget(widget.id);
    upsert([res.dashboard]);
  };

  const p = widget.presentation;
  const filters = widget.query.filters ?? [];
  const elapsed = runtime?.startedAt ? Math.round((Date.now() - runtime.startedAt) / 1000) : 0;

  return (
    <div
      className={`widget ${selected ? "selected" : ""}`}
      style={{ gridColumn: `span ${Math.min(12, p.w ?? 6)}`, gridRow: `span ${p.h ?? 4}` }}
      onPointerDown={(e) => e.stopPropagation()}
      onClick={(e) => {
        e.stopPropagation();
        select("widget", widget.id, e.shiftKey || e.metaKey || e.ctrlKey);
      }}
    >
      <div className="widget-head">
        <div className="widget-title" title={widget.title}>{widget.title}</div>
        <div className="widget-meta">
          {status === "loading" && <span className="status-loading"><span className="spinner" />Running{elapsed >= 2 ? ` · ${elapsed}s` : ""}</span>}
          {status === "queued" && <span className="muted">Queued</span>}
          {(status === "success" || status === "empty") && result && (
            <span className="muted" title={`Executed ${new Date(result.executed_at).toLocaleString()} in ${result.duration_ms} ms${result.cached ? " (served from cache)" : ""}`}>
              {timeAgo(result.executed_at)}
            </span>
          )}
          <button className="icon-btn" title="Refresh data" onClick={(e) => { e.stopPropagation(); ensureData(widget, true); }}>↻</button>
          <div className="menu-anchor">
            <button className="icon-btn" title="More" onClick={(e) => { e.stopPropagation(); setMenu((m) => !m); }}>⋯</button>
            {menu && (
              <div className="menu" onClick={(e) => e.stopPropagation()}>
                <button onClick={() => { setAsTable((t) => !t); setMenu(false); }}>{asTable ? "Show chart" : "View as table"}</button>
                <div className="menu-sep" />
                <div className="menu-label">Display as</div>
                {TYPES.map((t) => (
                  <button key={t} className={t === widget.type ? "active" : ""} onClick={() => changeType(t)}>{t}</button>
                ))}
                <div className="menu-sep" />
                <button className="danger" onClick={remove}>Remove widget</button>
              </div>
            )}
          </div>
        </div>
      </div>
      {(filters.length > 0 || widget.dependency_issues.length > 0 || widget.skipped_filters.length > 0) && (
        <div className="widget-sub">
          {filters.map((f, i) => (
            <FilterChip
              key={`${f.field}-${i}`}
              filter={f}
              onChange={(nf) => updateFilters(filters.map((x, j) => (j === i ? nf : x)))}
              onRemove={() => updateFilters(filters.filter((_, j) => j !== i))}
            />
          ))}
          {widget.dependency_issues.length > 0 && (
            <span className="badge warn" title={widget.dependency_issues.join("\n")}>⚠ Definition needs review</span>
          )}
          {widget.skipped_filters.length > 0 && (
            <span className="badge muted" title={widget.skipped_filters.map((s) => `${s.field}: ${s.reason}`).join("\n")}>
              {widget.skipped_filters.length} dashboard filter(s) not applicable
            </span>
          )}
        </div>
      )}
      <div className="widget-body">
        {status === "error" && (
          <div className="widget-state error">
            <strong>Couldn’t load this view</strong>
            <span>{runtime?.error}</span>
            <button className="btn small" onClick={() => ensureData(widget, true)}>Retry</button>
          </div>
        )}
        {(status === "idle" || status === "queued" || (status === "loading" && !result)) && (
          <div className="widget-state"><div className="skeleton" /></div>
        )}
        {status === "empty" && <div className="widget-state"><span className="muted">No rows match this view.</span></div>}
        {result && (status === "success" || (status === "loading" && result.row_count > 0)) && (
          <div className={`widget-content ${status === "loading" ? "stale" : ""}`}>
            <WidgetBody widget={widget} result={result} theme={theme} asTable={asTable} />
          </div>
        )}
      </div>
      {result?.truncated && status === "success" && (
        <div className="widget-foot muted">Showing first {result.limit.toLocaleString()} rows</div>
      )}
    </div>
  );
});
