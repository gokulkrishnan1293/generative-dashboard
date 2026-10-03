import { useEffect, useRef, useState } from "react";
import { describeFilter } from "../lib/format";
import type { Filter } from "../lib/types";

const NO_VALUE = ["is_null", "not_null"];

function toText(f: Filter): string {
  return Array.isArray(f.value) ? f.value.join(", ") : f.value === undefined || f.value === null ? "" : String(f.value);
}

function fromText(f: Filter, text: string): unknown {
  if (["in", "not_in", "between"].includes(f.op)) {
    return text.split(",").map((s) => coerce(s.trim(), Array.isArray(f.value) ? f.value[0] : undefined)).filter((s) => s !== "");
  }
  return coerce(text.trim(), f.value);
}

function coerce(text: string, like: unknown): unknown {
  if (typeof like === "number" && text !== "" && !Number.isNaN(Number(text))) return Number(text);
  return text;
}

/** Edits an existing filter's value directly; no agent round-trip needed. */
export function FilterChip({ filter, onChange, onRemove, disabled }: {
  filter: Filter;
  onChange: (f: Filter) => Promise<void> | void;
  onRemove?: () => void;
  disabled?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(toText(filter));
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (editing) ref.current?.focus();
  }, [editing]);

  const commit = async () => {
    try {
      await onChange({ ...filter, value: fromText(filter, text) });
      setEditing(false);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  if (editing && !NO_VALUE.includes(filter.op)) {
    return (
      <span className="chip chip-editing" onPointerDown={(e) => e.stopPropagation()}>
        <span className="chip-field">{describeFilter({ ...filter, value: "" })}</span>
        <input
          ref={ref}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") setEditing(false);
          }}
          title={error ?? "Enter to apply, Esc to cancel. Separate list values with commas."}
          className={error ? "invalid" : ""}
        />
        <button className="chip-btn" onClick={commit} title="Apply">✓</button>
      </span>
    );
  }
  return (
    <span className="chip" title={`${filter.field} — click to edit`} onPointerDown={(e) => e.stopPropagation()}>
      <button className="chip-label" disabled={disabled} onClick={() => { setText(toText(filter)); setEditing(true); }}>
        {describeFilter(filter)}
      </button>
      {onRemove && !disabled && <button className="chip-btn" onClick={onRemove} title="Remove filter">×</button>}
    </span>
  );
}
