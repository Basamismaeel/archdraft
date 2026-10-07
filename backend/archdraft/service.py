"""Runs the ADK workflows and turns their events into the API response.

Used by the FastAPI app, scripts/generate.py and scripts/evaluate.py, so all of them go through
exactly the same code.
"""

import asyncio
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal

from google.adk import Runner, Workflow
from google.adk.events import Event
from google.adk.models import BaseLlm
from google.adk.sessions import InMemorySessionService
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from archdraft import storage
from archdraft.agents.pipeline import (
    ARCHITECT_NAME,
    BASELINE_NAME,
    LLM_AGENT_NAMES,
    STATE_HISTORY,
    STATE_REVIEW_HISTORY,
    build_baseline,
    build_judge,
    build_pipeline,
    build_requirements_analyst,
    build_single_agent,
)
from archdraft.config import model_name, require_credentials
from archdraft.metrics import (
    Coverage,
    DiagramStats,
    extract_mermaid,
    mermaid_text_stats,
    model_coverage,
    model_stats,
    text_coverage,
)
from archdraft.render.mermaid import mermaid_node_ids, to_mermaid
from archdraft.schema import (
    ArchitectureModel,
    CriticReport,
    JudgeReport,
    ObligationCheck,
    RequirementsAnalysis,
)
from archdraft.validation.rules import ValidationError

Mode = Literal["pipeline", "single_agent", "baseline"]
Progress = Callable[[dict[str, Any]], Awaitable[None]]


class NodeTiming(BaseModel):
    node: str
    ms: int


class Timings(BaseModel):
    total_ms: int
    nodes: list[NodeTiming]


class AttemptRecord(BaseModel):
    attempt: int
    error_count: int
    warning_count: int = 0
    errors: list[ValidationError]


class ReviewRound(BaseModel):
    round: int
    met: int
    partial: int
    missing: int
    blocking: int
    major: int
    minor: int


class Judgement(BaseModel):
    """An independent examiner's grade of one diagram against fixed obligations."""

    score: float  # (met + 0.5 * partial) / total, as a percentage
    met: int
    partial: int
    missing: int
    total: int
    checks: list[ObligationCheck]
    unjustified_elements: list[str]
    illogical_connections: list[str]
    obligations_from: str  # which analysis supplied the obligations
    judge_model: str


class GenerateResult(BaseModel):
    id: str = ""
    created_at: str
    mode: Mode
    llm_model: str
    requirements_text: str
    model: ArchitectureModel | None
    mermaid: str
    node_ids: dict[str, str]  # Mermaid node ID -> Element.id, for click handling in the UI
    validation_errors: list[ValidationError]
    validation_history: list[AttemptRecord]
    coverage: Coverage
    stats: DiagramStats
    timings: Timings
    llm_calls: int
    raw_llm_response: str
    analysis: RequirementsAnalysis | None = None
    review: CriticReport | None = None
    review_history: list[ReviewRound] = []
    judgement: Judgement | None = None


class GenerationError(RuntimeError):
    """The workflow ran but did not produce a usable result."""


def resolve_model() -> str | BaseLlm:
    """The model handed to ADK. Tests replace this with an offline stub."""
    require_credentials()
    return model_name()


BUILDERS: dict[str, Callable[[str | BaseLlm], Workflow]] = {
    "pipeline": build_pipeline,
    "single_agent": build_single_agent,
    "baseline": build_baseline,
    "judge": build_judge,
    "analyst": lambda m: Workflow(
        name="archdraft_analyst", edges=[("START", build_requirements_analyst(m))]
    ),
}
_workflows: dict[tuple[str, str], Workflow] = {}


def _workflow(kind: str, model: str | BaseLlm) -> Workflow:
    if not isinstance(model, str):  # stub models are not cached
        return BUILDERS[kind](model)
    key = (kind, model)
    if key not in _workflows:
        _workflows[key] = BUILDERS[kind](model)
    return _workflows[key]


def _node_label(event: Event) -> str:
    path = event.node_info.path if event.node_info else ""
    last = (path or event.author or "?").split("/")[-1]
    name, _, run = last.partition("@")
    return f"{name} (run {run})" if run and run != "1" else name


def _model_text(event: Event) -> str:
    if event.partial or not event.content or event.content.role != "model":
        return ""
    return "".join(p.text for p in event.content.parts or [] if p.text and not p.thought)


