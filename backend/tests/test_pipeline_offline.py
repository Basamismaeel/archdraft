"""Runs the real ADK graphs end to end with a stub model: no network, no API key."""

import asyncio
import json
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse

from archdraft import service, storage
from archdraft.agents.pipeline import ARCHITECT_NAME
from archdraft.metrics import text_coverage
from tests.conftest import (
    LIBRARY_REQUIREMENTS,
    StubLlm,
    critic_report,
    library_model_with_fulfilments,
    stub_answers,
)


def use_stub(monkeypatch: pytest.MonkeyPatch, **answers: object) -> StubLlm:
    stub = StubLlm(model="stub", responses=stub_answers(**answers))  # type: ignore[arg-type]
    monkeypatch.setattr(service, "resolve_model", lambda: stub)
    return stub


def broken_model_json() -> str:
    broken = library_model_with_fulfilments()
    broken.elements[2].satisfies = []  # untraced web app
    for owner in [*broken.elements, *broken.relations]:
        owner.satisfies = [r for r in owner.satisfies if r != "FR-04"]
    return broken.model_dump_json()


def text_of(request: object) -> str:
    return "".join(p.text or "" for c in request.contents for p in c.parts or [])  # type: ignore[attr-defined]


def test_clean_run_goes_analyst_architect_validator_critic(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    stub = use_stub(monkeypatch)
    result = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "pipeline"))

    nodes = [n.node for n in result.timings.nodes]
    assert nodes == [
        "prepare_input",
        "requirements_analyst",
        "build_architect_request",
        ARCHITECT_NAME,
        "validate_architecture",
        "build_review_request",
        "architecture_critic",
        "review_router",
        "render_diagram",
    ]
    assert result.llm_calls == 3
    assert result.validation_errors == []
    assert result.analysis is not None and len(result.analysis.obligations) == 2
    assert result.review is not None and result.review_history[0].met == 2
    # The architect is given the analyst's obligations, the critic the architect's design.
    assert "OB-02" in text_of(stub.requests_for("ArchitectureModel")[0])
    assert '"fulfilments"' in text_of(stub.requests_for("CriticReport")[0])
    saved = json.loads((tmp_data_dir / f"{result.id}.json").read_text())
    assert saved["analysis"]["obligations"][0]["id"] == "OB-01"
    assert storage.list_projects()[0].id == result.id


def test_rule_repair_then_critic_revision(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    good = library_model_with_fulfilments().model_dump_json()
    stub = use_stub(
        monkeypatch,
        architectures=[broken_model_json(), good, good],
        critics=[
            critic_report(status="partial", findings=1).model_dump_json(),
            critic_report().model_dump_json(),
        ],
    )
    result = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "pipeline"))

    # broken -> rule repair -> critic asks for revision -> revised -> critic accepts
    assert len(stub.requests_for("ArchitectureModel")) == 3
    assert len(stub.requests_for("CriticReport")) == 2
    assert [a.error_count > 0 for a in result.validation_history] == [True, False, False]
    assert [r.partial for r in result.review_history] == [1, 0]
    repair, revision = (text_of(r) for r in stub.requests_for("ArchitectureModel")[1:])
    assert "element_traced" in repair and "FR-04: The system emails members" in repair
    assert "No search index for a 1 s target." in revision and "OB-01 is partial" in revision
    assert result.coverage.percent == 100.0


def test_only_one_revision_round(monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path) -> None:
    stub = use_stub(monkeypatch, critics=[critic_report(status="missing").model_dump_json()])
    result = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "pipeline"))
    assert len(stub.requests_for("CriticReport")) == 2
    assert [r.missing for r in result.review_history] == [1, 1]  # still reported, not hidden


def test_errors_survive_when_repair_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    use_stub(monkeypatch, architectures=[broken_model_json()])
    result = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "single_agent"))
    assert result.llm_calls == 2  # one repair attempt, then stop
    rules = {e.rule for e in result.validation_errors}
    assert {"element_traced", "requirement_accounted_for"} <= rules
    assert "class n_web_app flagged" in result.mermaid
    assert result.analysis is None and result.review is None


def test_baseline_extracts_mermaid_and_measures_it(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    answer = (
        "Here is the architecture:\n```mermaid\nflowchart TD\n"
        "  U[Member] --> W[Web App]\n  W --> A[API]\n  A --> D[(PostgreSQL)]\n"
        "  A --> L[(Loans DB - PostgreSQL)]\n```\nHope this helps."
    )
    stub = use_stub(monkeypatch, baseline=answer)
    result = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "baseline"))

    assert stub.requests[0].config.response_schema is None
    assert result.model is None
    assert result.mermaid.startswith("flowchart TD")
    assert "Hope this helps" not in result.mermaid
    assert result.stats.elements == 5
    assert result.stats.relations == 4
    assert result.stats.datastore_nodes == 2
    assert result.stats.datastore_technologies == ["PostgreSQL"]
    assert result.coverage.covered == 0 and result.coverage.total == 6


def test_judge_grades_runs_against_shared_obligations(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    stub = use_stub(monkeypatch)
    pipeline = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "pipeline"))
    baseline = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "baseline"))
    grades = asyncio.run(service.judge_saved([pipeline.id, baseline.id]))

    assert grades[pipeline.id].score == 100.0 and grades[baseline.id].total == 2
    assert grades[baseline.id].obligations_from == f"analysis of run {pipeline.id}"
    # Both diagrams went to the same judge prompt; the analyst was not called again.
    assert len(stub.requests_for("RequirementsAnalysis")) == 1
    judged = [text_of(r) for r in stub.requests_for("JudgeReport")]
    assert any("A[App] --> B[(DB)]" in t for t in judged)
    assert json.loads((tmp_data_dir / f"{baseline.id}.json").read_text())["judgement"]


def test_baseline_coverage_reads_id_shorthand() -> None:
    coverage = text_coverage('A["Service FR-01/02/04"] --> B["NFR-01"]', LIBRARY_REQUIREMENTS)
    assert coverage.uncovered == ["FR-03", "NFR-02"]


def test_overloaded_model_is_retried_at_node_level(
    monkeypatch: pytest.MonkeyPatch, tmp_data_dir: Path
) -> None:
    from google.adk.workflow import RetryConfig
    from google.genai import errors as genai_errors

    from archdraft.agents import pipeline

    monkeypatch.setattr(
        pipeline,
        "NODE_RETRY",
        RetryConfig(max_attempts=3, initial_delay=0.01, max_delay=0.01, exceptions=["ServerError"]),
    )

    class FlakyStub(StubLlm):
        failures: int = 1

        async def generate_content_async(
            self, llm_request: LlmRequest, stream: bool = False
        ) -> AsyncGenerator[LlmResponse, None]:
            if self.failures:
                self.failures -= 1
                raise genai_errors.ServerError(503, {"error": {"message": "high demand"}})
            async for response in super().generate_content_async(llm_request, stream):
                yield response

    stub = FlakyStub(model="stub", responses=stub_answers())
    monkeypatch.setattr(service, "resolve_model", lambda: stub)
    result = asyncio.run(service.generate(LIBRARY_REQUIREMENTS, "pipeline"))
    assert result.analysis is not None and result.review is not None
