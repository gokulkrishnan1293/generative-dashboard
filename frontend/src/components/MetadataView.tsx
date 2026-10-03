import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { timeAgo } from "../lib/format";
import { useStore } from "../lib/store";
import type {
  ColumnMeta, ImpactItem, MetadataDoc, MetricMeta, RelationshipMeta, ReviewStatus, TableMeta,
} from "../lib/types";

const STATUSES: ReviewStatus[] = ["draft", "needs_review", "approved", "rejected", "missing"];
const STATUS_LABEL: Record<ReviewStatus, string> = {
  draft: "Draft", needs_review: "Needs review", approved: "Approved", rejected: "Rejected", missing: "Missing",
};
const SEMANTICS = ["", "identifier", "dimension", "measure", "time", "text", "flag"];

function StatusBadge({ status }: { status: ReviewStatus }) {
  return <span className={`status-badge s-${status}`}>{STATUS_LABEL[status]}</span>;
}

function attention(item: { status: ReviewStatus; ambiguities: string[]; schema_change?: string | null }): boolean {
  return item.status === "needs_review" || item.status === "missing" || item.ambiguities.length > 0 || !!item.schema_change;
}

function Ambiguities({ items, onResolve }: { items: string[]; onResolve: (i: number) => void }) {
  if (!items.length) return null;
  return (
    <ul className="ambiguities">
      {items.map((a, i) => (
        <li key={i}>
          <span>⚠ {a}</span>
          <button className="link small" onClick={() => onResolve(i)}>Mark resolved</button>
        </li>
      ))}
    </ul>
  );
}

function StatusSelect({ value, onChange }: { value: ReviewStatus; onChange: (s: ReviewStatus) => void }) {
  return (
    <select className={`status-select s-${value}`} value={value} onChange={(e) => onChange(e.target.value as ReviewStatus)}>
      {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
    </select>
  );
}

function codedToText(c: ColumnMeta): string {
  const keys = new Set([...c.allowed_values, ...Object.keys(c.coded_values)]);
  return [...keys].map((k) => `${k} = ${c.coded_values[k] ?? ""}`).join("\n");
}

function textToCoded(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const [k, ...rest] = line.split("=");
    if (k.trim() && rest.join("=").trim()) out[k.trim()] = rest.join("=").trim();
  }
  return out;
}

function ColumnRow({ col, admin, onChange }: { col: ColumnMeta; admin: boolean; onChange: (c: ColumnMeta) => void }) {
  const [codes, setCodes] = useState(codedToText(col));
  useEffect(() => setCodes(codedToText(col)), [col.coded_values, col.allowed_values]);
  const hasCodes = col.allowed_values.length > 0 || Object.keys(col.coded_values).length > 0;
  return (
    <tr className={attention(col) ? "attention" : ""}>
      <td className="col-name">
        <code>{col.name}</code>
        <div className="muted small">{col.data_type}{col.primary_key ? " · PK" : ""}{col.nullable ? "" : " · required"}</div>
        {col.schema_change && <div className="badge warn small">{col.schema_change}</div>}
      </td>
      <td>
        <textarea rows={2} value={col.description} placeholder="Business meaning (leave empty if unknown)"
          onChange={(e) => onChange({ ...col, description: e.target.value })} />
        {hasCodes && (
          <textarea rows={Math.min(6, Math.max(2, codes.split("\n").length))} className="mono small" value={codes}
            placeholder="code = meaning" onChange={(e) => setCodes(e.target.value)}
            onBlur={() => onChange({ ...col, coded_values: textToCoded(codes) })} />
        )}
        <Ambiguities items={col.ambiguities} onResolve={(i) => onChange({ ...col, ambiguities: col.ambiguities.filter((_, j) => j !== i) })} />
      </td>
      <td>
        <select value={col.semantic_type ?? ""} onChange={(e) => onChange({ ...col, semantic_type: e.target.value || null })}>
          {SEMANTICS.map((s) => <option key={s} value={s}>{s || "—"}</option>)}
        </select>
        <input className="unit" value={col.unit ?? ""} placeholder="unit" onChange={(e) => onChange({ ...col, unit: e.target.value || null })} />
      </td>
      <td className="center">
        <input type="checkbox" checked={col.restricted} disabled={!admin} title={admin ? "Restrict to admins" : "Only admins can change access"}
          onChange={(e) => onChange({ ...col, restricted: e.target.checked })} />
      </td>
      <td>
        <StatusSelect value={col.status} onChange={(s) => onChange({ ...col, status: s })} />
        <div className="muted small">conf. {Math.round(col.confidence * 100)}%</div>
      </td>
    </tr>
  );
}

