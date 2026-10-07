from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from archdraft import service
from archdraft.api import app
from archdraft.config import ConfigError
from tests.conftest import LIBRARY_REQUIREMENTS, StubLlm, stub_answers

client = TestClient(app)


def test_samples_ship_both_requirement_sets() -> None:
    samples = {s["id"]: s for s in client.get("/api/samples").json()}
    assert {"library", "car_sales"} <= samples.keys()
    assert samples["car_sales"]["title"] == "Car Sales Marketplace"
    assert "FR-20:" in samples["car_sales"]["text"]


def test_generate_then_list_and_reload(monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path) -> None:
    stub = StubLlm(model="stub", responses=stub_answers())
    monkeypatch.setattr(service, "resolve_model", lambda: stub)

    response = client.post(
        "/api/generate", json={"requirements_text": LIBRARY_REQUIREMENTS, "mode": "pipeline"}
    )
    assert response.status_code == 200
    body = response.json()
    for key in ("model", "mermaid", "validation_errors", "coverage", "timings", "raw_llm_response"):
        assert key in body
    assert body["coverage"] == {
        "covered": 6,
        "total": 6,
        "percent": 100.0,
        "uncovered": [],
        "basis": "requirements cited by at least one element or relation",
    }

    listed = client.get("/api/projects").json()
    assert [p["id"] for p in listed] == [body["id"]]
    reloaded = client.get(f"/api/projects/{body['id']}").json()
    assert reloaded["mermaid"] == body["mermaid"]


def test_missing_configuration_is_a_readable_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_key() -> str:
        raise ConfigError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(service, "resolve_model", no_key)
    response = client.post("/api/generate", json={"requirements_text": "FR-01: x"})
    assert response.status_code == 503
    assert "GOOGLE_API_KEY" in response.json()["detail"]


def test_unknown_or_unsafe_project_id_is_404(tmp_data_dir: Path) -> None:
    assert client.get("/api/projects/does-not-exist").status_code == 404
    assert client.get("/api/projects/..%2F..%2Fetc%2Fpasswd").status_code == 404


def test_stream_reports_each_node_then_the_result(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    import json

    stub = StubLlm(model="stub", responses=stub_answers())
    monkeypatch.setattr(service, "resolve_model", lambda: stub)
    with client.stream(
        "POST", "/api/generate/stream", json={"requirements_text": LIBRARY_REQUIREMENTS}
    ) as response:
        lines = [json.loads(line) for line in response.iter_lines() if line]
    steps = [line["node"] for line in lines if line["type"] == "step"]
    assert steps[:2] == ["prepare_input", "requirements_analyst"]
    assert steps[-1] == "render_diagram"
    assert lines[-1]["type"] == "result"
    assert lines[-1]["result"]["review"]["obligation_checks"]


def test_stream_reports_errors_as_a_line(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    def no_key() -> str:
        raise ConfigError("GOOGLE_API_KEY is not set.")

    monkeypatch.setattr(service, "resolve_model", no_key)
    with client.stream("POST", "/api/generate/stream", json={"requirements_text": "FR-01: x"}) as r:
        lines = [json.loads(line) for line in r.iter_lines() if line]
    assert lines == [{"type": "error", "status": 503, "detail": "GOOGLE_API_KEY is not set."}]
