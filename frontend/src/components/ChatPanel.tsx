import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useStore } from "../lib/store";
import type { HistoryItem } from "../lib/types";

const SUGGESTIONS = [
  "Create a sales dashboard showing monthly revenue, top 10 customers and revenue by customer region",
  "Build an operations dashboard with order counts by status and a table of pending orders",
  "Create a product dashboard with gross margin by category and units sold per month",
];

function SelectionChip() {
  const selection = useStore((s) => s.selection);
  const dashboards = useStore((s) => s.dashboards);
  const clear = useStore((s) => s.clearSelection);
  const names: string[] = [];
  for (const id of selection.dashboardIds) if (dashboards[id]) names.push(`▣ ${dashboards[id].name}`);
  for (const id of selection.widgetIds) {
    for (const d of Object.values(dashboards)) {
      const w = d.widgets.find((x) => x.id === id);
      if (w) names.push(`◧ ${w.title}`);
    }
  }
  if (!names.length) return <div className="selection-chip none">No selection — requests apply to the whole canvas</div>;
  return (
    <div className="selection-chip">
      <span className="selection-label">Editing</span>
      <span className="selection-names" title={names.join("\n")}>{names.join(", ")}</span>
      <button className="chip-btn" onClick={clear} title="Clear selection">×</button>
    </div>
  );
}

function History() {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const undo = useStore((s) => s.undo);
  const load = () => api.history().then(setItems).catch((e) => setError(String(e)));
  useEffect(() => {
    load();
  }, []);
  return (
    <div className="history">
      {error && <div className="error-text">{error}</div>}
      {items?.length === 0 && <div className="muted pad">No changes yet.</div>}
      {items?.map((h) => (
        <div key={h.id} className={`history-item ${h.undone ? "undone" : ""}`}>
          <div className="history-summary">{h.summary || "(change)"}</div>
          <div className="history-meta">
            <span className={`badge ${h.source === "agent" ? "info" : "muted"}`}>{h.source}</span>
            <span className="muted">{timeAgo(h.created_at)}</span>
            {!h.undone ? (
              <button className="btn small" onClick={async () => {
                try {
                  await undo(h.id);
                  load();
                } catch (e) {
                  setError(e instanceof Error ? e.message : String(e));
                }
              }}>Undo</button>
            ) : <span className="muted">undone</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ChatPanel() {
  const messages = useStore((s) => s.messages);
  const sending = useStore((s) => s.sending);
  const send = useStore((s) => s.send);
  const undo = useStore((s) => s.undo);
  const config = useStore((s) => s.config);
  const [text, setText] = useState("");
  const [tab, setTab] = useState<"chat" | "history">("chat");
  const [undoError, setUndoError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [messages.length, sending]);

  const submit = (prompt: string) => {
    const p = prompt.trim();
    if (!p || sending) return;
    setText("");
    send(p);
  };

  return (
    <aside className="chat-panel">
      <div className="panel-tabs">
        <button className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>Assistant</button>
        <button className={tab === "history" ? "active" : ""} onClick={() => setTab("history")}>History</button>
        <span className="spacer" />
        {tab === "chat" && messages.length > 0 && (
          <button className="link" onClick={async () => { await api.clearMessages(); useStore.setState({ messages: [] }); }}>Clear</button>
        )}
      </div>
      {tab === "history" ? <History /> : (
        <>
          {config && !config.llm_configured && (
            <div className="notice warn">
              No model configured. Set <code>OPENAI_API_KEY</code> (and optionally <code>OPENAI_BASE_URL</code> for your gateway) in <code>.env</code> and restart the backend.
            </div>
          )}
          <div className="messages" ref={listRef}>
            {messages.length === 0 && (
              <div className="intro">
                <p>Describe the dashboard you need. Select a dashboard or widget first to change just that part.</p>
                {SUGGESTIONS.map((s) => (
                  <button key={s} className="suggestion" onClick={() => submit(s)} disabled={sending}>{s}</button>
                ))}
              </div>
            )}
            {messages.map((m) => (
              <div key={m.id} className={`msg ${m.role} ${m.status}`}>
                {m.role === "user" && (m.selection?.widget_ids?.length || m.selection?.dashboard_ids?.length) ? (
                  <div className="msg-scope">on selection</div>
                ) : null}
                <div className="msg-text">{m.content}</div>
                {m.clarification && m.clarification.options.length > 0 && (
                  <div className="options">
                    {m.clarification.options.map((o) => (
                      <button key={o} className="btn small" disabled={sending} onClick={() => submit(o)}>{o}</button>
                    ))}
                  </div>
                )}
                {m.role === "assistant" && m.change_set_id && !m.change_set_id.startsWith("undone:") && (
                  <button className="link small" onClick={async () => {
                    try {
                      setUndoError(null);
                      await undo(m.change_set_id!);
                    } catch (e) {
                      setUndoError(e instanceof Error ? e.message : String(e));
                    }
                  }}>Undo this change</button>
                )}
                {m.change_set_id?.startsWith("undone:") && <span className="muted small">Change undone</span>}
              </div>
            ))}
            {sending && (
              <div className="msg assistant pending"><span className="spinner" /> Designing data requests and layout…</div>
            )}
            {undoError && <div className="error-text">{undoError}</div>}
          </div>
          <SelectionChip />
          <form className="composer" onSubmit={(e) => { e.preventDefault(); submit(text); }}>
            <textarea
              value={text}
              placeholder="e.g. Add customer region to this table"
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(text);
                }
              }}
              rows={3}
            />
            <button className="btn primary" type="submit" disabled={sending || !text.trim()}>Send</button>
          </form>
        </>
      )}
    </aside>
  );
}
