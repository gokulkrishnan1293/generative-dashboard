import { useCallback, useEffect, useMemo, useRef } from "react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import type { Dashboard, Viewport } from "../lib/types";
import { DashboardFrame } from "./DashboardFrame";
import { Minimap } from "./Minimap";

const MIN_ZOOM = 0.1;
const MAX_ZOOM = 2;
const DETAIL_ZOOM = 0.3; // below this, dashboards render as lightweight placeholders and don't fetch
const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

export function bounds(list: Dashboard[]) {
  if (!list.length) return null;
  return {
    x0: Math.min(...list.map((d) => d.x)),
    y0: Math.min(...list.map((d) => d.y)),
    x1: Math.max(...list.map((d) => d.x + d.width)),
    y1: Math.max(...list.map((d) => d.y + d.height)),
  };
}

export function fitViewport(list: Dashboard[], size: { width: number; height: number }, maxZoom = 1): Viewport | null {
  const b = bounds(list);
  if (!b) return null;
  const pad = 60;
  const zoom = clampZoom(Math.min(maxZoom, (size.width - pad * 2) / (b.x1 - b.x0), (size.height - pad * 2) / (b.y1 - b.y0)));
  return {
    zoom,
    x: (size.width - (b.x1 - b.x0) * zoom) / 2 - b.x0 * zoom,
    y: (size.height - (b.y1 - b.y0) * zoom) / 2 - b.y0 * zoom,
  };
}

function canScroll(el: HTMLElement | null, dx: number, dy: number): boolean {
  while (el && !el.classList.contains("canvas")) {
    if (el.hasAttribute("data-scrollable")) {
      const canY = dy !== 0 && el.scrollHeight > el.clientHeight + 1 &&
        ((dy > 0 && el.scrollTop + el.clientHeight < el.scrollHeight - 1) || (dy < 0 && el.scrollTop > 0));
      const canX = dx !== 0 && el.scrollWidth > el.clientWidth + 1 &&
        ((dx > 0 && el.scrollLeft + el.clientWidth < el.scrollWidth - 1) || (dx < 0 && el.scrollLeft > 0));
      if (canX || canY) return true;
    }
    el = el.parentElement;
  }
  return false;
}

export function Canvas() {
  const ref = useRef<HTMLDivElement>(null);
  const viewport = useStore((s) => s.viewport);
  const setViewport = useStore((s) => s.setViewport);
  const dashboards = useStore((s) => s.dashboards);
  const order = useStore((s) => s.order);
  const size = useStore((s) => s.canvasSize);
  const setCanvasSize = useStore((s) => s.setCanvasSize);
  const clearSelection = useStore((s) => s.clearSelection);
  const focusRequest = useStore((s) => s.focusRequest);
  const pan = useRef<{ sx: number; sy: number; ox: number; oy: number; moved: boolean } | null>(null);
  const saveTimer = useRef<number>();

  const list = useMemo(() => order.map((id) => dashboards[id]).filter(Boolean), [order, dashboards]);

  const update = useCallback((v: Viewport) => {
    setViewport(v);
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => api.saveViewport(v).catch(() => undefined), 600);
  }, [setViewport]);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setCanvasSize({ width: el.clientWidth, height: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, [setCanvasSize]);

  // Wheel: pan (trackpad friendly); Ctrl/⌘ + wheel or pinch: zoom around the cursor.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const v = useStore.getState().viewport;
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        const rect = el.getBoundingClientRect();
        const cx = e.clientX - rect.left;
        const cy = e.clientY - rect.top;
        const zoom = clampZoom(v.zoom * Math.exp(-e.deltaY * 0.0025));
        const k = zoom / v.zoom;
        update({ zoom, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k });
        return;
      }
      if (canScroll(e.target as HTMLElement, e.deltaX, e.deltaY)) return;
      e.preventDefault();
      update({ ...v, x: v.x - e.deltaX, y: v.y - e.deltaY });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [update]);

  useEffect(() => {
    if (!focusRequest) return;
    const targets = focusRequest.ids.map((id) => useStore.getState().dashboards[id]).filter(Boolean);
    const v = fitViewport(targets, useStore.getState().canvasSize);
    if (v) update(v);
  }, [focusRequest, update]);

  const zoomBy = (factor: number) => {
    const v = useStore.getState().viewport;
    const zoom = clampZoom(v.zoom * factor);
    const cx = size.width / 2;
    const cy = size.height / 2;
    update({ zoom, x: cx - (cx - v.x) * (zoom / v.zoom), y: cy - (cy - v.y) * (zoom / v.zoom) });
  };

  const fitAll = () => {
    const v = fitViewport(list, size);
    if (v) update(v);
  };

  // World-space rectangle currently on screen (with margin) decides which dashboards load data.
  const margin = 200 / viewport.zoom;
  const view = {
    x0: -viewport.x / viewport.zoom - margin,
    y0: -viewport.y / viewport.zoom - margin,
    x1: (size.width - viewport.x) / viewport.zoom + margin,
    y1: (size.height - viewport.y) / viewport.zoom + margin,
  };
  const detailed = viewport.zoom >= DETAIL_ZOOM;

  return (
    <div
      ref={ref}
      className="canvas"
      style={{
        backgroundPosition: `${viewport.x}px ${viewport.y}px`,
        backgroundSize: `${24 * viewport.zoom}px ${24 * viewport.zoom}px`,
      }}
      onPointerDown={(e) => {
        if (e.button !== 0 && e.button !== 1) return;
        (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
        pan.current = { sx: e.clientX, sy: e.clientY, ox: viewport.x, oy: viewport.y, moved: false };
      }}
      onPointerMove={(e) => {
        const p = pan.current;
        if (!p) return;
        const dx = e.clientX - p.sx;
        const dy = e.clientY - p.sy;
        if (Math.abs(dx) + Math.abs(dy) > 3) p.moved = true;
        if (p.moved) setViewport({ ...useStore.getState().viewport, x: p.ox + dx, y: p.oy + dy });
      }}
      onPointerUp={() => {
        const p = pan.current;
        pan.current = null;
        if (!p) return;
        if (p.moved) update(useStore.getState().viewport);
        else clearSelection();
      }}
    >
      <div className="world" style={{ transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})` }}>
        {list.map((d) => {
          const visible = d.x < view.x1 && d.x + d.width > view.x0 && d.y < view.y1 && d.y + d.height > view.y0;
          return <DashboardFrame key={d.id} dashboard={d} active={visible && detailed} detailed={detailed} />;
        })}
      </div>

      {list.length === 0 && (
        <div className="canvas-empty">
          <h2>Your canvas is empty</h2>
          <p>Describe a dashboard in the assistant panel, for example<br />
            <em>“Create a sales dashboard showing monthly revenue, top customers and revenue by customer region.”</em></p>
          <p className="muted">Drag the background to pan · Ctrl/⌘ + scroll to zoom · click a dashboard or widget to select it</p>
        </div>
      )}

      <div className="zoom-controls" onPointerDown={(e) => e.stopPropagation()}>
        <button onClick={() => zoomBy(1 / 1.2)} title="Zoom out">−</button>
        <button className="zoom-level" onClick={() => update({ ...viewport, zoom: 1 })} title="Reset to 100%">
          {Math.round(viewport.zoom * 100)}%
        </button>
        <button onClick={() => zoomBy(1.2)} title="Zoom in">+</button>
        <button onClick={fitAll} title="Fit all dashboards">Fit</button>
      </div>
      {list.length > 0 && <Minimap dashboards={list} view={view} onJump={update} />}
    </div>
  );
}