class _RunCapture(BaseModel):
    output: Any = None
    state: dict[str, Any] = {}
    raw_responses: list[tuple[str, str]] = []  # (agent name, text)
    model_versions: list[str] = []
    timings: Timings


async def _run(workflow: Workflow, text: str, progress: Progress | None = None) -> _RunCapture:
    sessions = InMemorySessionService()
    runner = Runner(app_name=workflow.name, agent=workflow, session_service=sessions)
    session = await sessions.create_session(app_name=workflow.name, user_id="archdraft")
    message = types.Content(role="user", parts=[types.Part(text=text)])

    output: Any = None
    error: str | None = None
    raw: list[tuple[str, str]] = []
    versions: list[str] = []
    nodes: list[NodeTiming] = []
    started = previous = time.perf_counter()
    try:
        async for event in runner.run_async(
            user_id="archdraft", session_id=session.id, new_message=message
        ):
            now = time.perf_counter()
            label = _node_label(event)
            elapsed = int((now - previous) * 1000)
            if nodes and nodes[-1].node == label:
                nodes[-1].ms += elapsed
            else:
                nodes.append(NodeTiming(node=label, ms=elapsed))
                if progress:
                    await progress({"type": "step", "node": label, "ms": elapsed})
            previous = now

            # Record the error and let the run finish: raising inside the event stream leaves
            # ADK's async generators half-closed and floods the log with secondary tracebacks.
            if event.error_message and error is None:
                error = f"{event.error_code or 'error'}: {event.error_message}"
            if event.author in LLM_AGENT_NAMES and (body := _model_text(event)):
                raw.append((event.author, body))
                # The model that actually answered: differs from GEMINI_MODEL after a fallback.
                if event.model_version and event.model_version not in versions:
                    versions.append(event.model_version)
            if event.output is not None:
                output = event.output
    except genai_errors.APIError as exc:
        raise GenerationError(f"The Gemini API refused the request. {exc}") from exc

    # A node that failed and then succeeded on ADK's node retry still logs the first error;
    # only a run that produced no output has really failed.
    if error and output is None:
        raise GenerationError(f"The model call failed. {error}")
    final = await sessions.get_session(
        app_name=workflow.name, user_id="archdraft", session_id=session.id
    )
    return _RunCapture(
        output=output,
        state=dict(final.state) if final else {},
        raw_responses=raw,
        model_versions=versions,
        timings=Timings(total_ms=int((time.perf_counter() - started) * 1000), nodes=nodes),
    )


def _answered_by(run: _RunCapture, configured: str) -> str:
    if not run.model_versions or run.model_versions == [configured]:
        return configured
    return ", ".join(run.model_versions) + f" (configured: {configured})"


def _last_from(run: _RunCapture, agent: str) -> str:
    texts = [t for a, t in run.raw_responses if a == agent]
    return texts[-1] if texts else ""


def _new_id(mode: str) -> str:
    return f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{mode}-{secrets.token_hex(3)}"


def _label(model: str | BaseLlm) -> str:
    return model if isinstance(model, str) else type(model).__name__


async def generate(
    requirements_text: str,
    mode: Mode,
    *,
    save: bool = True,
    progress: Progress | None = None,
) -> GenerateResult:
    model = resolve_model()
    workflow = _workflow(mode, model)
    created_at = datetime.now(UTC).isoformat(timespec="seconds")
    run = await _run(workflow, requirements_text, progress)

    if mode in ("pipeline", "single_agent"):
        if not isinstance(run.output, dict) or "model" not in run.output:
            raise GenerationError(
                "The pipeline finished without an architecture. Last model response: "
                + (run.raw_responses[-1][1][:500] if run.raw_responses else "(none)")
            )
        arch = ArchitectureModel.model_validate(run.output["model"])
        analysis = run.output.get("analysis")
        review = run.output.get("review")
        result = GenerateResult(
            created_at=created_at,
            mode=mode,
            llm_model=_answered_by(run, _label(model)),
            requirements_text=requirements_text,
            model=arch,
            mermaid=run.output["mermaid"],
            node_ids={mid: eid for eid, mid in mermaid_node_ids(arch).items()},
            validation_errors=[
                ValidationError.model_validate(e) for e in run.output["validation_errors"]
            ],
            validation_history=[
                AttemptRecord.model_validate(h) for h in run.state.get(STATE_HISTORY, [])
            ],
            coverage=model_coverage(arch, requirements_text),
            stats=model_stats(arch),
            timings=run.timings,
            llm_calls=len(run.raw_responses),
            raw_llm_response=_last_from(run, ARCHITECT_NAME),
            analysis=RequirementsAnalysis.model_validate(analysis) if analysis else None,
            review=CriticReport.model_validate(review) if review else None,
            review_history=[
                ReviewRound.model_validate(r) for r in run.state.get(STATE_REVIEW_HISTORY, [])
            ],
        )
    else:
        text = run.output if isinstance(run.output, str) else _last_from(run, BASELINE_NAME)
        if not text.strip():
            raise GenerationError("The baseline model returned an empty response.")
        mermaid = extract_mermaid(text)
        result = GenerateResult(
            created_at=created_at,
            mode=mode,
            llm_model=_answered_by(run, _label(model)),
            requirements_text=requirements_text,
            model=None,
            mermaid=mermaid,
            node_ids={},
            validation_errors=[],
            validation_history=[],
            coverage=text_coverage(mermaid, requirements_text),
            stats=mermaid_text_stats(mermaid),
            timings=run.timings,
            llm_calls=1,
            raw_llm_response=text,
        )

    if save:
        result.id = _new_id(mode)
        storage.save(result.id, result.model_dump(mode="json"))
    return result


