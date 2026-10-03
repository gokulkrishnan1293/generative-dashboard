import type { ValueFormat } from "./types";

const compact = new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 });

export function formatValue(v: unknown, format?: ValueFormat | null, opts: { compact?: boolean } = {}): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v !== "number" || format === "text" || format === "date") return String(v);
  switch (format) {
    case "currency":
      return opts.compact && Math.abs(v) >= 10000
        ? `$${compact.format(v)}`
        : v.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: Math.abs(v) >= 1000 ? 0 : 2 });
    case "percent":
      return `${(v * 100).toLocaleString(undefined, { maximumFractionDigits: 1 })}%`;
    case "integer":
      return opts.compact && Math.abs(v) >= 10000 ? compact.format(v) : Math.round(v).toLocaleString();
    default:
      if (opts.compact && Math.abs(v) >= 10000) return compact.format(v);
      return v.toLocaleString(undefined, { maximumFractionDigits: Number.isInteger(v) ? 0 : 2 });
  }
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleString();
}

export function describeFilter(f: { field: string; op: string; value?: unknown }): string {
  const ops: Record<string, string> = {
    eq: "=", neq: "≠", gt: ">", gte: "≥", lt: "<", lte: "≤", in: "in", not_in: "not in", between: "between",
    contains: "contains", is_null: "is empty", not_null: "is not empty", in_last_days: "in last",
  };
  const v = Array.isArray(f.value) ? f.value.join(", ") : f.value;
  const suffix = f.op === "in_last_days" ? `${v} days` : v ?? "";
  return `${f.field.split(".").pop()} ${ops[f.op] ?? f.op} ${suffix}`.trim();
}
