import os
import tempfile

import pytest

_tmp = tempfile.mkdtemp(prefix="gd-test-")
os.environ["APP_DB_URL"] = f"sqlite:///{_tmp}/app.db"
os.environ["DEMO_DB_PATH"] = f"{_tmp}/demo.db"
os.environ["OPENAI_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.llm import set_llm_override  # noqa: E402


class FakeLLM:
    model = "fake"

    def __init__(self):
        self.responses: list[dict] = []
        self.requests: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.requests.append((system, user))
        return self.responses.pop(0)


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def fake_llm():
    llm = FakeLLM()
    set_llm_override(llm)
    yield llm
    set_llm_override(None)


@pytest.fixture(scope="session")
def demo_source(client):
    ds = client.get("/api/datasources").json()[0]
    r = client.post(f"/api/datasources/{ds['id']}/metadata/load-demo")
    assert r.status_code == 200
    return ds
