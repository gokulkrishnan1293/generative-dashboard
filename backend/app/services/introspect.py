"""Schema discovery (FR-01) and merging into the metadata wrapper with change detection."""

import re
from dataclasses import dataclass, field

from sqlalchemy import inspect

from ..schemas import ColumnMeta, MetadataDoc, RelationshipMeta, TableMeta
from .sources import get_engine

_IN_LIST = re.compile(r"""["`\[]?(\w+)["`\]]?\s+IN\s*\(([^)]*)\)""", re.IGNORECASE)


@dataclass
class DiscoveredColumn:
    name: str
    data_type: str
    nullable: bool
    primary_key: bool
    comment: str | None = None
    allowed_values: list[str] = field(default_factory=list)


@dataclass
class DiscoveredTable:
    name: str
    comment: str | None
    columns: list[DiscoveredColumn]
    foreign_keys: list[tuple[str, str, str]]  # (column, referred_table, referred_column)


def discover_schema(url: str) -> list[DiscoveredTable]:
    """Reads structure only: names, types, keys, constraints, comments. Never rows."""
    insp = inspect(get_engine(url))
    tables: list[DiscoveredTable] = []
    for table_name in sorted(insp.get_table_names()):
        if table_name.startswith("sqlite_"):
            continue
        pk_cols = set(insp.get_pk_constraint(table_name).get("constrained_columns") or [])
        allowed: dict[str, list[str]] = {}
        try:
            for check in insp.get_check_constraints(table_name):
                for col, values in _IN_LIST.findall(check.get("sqltext") or ""):
                    allowed[col] = [v.strip().strip("'\"") for v in values.split(",") if v.strip()]
        except NotImplementedError:
            pass
        columns = [
            DiscoveredColumn(
                name=c["name"],
                data_type=str(c["type"]),
                nullable=bool(c.get("nullable", True)),
                primary_key=c["name"] in pk_cols,
                comment=c.get("comment"),
                allowed_values=allowed.get(c["name"], []),
            )
            for c in insp.get_columns(table_name)
        ]
        fks = []
        for fk in insp.get_foreign_keys(table_name):
            for local, remote in zip(fk["constrained_columns"], fk["referred_columns"]):
                fks.append((local, fk["referred_table"], remote))
        try:
            comment = (insp.get_table_comment(table_name) or {}).get("text")
        except NotImplementedError:
            comment = None
        tables.append(DiscoveredTable(table_name, comment, columns, fks))
    return tables


def relationship_id(from_table: str, from_column: str, to_table: str, to_column: str) -> str:
    return f"{from_table}.{from_column}->{to_table}.{to_column}"


def merge_discovery(doc: MetadataDoc, discovered: list[DiscoveredTable]) -> tuple[MetadataDoc, list[str]]:
    """Merge discovered structure into the wrapper. Reviewed meaning is kept; anything whose
    structure changed is sent back for review so dependent definitions can be assessed."""
    first_run = not doc.tables
    changes: list[str] = []
    seen_tables = set()
    tables_by_name = {t.name: t for t in doc.tables}

    for dt in discovered:
        seen_tables.add(dt.name)
        tm = tables_by_name.get(dt.name)
        table_is_new = tm is None
        if tm is None:
            tm = TableMeta(name=dt.name, description=dt.comment or "", schema_change=None if first_run else "added")
            doc.tables.append(tm)
            tables_by_name[dt.name] = tm
            if not first_run:
                changes.append(f"table added: {dt.name}")
        elif tm.status == "missing":
            tm.status, tm.schema_change = "needs_review", "reappeared"
            changes.append(f"table reappeared: {dt.name}")

        seen_cols = set()
        for dc in dt.columns:
            seen_cols.add(dc.name)
            cm = tm.column(dc.name)
            if cm is None:
                flag_added = not first_run and not table_is_new
                tm.columns.append(ColumnMeta(
                    name=dc.name, data_type=dc.data_type, nullable=dc.nullable, primary_key=dc.primary_key,
                    description=dc.comment or "", allowed_values=dc.allowed_values,
                    schema_change="added" if flag_added else None,
                ))
                if flag_added:
                    changes.append(f"column added: {dt.name}.{dc.name}")
                continue
            notes = []
            if cm.data_type and cm.data_type != dc.data_type:
                notes.append(f"type changed: {cm.data_type} -> {dc.data_type}")
            if sorted(cm.allowed_values) != sorted(dc.allowed_values):
                notes.append("allowed values changed")
            if cm.status == "missing":
                notes.append("reappeared")
            cm.data_type, cm.nullable, cm.primary_key = dc.data_type, dc.nullable, dc.primary_key
            cm.allowed_values = dc.allowed_values
            if notes:
                cm.schema_change = "; ".join(notes)
                if cm.status in ("approved", "missing"):
                    cm.status = "needs_review"
                changes.append(f"column changed: {dt.name}.{dc.name} ({cm.schema_change})")
        for cm in tm.columns:
            if cm.name not in seen_cols and cm.status != "missing":
                cm.status, cm.schema_change = "missing", "removed from source"
                changes.append(f"column removed: {dt.name}.{cm.name}")

    for tm in doc.tables:
        if tm.name not in seen_tables and tm.status != "missing":
            tm.status, tm.schema_change = "missing", "removed from source"
            changes.append(f"table removed: {tm.name}")

    declared = set()
    rels_by_id = {r.id: r for r in doc.relationships}
    for dt in discovered:
        pk_cols = {c.name for c in dt.columns if c.primary_key}
        for local, remote_table, remote_col in dt.foreign_keys:
            rid = relationship_id(dt.name, local, remote_table, remote_col)
            declared.add(rid)
            if rid not in rels_by_id:
                rel = RelationshipMeta(
                    id=rid, from_table=dt.name, from_column=local, to_table=remote_table, to_column=remote_col,
                    cardinality="one_to_one" if pk_cols == {local} else "many_to_one",
                    origin="declared", confidence=0.9,
                )
                doc.relationships.append(rel)
                rels_by_id[rid] = rel
                if not first_run:
                    changes.append(f"relationship added: {rid}")
    for rel in doc.relationships:
        if rel.origin == "declared" and rel.id not in declared and rel.status != "missing":
            rel.status = "missing"
            changes.append(f"relationship removed: {rel.id}")

    return doc, changes
