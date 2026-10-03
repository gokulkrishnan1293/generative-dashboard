from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import SessionLocal, init_db
from .models import DataSource
from .routers import agent, canvas, datasources, system


def bootstrap_demo() -> None:
    from datetime import datetime, timezone

    from .schemas import MetadataDoc
    from .services.demo_seed import DEMO_DOCUMENTATION, create_demo_database, demo_url
    from .services.introspect import discover_schema, merge_discovery

    s = get_settings()
    if not s.demo_enabled:
        return
    if not Path(s.demo_db_path).exists():
        create_demo_database(s.demo_db_path)
    with SessionLocal() as db:
        if db.query(DataSource).filter(DataSource.is_demo.is_(True)).first():
            return
        url = demo_url(s.demo_db_path)
        doc, _ = merge_discovery(MetadataDoc(), discover_schema(url))
        db.add(DataSource(
            name="Demo Sales (SQLite)", url=url, is_demo=True, documentation=DEMO_DOCUMENTATION,
            metadata_doc=doc.model_dump(), discovered_at=datetime.now(timezone.utc),
        ))
        db.commit()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    bootstrap_demo()
    yield


app = FastAPI(title="Generative Dashboard API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (system.router, datasources.router, canvas.router, agent.router):
    app.include_router(r)
