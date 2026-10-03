"""Connections to business databases. Read-only where the driver allows it."""

import sqlite3
import threading
from urllib.parse import unquote

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, make_url

_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def get_engine(url: str) -> Engine:
    with _lock:
        engine = _engines.get(url)
        if engine is None:
            engine = _build(url)
            _engines[url] = engine
        return engine


def dispose_engine(url: str) -> None:
    with _lock:
        engine = _engines.pop(url, None)
    if engine is not None:
        engine.dispose()


def _build(url: str) -> Engine:
    parsed = make_url(url)
    if parsed.get_backend_name() == "sqlite":
        path = unquote(parsed.database or "")
        if not path or path == ":memory:":
            raise ValueError("SQLite sources must point at a database file")

        def connect() -> sqlite3.Connection:
            return sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)

        return create_engine("sqlite://", creator=connect)
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def redact_url(url: str) -> str:
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return "<invalid url>"
