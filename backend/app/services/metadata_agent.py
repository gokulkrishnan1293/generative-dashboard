"""Drafts the business metadata wrapper (FR-02) from schema structure and documentation.

The agent sees table/column names, types, keys, constraints and the documentation an
administrator supplied. It never sees rows.
"""

from __future__ import annotations

import json
import re

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..schemas import Expr, MetadataDoc, MetricMeta, RelationshipMeta
from .introspect import relationship_id
from .llm import JSONCompleter, audited_call

SYSTEM = """You draft a business metadata wrapper for a relational database so that analysts can
review it and a dashboard agent can later use it. You receive ONLY schema structure (names,
types, keys, constraints, comments) and optional business documentation. You never see data.

Rules:
- Describe what each table represents and what one row means.
- Describe each column's business meaning, unit (e.g. USD, percent as fraction 0-1, days) and,
  for columns with allowed values, the meaning of each code.
- Only state meanings supported by names, constraints, comments or documentation. When a
  meaning is a guess, say so: lower the confidence and add a concrete question to
  "ambiguities". Never present a guess as fact. Leave descriptions empty rather than invent.
- semantic_type is one of identifier, dimension, measure, time, text, flag.
- Suggest restricted=true for personal or confidential data (salary, compensation, SSN, email...).
- Propose relationships not declared as foreign keys only when names strongly imply them
  (cardinality many_to_one from the referencing table). Add descriptions for declared ones.
- Propose business metrics ONLY when documentation defines them or they are unambiguous counts
  or sums. A metric is {"name": snake_case, "label", "description", "agg": sum|avg|min|max|count|count_distinct,
  "expr": E, "format": number|integer|currency|percent}, where E is {"column": "table.column"} |
  {"literal": number} | {"op": "add"|"sub"|"mul"|"div", "args": [E, E]}. All columns of one
  metric must come from tables joined many-to-one from the most granular table in it.
- confidence is 0..1.

Return one JSON object:
{"tables": [{"name", "description", "row_meaning", "confidence", "ambiguities": [], "restricted": false,
   "columns": [{"name", "description", "unit", "semantic_type", "coded_values": {"code": "meaning"},
                "confidence", "ambiguities": [], "restricted": false}]}],
 "relationships": [{"from_table", "from_column", "to_table", "to_column", "cardinality", "description",
                    "confidence", "ambiguities": []}],
 "metrics": [ ... ]}
"""


def _schema_for_prompt(doc: MetadataDoc, only_unapproved: bool) -> dict:
    tables = []
    for t in doc.tables:
        if t.status == "missing":
            continue
        cols = [
            {k: v for k, v in {
                "name": c.name, "type": c.data_type, "nullable": c.nullable, "primary_key": c.primary_key,
                "allowed_values": c.allowed_values or None,
                "existing_description": c.description or None if c.status != "approved" else None,
                "approved": c.status == "approved" or None,
            }.items() if v is not None}
            for c in t.columns if c.status != "missing"
        ]
        if only_unapproved and t.status == "approved" and all(c.status == "approved" for c in t.columns):
            continue
        tables.append({"name": t.name, "approved": t.status == "approved", "columns": cols})
    rels = [
        {"from": f"{r.from_table}.{r.from_column}", "to": f"{r.to_table}.{r.to_column}",
         "origin": r.origin, "cardinality": r.cardinality}
        for r in doc.relationships if r.status != "missing"
    ]
    return {"tables": tables, "declared_relationships": rels, "existing_metrics": [m.name for m in doc.metrics]}


def _status(confidence: float, ambiguities: list[str]) -> str:
    return "draft" if confidence >= 0.8 and not ambiguities else "needs_review"


