"""Persistent application state.

Business data never lives here: only data-source configuration, the reviewed
metadata wrapper, dashboard/widget definitions, change history and agent audit.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    url: Mapped[str] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Business documentation the drafting agent may use (glossary, metric definitions).
    documentation: Mapped[str] = mapped_column(Text, default="")
    # The business metadata wrapper (see schemas.MetadataDoc).
    metadata_doc: Mapped[dict] = mapped_column(JSON, default=dict)
    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drafted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Dashboard(Base):
    __tablename__ = "dashboards"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    data_source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    x: Mapped[float] = mapped_column(Float, default=0)
    y: Mapped[float] = mapped_column(Float, default=0)
    width: Mapped[float] = mapped_column(Float, default=960)
    height: Mapped[float] = mapped_column(Float, default=640)
    # Shared filters applied to every widget they are compatible with.
    filters: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    widgets: Mapped[list["Widget"]] = relationship(
        back_populates="dashboard",
        cascade="all, delete-orphan",
        order_by="Widget.position",
    )


class Widget(Base):
    __tablename__ = "widgets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    dashboard_id: Mapped[str] = mapped_column(ForeignKey("dashboards.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(300))
    position: Mapped[int] = mapped_column(Integer, default=0)
    query: Mapped[dict] = mapped_column(JSON, default=dict)
    presentation: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    dashboard: Mapped[Dashboard] = relationship(back_populates="widgets")


class CanvasState(Base):
    __tablename__ = "canvas_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    viewport: Mapped[dict] = mapped_column(JSON, default=lambda: {"x": 0, "y": 0, "zoom": 1})


class ChangeSet(Base):
    """One agent turn (or manual edit) worth of dashboard changes, for history and undo."""

    __tablename__ = "change_sets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    source: Mapped[str] = mapped_column(String(20), default="agent")
    summary: Mapped[str] = mapped_column(Text, default="")
    # {dashboard_id: snapshot | None}; None means the dashboard did not exist.
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    undone: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text)
    selection: Mapped[dict] = mapped_column(JSON, default=dict)
    clarification: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    change_set_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ok")  # ok | error | clarification
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AgentCall(Base):
    """Audit log of exactly what was sent to and received from the model.

    Used to verify the data boundary: inputs must contain metadata and
    configuration only, never query results.
    """

    __tablename__ = "agent_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    purpose: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    request: Mapped[dict] = mapped_column(JSON)
    response: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