# ---------------------------------------------------------------------------------------------
# Independent evaluation
# ---------------------------------------------------------------------------------------------


async def analyse(requirements_text: str) -> RequirementsAnalysis:
    """Run only the requirements analyst (used to get obligations for judging)."""
    run = await _run(_workflow("analyst", resolve_model()), requirements_text)
    if run.output is None:
        raise GenerationError("The requirements analyst returned nothing.")
    return RequirementsAnalysis.model_validate(run.output)


def judge_view(result: GenerateResult) -> str:
    """The diagram the judge sees. Pipeline results get untruncated arrow labels."""
    if result.model is not None:
        return to_mermaid(result.model, max_edge_label=500)
    return result.mermaid


async def judge(
    result: GenerateResult, analysis: RequirementsAnalysis, obligations_from: str
) -> Judgement:
    """Grade one result against fixed obligations with the independent judge prompt."""
    model = resolve_model()
    obligations = "\n".join(
        f"- {o.id} ({', '.join(o.requirement_ids)}): {o.statement}" for o in analysis.obligations
    )
    request = (
        f"## Requirements\n{result.requirements_text}\n\n"
        f"## Design obligations\n{obligations}\n\n"
        f"## Diagram (Mermaid)\n```mermaid\n{judge_view(result)}```\n"
    )
    run = await _run(_workflow("judge", model), request)
    if run.output is None:
        raise GenerationError("The judge returned nothing.")
    report = JudgeReport.model_validate(run.output)
    known = {o.id for o in analysis.obligations}
    checks = [c for c in report.obligation_checks if c.obligation_id in known]
    met = sum(c.status == "met" for c in checks)
    partial = sum(c.status == "partial" for c in checks)
    total = len(analysis.obligations)  # an obligation the judge skipped counts as missing
    return Judgement(
        score=round(100 * (met + 0.5 * partial) / total, 1) if total else 0.0,
        met=met,
        partial=partial,
        missing=total - met - partial,
        total=total,
        checks=checks,
        unjustified_elements=report.unjustified_elements,
        illogical_connections=report.illogical_connections,
        obligations_from=obligations_from,
        judge_model=_answered_by(run, _label(model)),
    )


async def judge_saved(project_ids: list[str]) -> dict[str, Judgement]:
    """Judge saved runs of the same requirements against one shared set of obligations."""
    results = []
    for pid in project_ids:
        data = storage.load(pid)
        if data is None:
            raise GenerationError(f"No saved run '{pid}'.")
        results.append(GenerateResult.model_validate(data))
    if len({r.requirements_text for r in results}) != 1:
        raise GenerationError("These runs were made from different requirements.")

    source = next((r for r in results if r.analysis is not None), None)
    if source is not None and source.analysis is not None:
        analysis, origin = source.analysis, f"analysis of run {source.id}"
    else:
        analysis, origin = await analyse(results[0].requirements_text), "fresh analysis"

    judgements = await asyncio.gather(*(judge(r, analysis, origin) for r in results))
    for result, judgement in zip(results, judgements, strict=True):
        result.judgement = judgement
        storage.save(result.id, json.loads(result.model_dump_json()))
    return {r.id: j for r, j in zip(results, judgements, strict=True)}
