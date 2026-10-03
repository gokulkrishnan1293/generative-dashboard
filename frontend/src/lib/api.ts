import type {
  AppConfig, ChatMessage, Dashboard, DataSourceSummary, Filter, HistoryItem, ImpactItem, MetadataDoc,
  Presentation, QueryResult, Viewport, Widget, WidgetType,
} from "./types";

let currentRole = "analyst";
export const setApiRole = (role: string) => {
  currentRole = role;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message);
  if (Array.isArray(detail)) return detail.map((d) => d.msg ?? JSON.stringify(d)).join("; ");
  return JSON.stringify(detail);
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "Content-Type": "application/json", "X-Role": currentRole },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) {
    let message = res.statusText;
    try {
      message = detailMessage((await res.json()).detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

export interface ChatResponse {
  message: ChatMessage;
  dashboards: Dashboard[];
  removed: string[];
  created?: string[];
}

export const api = {
  config: () => request<AppConfig>("GET", "/config"),
  canvas: () => request<{ viewport: Viewport; dashboards: Dashboard[] }>("GET", "/canvas"),
  saveViewport: (v: Viewport) => request<Viewport>("PUT", "/canvas/viewport", v),

  createDashboard: (name: string, dataSourceId: string, x: number, y: number) =>
    request<Dashboard>("POST", "/dashboards", { name, data_source_id: dataSourceId, x, y }),
  patchDashboard: (id: string, patch: Partial<Pick<Dashboard, "name" | "x" | "y" | "width" | "height" | "filters">>) =>
    request<Dashboard>("PATCH", `/dashboards/${id}`, patch),
  deleteDashboard: (id: string) => request<{ deleted: string }>("DELETE", `/dashboards/${id}`),

  patchWidget: (id: string, patch: { title?: string; type?: WidgetType; presentation?: Presentation; filters?: Filter[] }) =>
    request<Widget>("PATCH", `/widgets/${id}`, patch),
  deleteWidget: (id: string) => request<{ dashboard: Dashboard }>("DELETE", `/widgets/${id}`),
  widgetData: (id: string, force = false) => request<QueryResult>("POST", `/widgets/${id}/data?force=${force}`),

  history: () => request<HistoryItem[]>("GET", "/history"),
  undo: (id: string) => request<{ viewport: Viewport; dashboards: Dashboard[] }>("POST", `/history/${id}/undo`),

  messages: () => request<ChatMessage[]>("GET", "/agent/messages"),
  clearMessages: () => request<unknown>("DELETE", "/agent/messages"),
  chat: (prompt: string, selection: { dashboard_ids: string[]; widget_ids: string[] }, dataSourceId: string | null) =>
    request<ChatResponse>("POST", "/agent/chat", { prompt, selection, data_source_id: dataSourceId }),

  sources: () => request<DataSourceSummary[]>("GET", "/datasources"),
  createSource: (name: string, url: string, documentation: string) =>
    request<DataSourceSummary & { changes: string[] }>("POST", "/datasources", { name, url, documentation }),
  updateSource: (id: string, patch: { name?: string; documentation?: string }) =>
    request<DataSourceSummary>("PATCH", `/datasources/${id}`, patch),
  deleteSource: (id: string) => request<unknown>("DELETE", `/datasources/${id}`),
  discover: (id: string) =>
    request<{ changes: string[]; metadata: MetadataDoc; impact: ImpactItem[] }>("POST", `/datasources/${id}/discover`),
  draft: (id: string, overwrite = false) =>
    request<{ notes: string[]; metadata: MetadataDoc }>("POST", `/datasources/${id}/draft?overwrite=${overwrite}`),
  metadata: (id: string) => request<MetadataDoc>("GET", `/datasources/${id}/metadata`),
  saveMetadata: (id: string, doc: MetadataDoc) =>
    request<{ metadata: MetadataDoc; impact: ImpactItem[] }>("PUT", `/datasources/${id}/metadata`, doc),
  loadDemoMetadata: (id: string) => request<{ metadata: MetadataDoc }>("POST", `/datasources/${id}/metadata/load-demo`),
  impact: (id: string) => request<ImpactItem[]>("GET", `/datasources/${id}/impact`),
};
