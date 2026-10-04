from fastapi.testclient import TestClient

from app import main
from app.llm import LLMError
from app.schemas import Approach
from tests.test_schemas import good

client = TestClient(main.app)


def test_needs_input():
    assert client.post("/api/map", data={"text": ""}).status_code == 400


def test_ok(monkeypatch):
    monkeypatch.setattr(main, "map_approach", lambda t, i: (Approach.model_validate(good()), {"model": "m", "latency_seconds": 1.0}))
    r = client.post("/api/map", data={"text": "two sum"})
    assert r.status_code == 200 and r.json()["approach"]["mindmap"]["edges"][0]["from"] == "n1"


def test_txt_and_bad_type(monkeypatch):
    seen = {}
    def fake(t, i):
        seen["t"] = t
        return Approach.model_validate(good()), {"model": "m", "latency_seconds": 1.0}
    monkeypatch.setattr(main, "map_approach", fake)
    assert client.post("/api/map", files={"files": ("p.txt", b"hello", "text/plain")}).status_code == 200
    assert seen["t"] == "hello"
    assert client.post("/api/map", files={"files": ("a.pdf", b"x", "application/pdf")}).status_code == 415


def test_llm_error_is_json(monkeypatch):
    def boom(t, i): raise LLMError(502, "bad key")
    monkeypatch.setattr(main, "map_approach", boom)
    r = client.post("/api/map", data={"text": "x"})
    assert r.status_code == 502 and r.json() == {"error": "bad key"}
