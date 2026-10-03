import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { formatValue } from "../lib/format";
import { MAX_SERIES, OTHER_COLOR, type ChartTheme } from "../lib/theme";
import type { Presentation, QueryResult, ValueFormat, Widget } from "../lib/types";

interface Props {
  widget: Widget;
  result: QueryResult;
  theme: ChartTheme;
  asTable?: boolean;
}

function titleCase(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function makeLabeler(p: Presentation, result: QueryResult) {
  const cols = Object.fromEntries(result.columns.map((c) => [c.key, c]));
  return {
    label: (k: string) => p.labels?.[k] ?? titleCase(k),
    format: (k: string): ValueFormat | null =>
      p.formats?.[k] ?? cols[k]?.format ?? (cols[k]?.kind === "measure" ? "number" : "text"),
  };
}

export function WidgetBody({ widget, result, theme, asTable }: Props) {
  if (asTable || widget.type === "table") return <DataTable widget={widget} result={result} />;
  if (widget.type === "kpi") return <Kpi widget={widget} result={result} />;
  if (widget.type === "pie") return <PieView widget={widget} result={result} theme={theme} />;
  return <Cartesian widget={widget} result={result} theme={theme} />;
}

function DataTable({ widget, result }: { widget: Widget; result: QueryResult }) {
  const { label, format } = makeLabeler(widget.presentation, result);
  const all = result.columns.map((c) => c.key);
  const order = (widget.presentation.columns ?? []).filter((k) => all.includes(k));
  const keys = [...order, ...all.filter((k) => !order.includes(k))];
  const numeric = new Set(result.columns.filter((c) => c.kind === "measure").map((c) => c.key));
  return (
    <div className="table-wrap" data-scrollable>
      <table className="data-table">
        <thead>
          <tr>{keys.map((k) => <th key={k} className={numeric.has(k) ? "num" : ""}>{label(k)}</th>)}</tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i}>
              {keys.map((k) => (
                <td key={k} className={numeric.has(k) ? "num" : ""}>{formatValue(row[k], format(k))}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Kpi({ widget, result }: { widget: Widget; result: QueryResult }) {
  const { label, format } = makeLabeler(widget.presentation, result);
  const keys = widget.presentation.y?.length ? widget.presentation.y : result.columns.filter((c) => c.kind === "measure").map((c) => c.key);
  const row = result.rows[0] ?? {};
  return (
    <div className="kpi">
      {keys.map((k) => (
        <div key={k} className="kpi-item">
          <div className="kpi-value">{formatValue(row[k], format(k), { compact: true })}</div>
          {keys.length > 1 && <div className="kpi-label">{label(k)}</div>}
        </div>
      ))}
    </div>
  );
}

interface Series {
  key: string;
  name: string;
  color: string;
}

/** Pivot long rows into one row per x with a column per series value; fold the tail into "Other". */
function pivot(rows: Record<string, unknown>[], x: string, seriesKey: string, y: string, theme: ChartTheme) {
  const totals = new Map<string, number>();
  for (const r of rows) {
    const s = String(r[seriesKey] ?? "—");
    totals.set(s, (totals.get(s) ?? 0) + (Number(r[y]) || 0));
  }
  const ranked = [...totals.entries()].sort((a, b) => b[1] - a[1]).map(([k]) => k);
  const keep = ranked.length > MAX_SERIES ? ranked.slice(0, MAX_SERIES - 1) : ranked;
  // Color follows the entity: assign slots by name, not by rank.
  const byName = [...keep].sort();
  const series: Series[] = keep.map((k) => ({ key: `s:${k}`, name: k, color: theme.series[byName.indexOf(k)] }));
  const folded = ranked.length > keep.length;
  if (folded) series.push({ key: "s:__other", name: "Other", color: OTHER_COLOR[theme.mode] });
  const map = new Map<string, Record<string, unknown>>();
  for (const r of rows) {
    const xv = String(r[x] ?? "—");
    const entry = map.get(xv) ?? { [x]: xv };
    const s = String(r[seriesKey] ?? "—");
    const key = keep.includes(s) ? `s:${s}` : "s:__other";
    entry[key] = ((entry[key] as number) ?? 0) + (Number(r[y]) || 0);
    map.set(xv, entry);
  }
  return { data: [...map.values()], series };
}

/** Legend text wears ink tokens; the colored marker carries identity. */
function legendText(theme: ChartTheme) {
  return (value: string) => <span style={{ color: theme.inkSecondary }}>{value}</span>;
}

function tooltipStyle(theme: ChartTheme) {
  return {
    contentStyle: {
      background: theme.surface, border: `1px solid ${theme.grid}`, borderRadius: 8, fontSize: 12, color: theme.ink,
      boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
    },
    labelStyle: { color: theme.inkSecondary, marginBottom: 4 },
    itemStyle: { color: theme.ink, padding: 0 },
    cursor: { stroke: theme.axis, strokeWidth: 1, fill: theme.mode === "light" ? "rgba(11,11,11,0.04)" : "rgba(255,255,255,0.05)" },
  };
}

function Cartesian({ widget, result, theme }: { widget: Widget; result: QueryResult; theme: ChartTheme }) {
  const p = widget.presentation;
  const { label, format } = makeLabeler(p, result);
  const dims = result.columns.filter((c) => c.kind === "dimension").map((c) => c.key);
  const measures = result.columns.filter((c) => c.kind === "measure").map((c) => c.key);
  const x = p.x && dims.includes(p.x) ? p.x : dims[0];
  const ys = (p.y?.length ? p.y : measures).filter((k) => measures.includes(k));
  if (!x || !ys.length) return <div className="widget-note">This chart needs a dimension and a measure. Showing nothing.</div>;

  const seriesKey = p.series && dims.includes(p.series) && p.series !== x ? p.series : null;
  // One axis only: measures with different formats are drawn as small multiples, never dual-axis.
  const formats = new Set(ys.map((k) => format(k)));
  if (!seriesKey && ys.length > 1 && formats.size > 1) {
    return (
      <div className="multiples">
        {ys.map((k) => (
          <div key={k} className="multiple">
            <div className="multiple-title">{label(k)}</div>
            <div className="multiple-chart">
              <Cartesian widget={{ ...widget, presentation: { ...p, y: [k] } }} result={result} theme={theme} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  let data: Record<string, unknown>[] = result.rows;
  let series: Series[];
  let valueFormat = format(ys[0]);
  if (seriesKey) {
    const pv = pivot(result.rows, x, seriesKey, ys[0], theme);
    data = pv.data;
    series = pv.series;
  } else {
    series = ys.slice(0, MAX_SERIES).map((k, i) => ({ key: k, name: label(k), color: theme.series[i] }));
  }
  valueFormat = valueFormat ?? "number";
  const horizontal = widget.type === "bar" && p.horizontal;
  const stacked = p.stacked || (widget.type === "area" && series.length > 1 && !!seriesKey);
  const axisProps = { stroke: theme.axis, tick: { fill: theme.muted, fontSize: 11 }, tickLine: false };
  const valueAxis = {
    ...axisProps, axisLine: false, width: 64,
    tickFormatter: (v: number) => formatValue(v, valueFormat, { compact: true }),
  };
  const catAxis = { ...axisProps, dataKey: x, minTickGap: 12 };
  const tt = tooltipStyle(theme);
  const tooltip = (
    <Tooltip
      {...tt}
      formatter={(v: number, name: string) => [formatValue(v, valueFormat), name]}
    />
  );
  const legend = series.length > 1 ? (
    <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 11 }} formatter={legendText(theme)} />
  ) : null;
  const grid = <CartesianGrid stroke={theme.grid} vertical={false} horizontal={!horizontal} />;
  const margin = { top: 8, right: 12, bottom: 0, left: 0 };

  let chart;
  if (widget.type === "bar") {
    chart = (
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={margin} barGap={2} barCategoryGap="20%">
        {horizontal ? <CartesianGrid stroke={theme.grid} horizontal={false} /> : grid}
        {horizontal ? <XAxis type="number" {...valueAxis} /> : <XAxis {...catAxis} />}
        {horizontal ? <YAxis type="category" {...catAxis} width={110} /> : <YAxis {...valueAxis} />}
        {tooltip}
        {legend}
        {series.map((s, i) => {
          const top = !stacked || i === series.length - 1;
          const radius: [number, number, number, number] = !top ? [0, 0, 0, 0] : horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0];
          return (
            <Bar key={s.key} dataKey={s.key} name={s.name} fill={s.color} stackId={stacked ? "a" : undefined}
              radius={radius} stroke={stacked ? theme.surface : undefined} strokeWidth={stacked ? 2 : 0}
              maxBarSize={48} isAnimationActive={false} />
          );
        })}
      </BarChart>
    );
  } else if (widget.type === "area") {
    chart = (
      <AreaChart data={data} margin={margin}>
        {grid}
        <XAxis {...catAxis} />
        <YAxis {...valueAxis} />
        {tooltip}
        {legend}
        {series.map((s) => (
          <Area key={s.key} dataKey={s.key} name={s.name} stroke={s.color} fill={s.color} fillOpacity={0.18}
            strokeWidth={2} stackId={stacked ? "a" : undefined} type="monotone" dot={false}
            activeDot={{ r: 4, stroke: theme.surface, strokeWidth: 2 }} isAnimationActive={false} />
        ))}
      </AreaChart>
    );
  } else {
    chart = (
      <LineChart data={data} margin={margin}>
        {grid}
        <XAxis {...catAxis} />
        <YAxis {...valueAxis} />
        {tooltip}
        {legend}
        {series.map((s) => (
          <Line key={s.key} dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2} type="monotone"
            dot={data.length <= 2 ? { r: 4 } : false} activeDot={{ r: 4, stroke: theme.surface, strokeWidth: 2 }}
            isAnimationActive={false} connectNulls />
        ))}
      </LineChart>
    );
  }
  return (
    <ResponsiveContainer width="100%" height="100%">
      {chart}
    </ResponsiveContainer>
  );
}

function PieView({ widget, result, theme }: { widget: Widget; result: QueryResult; theme: ChartTheme }) {
  const p = widget.presentation;
  const { format } = makeLabeler(p, result);
  const dims = result.columns.filter((c) => c.kind === "dimension").map((c) => c.key);
  const measures = result.columns.filter((c) => c.kind === "measure").map((c) => c.key);
  const x = p.x && dims.includes(p.x) ? p.x : dims[0];
  const y = p.y?.[0] && measures.includes(p.y[0]) ? p.y[0] : measures[0];
  if (!x || !y) return <div className="widget-note">A pie needs one dimension and one measure.</div>;
  const sorted = [...result.rows].sort((a, b) => (Number(b[y]) || 0) - (Number(a[y]) || 0));
  const keep = sorted.length > MAX_SERIES ? sorted.slice(0, MAX_SERIES - 1) : sorted;
  const rest = sorted.slice(keep.length);
  const names = keep.map((r) => String(r[x] ?? "—"));
  const byName = [...names].sort();
  const data = keep.map((r, i) => ({ name: names[i], value: Number(r[y]) || 0, color: theme.series[byName.indexOf(names[i])] }));
  if (rest.length) {
    data.push({ name: "Other", value: rest.reduce((s, r) => s + (Number(r[y]) || 0), 0), color: OTHER_COLOR[theme.mode] });
  }
  const tt = tooltipStyle(theme);
  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" paddingAngle={0}
          stroke={theme.surface} strokeWidth={2} isAnimationActive={false}>
          {data.map((d) => <Cell key={d.name} fill={d.color} />)}
        </Pie>
        <Tooltip {...tt} formatter={(v: number, name: string) => [formatValue(v, format(y)), name]} />
        <Legend iconType="circle" iconSize={8} layout="vertical" align="right" verticalAlign="middle"
          wrapperStyle={{ fontSize: 11 }} formatter={legendText(theme)} />
      </PieChart>
    </ResponsiveContainer>
  );
}
