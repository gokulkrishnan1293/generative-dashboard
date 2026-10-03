import { useStore } from "../lib/store";
import type { Dashboard, Viewport } from "../lib/types";
import { bounds } from "./Canvas";

const W = 200;
const H = 130;

/** Navigation aid: an overview of every dashboard and the current view; click to jump. */
export function Minimap({ dashboards, view, onJump }: {
  dashboards: Dashboard[];
  view: { x0: number; y0: number; x1: number; y1: number };
  onJump: (v: Viewport) => void;
}) {
  const size = useStore((s) => s.canvasSize);
  const zoom = useStore((s) => s.viewport.zoom);
  const selected = useStore((s) => s.selection.dashboardIds);
  const b = bounds(dashboards)!;
  const pad = 400;
  const wx0 = Math.min(b.x0, view.x0) - pad;
  const wy0 = Math.min(b.y0, view.y0) - pad;
  const wx1 = Math.max(b.x1, view.x1) + pad;
  const wy1 = Math.max(b.y1, view.y1) + pad;
  const k = Math.min(W / (wx1 - wx0), H / (wy1 - wy0));
  const sx = (x: number) => (x - wx0) * k;
  const sy = (y: number) => (y - wy0) * k;

  return (
    <div className="minimap" onPointerDown={(e) => {
      e.stopPropagation();
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      const wx = (e.clientX - rect.left) / k + wx0;
      const wy = (e.clientY - rect.top) / k + wy0;
      onJump({ zoom, x: size.width / 2 - wx * zoom, y: size.height / 2 - wy * zoom });
    }}>
      <svg width={W} height={H}>
        {dashboards.map((d) => (
          <rect key={d.id} x={sx(d.x)} y={sy(d.y)} width={Math.max(2, d.width * k)} height={Math.max(2, d.height * k)}
            rx={2} className={selected.includes(d.id) ? "mm-dash selected" : "mm-dash"}>
            <title>{d.name}</title>
          </rect>
        ))}
        <rect x={sx(view.x0 + 200 / zoom)} y={sy(view.y0 + 200 / zoom)}
          width={(view.x1 - view.x0 - 400 / zoom) * k} height={(view.y1 - view.y0 - 400 / zoom) * k} className="mm-view" />
      </svg>
    </div>
  );
}
