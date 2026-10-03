import { create } from "zustand";
import { api, setApiRole } from "./api";
import { TaskQueue } from "./queue";
import type {
  AppConfig, ChatMessage, Dashboard, DataSourceSummary, QueryResult, Role, Viewport, Widget, WidgetRuntime,
} from "./types";

const queue = new TaskQueue(4);
const ROLE_KEY = "gd.role";

function storedRole(): Role {
  try {
    const r = localStorage.getItem(ROLE_KEY);
    if (r === "admin" || r === "analyst" || r === "viewer") return r;
  } catch {
    /* storage unavailable */
  }
  return "analyst";
}

export interface Selection {
  dashboardIds: string[];
  widgetIds: string[];
}

interface State {
  ready: boolean;
  loadError: string | null;
  role: Role;
  config: AppConfig | null;
  sources: DataSourceSummary[];
  activeSourceId: string | null;
  dashboards: Record<string, Dashboard>;
  order: string[];
  viewport: Viewport;
  canvasSize: { width: number; height: number };
  selection: Selection;
  results: Record<string, QueryResult>;
  runtime: Record<string, WidgetRuntime>;
  messages: ChatMessage[];
  sending: boolean;
  focusRequest: { ids: string[]; at: number } | null;

  init(): Promise<void>;
  setRole(role: Role): Promise<void>;
  refreshSources(): Promise<void>;
  setActiveSource(id: string): void;
  reloadCanvas(): Promise<void>;
  upsertDashboards(list: Dashboard[]): void;
  removeDashboards(ids: string[]): void;
  setViewport(v: Viewport): void;
  setCanvasSize(size: { width: number; height: number }): void;
  updateDashboardLocal(id: string, patch: Partial<Dashboard>): void;
  select(kind: "dashboard" | "widget", id: string, additive: boolean): void;
  clearSelection(): void;
  ensureData(widget: Widget, force?: boolean): void;
  refreshDashboard(id: string): void;
  send(prompt: string): Promise<void>;
  undo(changeSetId: string): Promise<void>;
  focus(ids: string[]): void;
}