function TableCard({ table, admin, onlyAttention, onChange }: {
  table: TableMeta; admin: boolean; onlyAttention: boolean; onChange: (t: TableMeta) => void;
}) {
  const [open, setOpen] = useState(attention(table) || table.columns.some(attention));
  const cols = onlyAttention ? table.columns.filter(attention) : table.columns;
  const pending = table.columns.filter((c) => c.status !== "approved" && c.status !== "missing" && c.status !== "rejected").length;
  const approveAll = () => onChange({
    ...table, status: table.status === "missing" ? "missing" : "approved", ambiguities: [], schema_change: null,
    columns: table.columns.map((c) => (c.status === "missing" || c.status === "rejected" ? c : { ...c, status: "approved", ambiguities: [], schema_change: null })),
  });
  return (
    <section className={`meta-card ${attention(table) ? "attention" : ""}`}>
      <header onClick={() => setOpen((o) => !o)}>
        <span className="caret">{open ? "▾" : "▸"}</span>
        <code className="table-name">{table.name}</code>
        <StatusBadge status={table.status} />
        {table.restricted && <span className="badge muted">restricted</span>}
        {table.schema_change && <span className="badge warn">{table.schema_change}</span>}
        <span className="muted small">{table.columns.length} columns{pending ? ` · ${pending} to review` : ""}</span>
        <span className="spacer" />
        <button className="btn small" onClick={(e) => { e.stopPropagation(); approveAll(); }}>Approve table & columns</button>
      </header>
      {open && (
        <div className="meta-card-body">
          <div className="table-fields">
            <label>What it represents
              <textarea rows={2} value={table.description} onChange={(e) => onChange({ ...table, description: e.target.value })} />
            </label>
            <label>One row means
              <input value={table.row_meaning} onChange={(e) => onChange({ ...table, row_meaning: e.target.value })} />
            </label>
            <div className="table-flags">
              <label className="inline"><input type="checkbox" checked={table.restricted} disabled={!admin}
                onChange={(e) => onChange({ ...table, restricted: e.target.checked })} /> Restricted (admin only)</label>
              <StatusSelect value={table.status} onChange={(s) => onChange({ ...table, status: s })} />
              <span className="muted small">confidence {Math.round(table.confidence * 100)}%</span>
            </div>
            <Ambiguities items={table.ambiguities} onResolve={(i) => onChange({ ...table, ambiguities: table.ambiguities.filter((_, j) => j !== i) })} />
          </div>
          {cols.length > 0 && (
            <table className="meta-columns">
              <thead><tr><th>Column</th><th>Meaning</th><th>Type / unit</th><th>Restricted</th><th>Status</th></tr></thead>
              <tbody>
                {cols.map((c) => (
                  <ColumnRow key={c.name} col={c} admin={admin}
                    onChange={(nc) => onChange({ ...table, columns: table.columns.map((x) => (x.name === nc.name ? nc : x)) })} />
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </section>
  );
}

function RelationshipRow({ rel, onChange }: { rel: RelationshipMeta; onChange: (r: RelationshipMeta) => void }) {
  return (
    <tr className={attention(rel) ? "attention" : ""}>
      <td><code>{rel.from_table}.{rel.from_column}</code> → <code>{rel.to_table}.{rel.to_column}</code>
        <div className="muted small">{rel.origin}</div></td>
      <td>
        <select value={rel.cardinality} onChange={(e) => onChange({ ...rel, cardinality: e.target.value as RelationshipMeta["cardinality"] })}>
          <option value="many_to_one">many → one</option>
          <option value="one_to_one">one → one</option>
        </select>
      </td>
      <td>
        <input value={rel.description} placeholder="Meaning of the relationship" onChange={(e) => onChange({ ...rel, description: e.target.value })} />
        <Ambiguities items={rel.ambiguities} onResolve={(i) => onChange({ ...rel, ambiguities: rel.ambiguities.filter((_, j) => j !== i) })} />
      </td>
      <td><StatusSelect value={rel.status} onChange={(s) => onChange({ ...rel, status: s })} /></td>
    </tr>
  );
}

function exprText(e: unknown): string {
  const x = e as { column?: string; literal?: number; op?: string; args?: unknown[] };
  if (x.column) return x.column;
  if (x.literal !== undefined && x.literal !== null) return String(x.literal);
  const sym: Record<string, string> = { add: "+", sub: "−", mul: "×", div: "÷" };
  return `(${exprText(x.args?.[0])} ${sym[x.op ?? ""] ?? x.op} ${exprText(x.args?.[1])})`;
}

function MetricRow({ metric, onChange }: { metric: MetricMeta; onChange: (m: MetricMeta) => void }) {
  return (
    <tr className={attention(metric) ? "attention" : ""}>
      <td><strong>{metric.label}</strong><div><code className="small">{metric.name}</code></div></td>
      <td><code className="small">{metric.agg}{exprText(metric.expr)}</code><div className="muted small">{metric.format}</div></td>
      <td>
        <textarea rows={2} value={metric.description} onChange={(e) => onChange({ ...metric, description: e.target.value })} />
        <Ambiguities items={metric.ambiguities} onResolve={(i) => onChange({ ...metric, ambiguities: metric.ambiguities.filter((_, j) => j !== i) })} />
      </td>
      <td><StatusSelect value={metric.status} onChange={(s) => onChange({ ...metric, status: s })} /></td>
    </tr>
  );
}

function ConnectForm({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [docs, setDocs] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form className="connect-form" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        await api.createSource(name, url, docs);
        onDone();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(false);
      }
    }}>
      <h3>Connect a database</h3>
      <label>Name<input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Warehouse" /></label>
      <label>SQLAlchemy URL<input required value={url} onChange={(e) => setUrl(e.target.value)}
        placeholder="postgresql+psycopg://readonly:pw@host/db or sqlite:////path/file.db" /></label>
      <label>Business documentation (optional)<textarea rows={4} value={docs} onChange={(e) => setDocs(e.target.value)}
        placeholder="Glossary, metric definitions, status meanings…" /></label>
      {error && <div className="error-text">{error}</div>}
      <button className="btn primary" disabled={busy}>{busy ? "Connecting…" : "Connect & discover schema"}</button>
      <p className="muted small">Use a read-only database user. Only schema structure is read during onboarding.</p>
    </form>
  );
}

export function MetadataView() {
  const sources = useStore((s) => s.sources);
  const activeSourceId = useStore((s) => s.activeSourceId);
  const setActive = useStore((s) => s.setActiveSource);
  const refreshSources = useStore((s) => s.refreshSources);
  const reloadCanvas = useStore((s) => s.reloadCanvas);
  const role = useStore((s) => s.role);
  const config = useStore((s) => s.config);
  const [doc, setDoc] = useState<MetadataDoc | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [impact, setImpact] = useState<ImpactItem[]>([]);
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [documentation, setDocumentation] = useState("");
  const source = sources.find((s) => s.id === activeSourceId) ?? null;
  const canEdit = role !== "viewer";
  const admin = role === "admin";

  useEffect(() => {
    if (!activeSourceId) return;
    setDoc(null);
    setDirty(false);
    setNotes([]);
    api.metadata(activeSourceId).then(setDoc).catch((e) => setError(String(e)));
    api.impact(activeSourceId).then(setImpact).catch(() => undefined);
  }, [activeSourceId]);
  useEffect(() => setDocumentation(source?.documentation ?? ""), [source?.id, source?.documentation]);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const update = (next: MetadataDoc) => {
    setDoc(next);
    setDirty(true);
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    if (!doc) return c;
    const items = [...doc.tables, ...doc.tables.flatMap((t) => t.columns), ...doc.relationships, ...doc.metrics];
    for (const i of items) c[i.status] = (c[i.status] ?? 0) + 1;
    c.total = items.length;
    c.attention = items.filter(attention).length;
    return c;
  }, [doc]);

  const sortedTables = useMemo(() => {
    if (!doc) return [];
    const score = (t: TableMeta) => (attention(t) ? 2 : 0) + (t.columns.some(attention) ? 1 : 0);
    const list = [...doc.tables].sort((a, b) => score(b) - score(a) || a.name.localeCompare(b.name));
    return onlyAttention ? list.filter((t) => score(t) > 0) : list;
  }, [doc, onlyAttention]);

  const approveConfident = () => {
    if (!doc) return;
    const ok = <T extends { status: ReviewStatus; ambiguities: string[]; confidence: number }>(x: T): T =>
      x.status === "draft" && !x.ambiguities.length && x.confidence >= 0.8 ? { ...x, status: "approved" } : x;
    update({
      tables: doc.tables.map((t) => ({ ...ok(t), columns: t.columns.map(ok) })),
      relationships: doc.relationships.map(ok),
      metrics: doc.metrics.map(ok),
    });
  };

  return (
    <div className="metadata-view">
      <aside className="source-list">
        <h3>Data sources</h3>
        {sources.map((s) => (
          <button key={s.id} className={`source-item ${s.id === activeSourceId ? "active" : ""}`} onClick={() => { setActive(s.id); setConnecting(false); }}>
            <div>{s.name}</div>
            <div className="muted small">{s.table_count} tables · {s.status_counts.approved ?? 0} approved</div>
          </button>
        ))}
        {admin ? (
          <button className="btn small block" onClick={() => setConnecting(true)}>+ Connect database</button>
        ) : <p className="muted small">Switch to the admin role to connect databases.</p>}
      </aside>

      <main className="metadata-main">
        {connecting ? (
          <ConnectForm onDone={async () => { setConnecting(false); await refreshSources(); }} />
        ) : !source ? (
          <p className="muted pad">No data source selected.</p>
        ) : (
          <>
            <div className="metadata-head">
              <div>
                <h2>{source.name}</h2>
                <div className="muted small">
                  <code>{source.url}</code> · discovered {timeAgo(source.discovered_at)} · drafted {timeAgo(source.drafted_at)}
                </div>
              </div>
              <div className="metadata-actions">
                <button className="btn" disabled={!canEdit || !!busy} title="Re-read schema and flag changes"
                  onClick={() => run("discover", async () => {
                    const r = await api.discover(source.id);
                    setDoc(r.metadata);
                    setImpact(r.impact);
                    setDirty(false);
                    setNotes(r.changes.length ? r.changes : ["No schema changes detected."]);
                    await refreshSources();
                  })}>{busy === "discover" ? "Scanning…" : "Re-scan schema"}</button>
                <button className="btn" disabled={!canEdit || !!busy}
                  title={config?.llm_configured ? "Let the agent draft descriptions for unapproved items" : "No model configured: produces a structure-only draft"}
                  onClick={() => run("draft", async () => {
                    if (dirty && !confirm("Discard unsaved edits and draft with AI?")) return;
                    if (documentation !== source.documentation) await api.updateSource(source.id, { documentation });
                    const r = await api.draft(source.id);
                    setDoc(r.metadata);
                    setDirty(false);
                    setNotes(r.notes.length ? r.notes : ["Draft updated. Items needing attention are listed first."]);
                    await refreshSources();
                  })}>{busy === "draft" ? "Drafting…" : "Draft with AI"}</button>
                {source.is_demo && (
                  <button className="btn" disabled={!canEdit || !!busy} title="Apply the reviewed metadata bundled with the demo database"
                    onClick={() => run("demo", async () => {
                      const r = await api.loadDemoMetadata(source.id);
                      setDoc(r.metadata);
                      setDirty(false);
                      setNotes(["Loaded reviewed demo metadata. All demo tables are approved."]);
                      await refreshSources();
                      await reloadCanvas();
                    })}>Use reviewed demo metadata</button>
                )}
                <button className="btn primary" disabled={!canEdit || !dirty || !!busy}
                  onClick={() => run("save", async () => {
                    if (!doc) return;
                    if (documentation !== source.documentation) await api.updateSource(source.id, { documentation });
                    const r = await api.saveMetadata(source.id, doc);
                    setDoc(r.metadata);
                    setImpact(r.impact);
                    setDirty(false);
                    setNotes(["Saved. Only approved items are used for dashboard generation."]);
                    await refreshSources();
                    await reloadCanvas();
                  })}>{busy === "save" ? "Saving…" : dirty ? "Save review" : "Saved"}</button>
              </div>
            </div>

            {!canEdit && <div className="notice">Viewers can read metadata. Switch to analyst or admin to review.</div>}
            {error && <div className="notice error">{error}</div>}
            {notes.length > 0 && <div className="notice info"><ul>{notes.map((n, i) => <li key={i}>{n}</li>)}</ul></div>}
            {impact.length > 0 && (
              <div className="notice warn">
                <strong>{impact.length} saved widget(s) depend on definitions that changed or are not approved:</strong>
                <ul>{impact.map((i) => <li key={i.widget_id}>{i.dashboard} › {i.widget}: {i.issues.join("; ")}</li>)}</ul>
              </div>
            )}

            <details className="docs-box">
              <summary>Business documentation used for drafting</summary>
              <textarea rows={6} value={documentation} disabled={!canEdit} onChange={(e) => { setDocumentation(e.target.value); setDirty(true); }} />
            </details>

            {doc && (
              <>
                <div className="review-bar">
                  <span><strong>{counts.approved ?? 0}</strong> / {counts.total} approved</span>
                  <span className="muted">· {counts.attention ?? 0} need attention · {counts.draft ?? 0} drafts</span>
                  <div className="progress"><div style={{ width: `${((counts.approved ?? 0) / Math.max(1, counts.total)) * 100}%` }} /></div>
                  <label className="inline"><input type="checkbox" checked={onlyAttention} onChange={(e) => setOnlyAttention(e.target.checked)} /> Only items needing attention</label>
                  <button className="btn small" disabled={!canEdit} onClick={approveConfident}
                    title="Approve drafts with ≥80% confidence and no open questions">Approve confident drafts</button>
                </div>

                {sortedTables.map((t) => (
                  <TableCard key={t.name} table={t} admin={admin} onlyAttention={onlyAttention}
                    onChange={(nt) => update({ ...doc, tables: doc.tables.map((x) => (x.name === nt.name ? nt : x)) })} />
                ))}

                <section className="meta-card">
                  <header><code className="table-name">Relationships</code><span className="muted small">Joins the agent may use. Only approved relationships are used.</span></header>
                  <div className="meta-card-body">
                    <table className="meta-columns">
                      <thead><tr><th>Join</th><th>Cardinality</th><th>Meaning</th><th>Status</th></tr></thead>
                      <tbody>
                        {doc.relationships.filter((r) => !onlyAttention || attention(r)).map((r) => (
                          <RelationshipRow key={r.id} rel={r}
                            onChange={(nr) => update({ ...doc, relationships: doc.relationships.map((x) => (x.id === nr.id ? nr : x)) })} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>

                <section className="meta-card">
                  <header><code className="table-name">Business metrics</code><span className="muted small">Reusable calculations.</span></header>
                  <div className="meta-card-body">
                    {doc.metrics.length === 0 && <p className="muted small pad">No metrics yet. Add definitions to the documentation and draft with AI.</p>}
                    {doc.metrics.length > 0 && (
                      <table className="meta-columns">
                        <thead><tr><th>Metric</th><th>Calculation</th><th>Description</th><th>Status</th></tr></thead>
                        <tbody>
                          {doc.metrics.filter((m) => !onlyAttention || attention(m)).map((m) => (
                            <MetricRow key={m.name} metric={m}
                              onChange={(nm) => update({ ...doc, metrics: doc.metrics.map((x) => (x.name === nm.name ? nm : x)) })} />
                          ))}
                        </tbody>
                      </table>
                    )}
                  </div>
                </section>
              </>
            )}
          </>
        )}
      </main>
    </div>
  );
}