def _f(v, default=0.0) -> float:
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def apply_draft(doc: MetadataDoc, draft: dict, overwrite: bool = False) -> list[str]:
    """Merge an agent draft into the wrapper. Approved items are never changed unless overwrite."""
    notes: list[str] = []
    for td in draft.get("tables") or []:
        t = doc.table(str(td.get("name")))
        if t is None:
            continue
        if overwrite or t.status not in ("approved", "rejected"):
            t.description = td.get("description") or t.description
            t.row_meaning = td.get("row_meaning") or t.row_meaning
            t.confidence = _f(td.get("confidence"))
            t.ambiguities = [str(a) for a in td.get("ambiguities") or []]
            t.restricted = bool(td.get("restricted", t.restricted))
            if t.status != "missing":
                t.status = _status(t.confidence, t.ambiguities)  # type: ignore[assignment]
        for cd in td.get("columns") or []:
            c = t.column(str(cd.get("name")))
            if c is None or (c.status in ("approved", "rejected", "missing") and not overwrite):
                continue
            c.description = cd.get("description") or c.description
            c.unit = cd.get("unit") or c.unit
            st = cd.get("semantic_type")
            c.semantic_type = st if st in ("identifier", "dimension", "measure", "time", "text", "flag") else c.semantic_type
            coded = cd.get("coded_values") or {}
            if isinstance(coded, dict):
                c.coded_values = {str(k): str(v) for k, v in coded.items()}
            c.confidence = _f(cd.get("confidence"))
            c.ambiguities = [str(a) for a in cd.get("ambiguities") or []]
            missing_codes = [v for v in c.allowed_values if v not in c.coded_values]
            if missing_codes:
                c.ambiguities.append(f"Meaning of codes not documented: {', '.join(missing_codes)}")
            c.restricted = bool(cd.get("restricted", c.restricted))
            if c.status != "missing":
                c.status = _status(c.confidence, c.ambiguities)  # type: ignore[assignment]

    rels = {r.id: r for r in doc.relationships}
    for rd in draft.get("relationships") or []:
        try:
            rid = relationship_id(rd["from_table"], rd["from_column"], rd["to_table"], rd["to_column"])
        except KeyError:
            continue
        existing = rels.get(rid)
        if existing is not None:
            if existing.status not in ("approved", "rejected", "missing") or overwrite:
                existing.description = rd.get("description") or existing.description
                existing.ambiguities = [str(a) for a in rd.get("ambiguities") or []]
                existing.confidence = max(existing.confidence, _f(rd.get("confidence")))
                existing.status = _status(existing.confidence, existing.ambiguities)  # type: ignore[assignment]
            continue
        ft, tt = doc.table(rd["from_table"]), doc.table(rd["to_table"])
        if not ft or not tt or not ft.column(rd["from_column"]) or not tt.column(rd["to_column"]):
            notes.append(f"ignored relationship to unknown columns: {rid}")
            continue
        rel = RelationshipMeta(
            id=rid, from_table=rd["from_table"], from_column=rd["from_column"], to_table=rd["to_table"],
            to_column=rd["to_column"],
            cardinality="one_to_one" if rd.get("cardinality") == "one_to_one" else "many_to_one",
            origin="inferred", description=rd.get("description") or "", confidence=_f(rd.get("confidence")),
            ambiguities=[str(a) for a in rd.get("ambiguities") or []] or ["Inferred from naming; not declared as a foreign key."],
            status="needs_review",
        )
        doc.relationships.append(rel)
        rels[rid] = rel

    metrics = {m.name: m for m in doc.metrics}
    for md in draft.get("metrics") or []:
        try:
            name = re.sub(r"[^a-z0-9_]", "_", str(md["name"]).lower())
            existing = metrics.get(name)
            if existing is not None and existing.status in ("approved", "rejected") and not overwrite:
                continue
            metric = MetricMeta(
                name=name, label=md.get("label") or name.replace("_", " ").title(),
                description=md.get("description") or "", agg=md["agg"], expr=Expr.model_validate(md["expr"]),
                format=md.get("format") if md.get("format") in ("number", "integer", "currency", "percent") else "number",
                confidence=_f(md.get("confidence")), ambiguities=[str(a) for a in md.get("ambiguities") or []],
            )
        except (KeyError, ValidationError, TypeError) as exc:
            notes.append(f"ignored invalid metric proposal {md.get('name')!r}: {exc.__class__.__name__}")
            continue
        unknown = [c for c in metric.expr.columns() if not _column_exists(doc, c)]
        if unknown:
            notes.append(f"ignored metric '{name}' referencing unknown columns {unknown}")
            continue
        metric.status = _status(metric.confidence, metric.ambiguities)  # type: ignore[assignment]
        if existing is not None:
            doc.metrics[doc.metrics.index(existing)] = metric
        else:
            doc.metrics.append(metric)
        metrics[name] = metric
    return notes


def _column_exists(doc: MetadataDoc, ref: str) -> bool:
    if ref.count(".") != 1:
        return False
    t, c = ref.split(".")
    table = doc.table(t)
    return bool(table and table.column(c))


def draft_with_llm(db: Session, llm: JSONCompleter, doc: MetadataDoc, documentation: str, overwrite: bool) -> list[str]:
    user = json.dumps({
        "schema": _schema_for_prompt(doc, only_unapproved=not overwrite),
        "documentation": documentation or "(none provided)",
    }, indent=1)
    draft = audited_call(db, llm, "metadata_draft", SYSTEM, user)
    return apply_draft(doc, draft, overwrite=overwrite)


_SENSITIVE = re.compile(r"salary|compensation|ssn|social_security|password|email|phone|birth", re.I)


def heuristic_draft(doc: MetadataDoc) -> list[str]:
    """Fallback when no model is configured: structure-only typing, everything left for review."""
    for t in doc.tables:
        if t.status in ("approved", "rejected", "missing"):
            continue
        t.status = "needs_review"
        t.restricted = t.restricted or bool(_SENSITIVE.search(t.name))
        if not t.ambiguities:
            t.ambiguities = ["No AI draft available: describe what this table and one row represent."]
        for c in t.columns:
            if c.status in ("approved", "rejected", "missing"):
                continue
            dt = c.data_type.upper()
            name = c.name.lower()
            if c.primary_key or name == "id" or name.endswith("_id"):
                c.semantic_type = "identifier"
            elif "DATE" in dt or "TIME" in dt or name.endswith(("_at", "_on", "_date")):
                c.semantic_type = "time"
            elif any(k in dt for k in ("INT", "NUM", "DEC", "REAL", "FLOAT", "DOUBLE")):
                c.semantic_type = "measure"
            else:
                c.semantic_type = "dimension"
            c.restricted = c.restricted or bool(_SENSITIVE.search(c.name))
            c.status = "needs_review"
            c.ambiguities = c.ambiguities or ["No AI draft available: business meaning needs a description."]
    for r in doc.relationships:
        if r.status == "draft":
            r.status = "needs_review"
    return ["OPENAI_API_KEY not configured: produced a structure-only draft for manual review."]