export const useStore = create<State>((set, get) => ({
  ready: false,
  loadError: null,
  role: storedRole(),
  config: null,
  sources: [],
  activeSourceId: null,
  dashboards: {},
  order: [],
  viewport: { x: 0, y: 0, zoom: 1 },
  canvasSize: { width: 1200, height: 800 },
  selection: { dashboardIds: [], widgetIds: [] },
  results: {},
  runtime: {},
  messages: [],
  sending: false,
  focusRequest: null,

  async init() {
    setApiRole(get().role);
    try {
      const [config, sources, canvas, messages] = await Promise.all([
        api.config(), api.sources(), api.canvas(), api.messages(),
      ]);
      set({
        config, sources, messages, viewport: canvas.viewport,
        activeSourceId: sources[0]?.id ?? null, ready: true, loadError: null,
      });
      get().upsertDashboards(canvas.dashboards);
    } catch (e) {
      set({ loadError: e instanceof Error ? e.message : String(e), ready: true });
    }
  },

  async setRole(role) {
    try {
      localStorage.setItem(ROLE_KEY, role);
    } catch {
      /* ignore */
    }
    setApiRole(role);
    // Results are authorized per role; never reuse another role's cache.
    set({ role, results: {}, runtime: {} });
    await get().reloadCanvas();
  },

  async refreshSources() {
    const sources = await api.sources();
    const active = get().activeSourceId;
    set({ sources, activeSourceId: sources.some((s) => s.id === active) ? active : sources[0]?.id ?? null });
  },

  setActiveSource(id) {
    set({ activeSourceId: id });
  },

  async reloadCanvas() {
    const canvas = await api.canvas();
    set({ dashboards: {}, order: [] });
    get().upsertDashboards(canvas.dashboards);
  },

  upsertDashboards(list) {
    set((s) => {
      const dashboards = { ...s.dashboards };
      const order = [...s.order];
      for (const d of list) {
        if (!dashboards[d.id]) order.push(d.id);
        dashboards[d.id] = d;
      }
      return { dashboards, order };
    });
  },

  removeDashboards(ids) {
    set((s) => {
      const dashboards = { ...s.dashboards };
      ids.forEach((id) => delete dashboards[id]);
      return {
        dashboards,
        order: s.order.filter((id) => !ids.includes(id)),
        selection: { dashboardIds: s.selection.dashboardIds.filter((id) => !ids.includes(id)), widgetIds: [] },
      };
    });
  },

  setViewport(v) {
    set({ viewport: v });
  },

  setCanvasSize(size) {
    set({ canvasSize: size });
  },

  updateDashboardLocal(id, patch) {
    set((s) => (s.dashboards[id] ? { dashboards: { ...s.dashboards, [id]: { ...s.dashboards[id], ...patch } } } : {}));
  },

  select(kind, id, additive) {
    set((s) => {
      const key = kind === "dashboard" ? "dashboardIds" : "widgetIds";
      const other = kind === "dashboard" ? "widgetIds" : "dashboardIds";
      const current = s.selection[key];
      let next: string[];
      if (additive) next = current.includes(id) ? current.filter((x) => x !== id) : [...current, id];
      else next = current.length === 1 && current[0] === id ? [] : [id];
      return { selection: { ...s.selection, [key]: next, [other]: additive ? s.selection[other] : [] } as Selection };
    });
  },

  clearSelection() {
    set({ selection: { dashboardIds: [], widgetIds: [] } });
  },

  ensureData(widget, force = false) {
    const { results, runtime } = get();
    const hash = widget.effective_query_hash;
    const rt = runtime[widget.id];
    if (!force && hash && results[hash]) {
      // Definition change that needs no new data (e.g. presentation only): reuse results.
      if (rt?.hash !== hash || rt.status !== (results[hash].row_count ? "success" : "empty")) {
        set((s) => ({
          runtime: { ...s.runtime, [widget.id]: { status: results[hash].row_count ? "success" : "empty", hash } },
        }));
      }
      return;
    }
    if (!force && rt && rt.hash === hash && ["queued", "loading", "error"].includes(rt.status)) return;
    set((s) => ({ runtime: { ...s.runtime, [widget.id]: { status: "queued", hash } } }));
    queue.add(async () => {
      set((s) => ({ runtime: { ...s.runtime, [widget.id]: { status: "loading", hash, startedAt: Date.now() } } }));
      try {
        const result = await api.widgetData(widget.id, force);
        set((s) => ({
          results: { ...s.results, [result.query_hash]: result },
          runtime: {
            ...s.runtime,
            [widget.id]: { status: result.row_count ? "success" : "empty", hash: result.query_hash },
          },
        }));
      } catch (e) {
        set((s) => ({
          runtime: { ...s.runtime, [widget.id]: { status: "error", hash, error: e instanceof Error ? e.message : String(e) } },
        }));
      }
    });
  },

  refreshDashboard(id) {
    const d = get().dashboards[id];
    d?.widgets.forEach((w) => get().ensureData(w, true));
  },

  async send(prompt) {
    const { selection, activeSourceId } = get();
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`, role: "user", content: prompt, status: "ok", clarification: null,
      change_set_id: null, created_at: new Date().toISOString(),
      selection: { dashboard_ids: selection.dashboardIds, widget_ids: selection.widgetIds }, pending: true,
    };
    set((s) => ({ messages: [...s.messages, optimistic], sending: true }));
    try {
      const res = await api.chat(
        prompt, { dashboard_ids: selection.dashboardIds, widget_ids: selection.widgetIds }, activeSourceId,
      );
      set((s) => ({
        messages: [...s.messages.map((m) => (m.id === optimistic.id ? { ...m, pending: false } : m)), res.message],
      }));
      if (res.removed.length) get().removeDashboards(res.removed);
      get().upsertDashboards(res.dashboards);
      if (res.created?.length) get().focus(res.created);
    } catch (e) {
      const error: ChatMessage = {
        ...optimistic, id: `err-${Date.now()}`, role: "assistant", status: "error", pending: false,
        content: e instanceof Error ? e.message : String(e),
      };
      set((s) => ({ messages: [...s.messages.map((m) => (m.id === optimistic.id ? { ...m, pending: false } : m)), error] }));
    } finally {
      set({ sending: false });
    }
  },

  async undo(changeSetId) {
    const canvas = await api.undo(changeSetId);
    set({ dashboards: {}, order: [] });
    get().upsertDashboards(canvas.dashboards);
    set((s) => ({
      messages: s.messages.map((m) => (m.change_set_id === changeSetId ? { ...m, change_set_id: `undone:${changeSetId}` } : m)),
    }));
  },

  focus(ids) {
    set({ focusRequest: { ids, at: Date.now() } });
  },
}));
