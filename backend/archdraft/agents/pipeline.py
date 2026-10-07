"""The ArchDraft agent graph, built on the ADK 2.x graph Workflow.

v2 pipeline (three LLM agents, four deterministic nodes):

    START
      -> prepare_input                 (code)  stores the requirements in session state
      -> requirements_analyst          (LLM)   requirements, data classes, design obligations
      -> build_architect_request       (code)
      -> requirements_to_architecture  (LLM)   ArchitectureModel with fulfilments per obligation
      -> validate_architecture         (code)  11 deterministic rules
           REPAIR -> build_repair_request -> architect             (at most once per round)
           REVIEW -> build_review_request -> architecture_critic (LLM) -> review_router (code)
                       REVISE -> build_revision_request -> architect      (at most once)
                       ACCEPT -> render_diagram
           ACCEPT -> render_diagram                                (single-agent mode only)

The analyst, the architect and the critic correspond to the Requirements Analyst, Component
Synthesizer and Constraint Validator roles of the Agent Garden design. The validator and the
diagram renderer are code, so they are repeatable and cannot hallucinate.

`build_single_agent` keeps the v1 graph (architect + validator only) for before/after
evaluation, and `build_baseline` is the naive one-prompt comparison.
"""

import json
from typing import Any

from google.adk import Agent, Context, Event, Workflow
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.models import BaseLlm, FallbackModel, Gemini
from google.adk.workflow import START, RetryConfig
from google.genai import types

from archdraft.config import PROMPTS_DIR, fallback_model_names
from archdraft.render.mermaid import to_mermaid
from archdraft.schema import (
    ArchitectureModel,
    CriticReport,
    JudgeReport,
    RequirementsAnalysis,
)
from archdraft.validation.rules import blocking, validate_model

PIPELINE_NAME = "archdraft_pipeline"
SINGLE_AGENT_NAME = "archdraft_single_agent"
ANALYST_NAME = "requirements_analyst"
ARCHITECT_NAME = "requirements_to_architecture"
CRITIC_NAME = "architecture_critic"
BASELINE_NAME = "naive_baseline"
JUDGE_NAME = "independent_judge"
LLM_AGENT_NAMES = {ANALYST_NAME, ARCHITECT_NAME, CRITIC_NAME, BASELINE_NAME, JUDGE_NAME}

MAX_REPAIRS_PER_ROUND = 1  # deterministic-rule repair, as in the original brief
MAX_REVISIONS = 1  # critic-driven revision rounds
REPAIR = "REPAIR"
REVIEW = "REVIEW"
REVISE = "REVISE"
ACCEPT = "ACCEPT"

# Session state keys. Kept in one place because the service reads them back after a run.
STATE_REQUIREMENTS = "requirements_text"
STATE_ANALYSIS = "analysis"
STATE_ARCHITECTURE = "architecture"
STATE_ATTEMPT = "attempt"
STATE_ROUND_ATTEMPTS = "round_attempts"
STATE_ERRORS = "validation_errors"
STATE_HISTORY = "validation_history"
STATE_REVIEW = "review"
STATE_REVIEW_HISTORY = "review_history"
STATE_REVISIONS = "revisions"


# Gemini answers 503 "high demand" and 429 during busy periods. Each model retries with
# backoff; if the primary model is still overloaded, ADK's FallbackModel moves the request on
# to GEMINI_FALLBACK_MODEL (when set), so a busy period does not end a demo.
RETRYABLE = [429, 500, 502, 503, 504]
PRIMARY_RETRY = types.HttpRetryOptions(
    attempts=3, initial_delay=2, max_delay=10, http_status_codes=RETRYABLE
)
FALLBACK_RETRY = types.HttpRetryOptions(
    attempts=5, initial_delay=2, max_delay=30, http_status_codes=RETRYABLE
)


# If every model is still overloaded, or the answer does not parse against the schema, ADK
# re-runs the whole agent node after a pause: up to 3 attempts, waiting about 20 s then 40 s.
NODE_RETRY = RetryConfig(
    max_attempts=3,
    initial_delay=20,
    max_delay=60,
    exceptions=["ServerError", "ValidationError", "JSONDecodeError"],
)


def with_retries(model: str | BaseLlm) -> BaseLlm:
    """Wrap a model name in ADK's Gemini class with retries and an optional fallback.

    Stub models used by the tests pass through unchanged."""
    if not isinstance(model, str):
        return model
    primary = Gemini(model=model, retry_options=PRIMARY_RETRY)
    backups = [name for name in fallback_model_names() if name != model]
    if not backups:
        return primary
    return FallbackModel(
        models=[primary, *(Gemini(model=name, retry_options=FALLBACK_RETRY) for name in backups)]
    )


def load_prompt(name: str) -> str:
    """Read a prompt file. Called on every model request, so prompt edits apply without restart."""
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def _prompt(name: str) -> Any:
    # An instruction provider (rather than a string) also stops ADK from treating any
    # {braces} a teammate writes in the Markdown file as session-state placeholders.
    def provider(_ctx: ReadonlyContext) -> str:
        return load_prompt(name)

    return provider


def _analysis(ctx: Context) -> RequirementsAnalysis | None:
    raw = ctx.state.get(STATE_ANALYSIS)
    return RequirementsAnalysis.model_validate(raw) if raw else None


def _dump(model: Any) -> str:
    return model.model_dump_json(indent=1)


# ---------------------------------------------------------------------------------------------
# Deterministic nodes. Plain functions: ADK wraps each one in a FunctionNode. `ctx` and
# `node_input` are bound by ADK; `node_input` is the previous node's output.
# ---------------------------------------------------------------------------------------------


def prepare_input(ctx: Context, node_input: str) -> str:
    """Keep the original requirements in session state; later nodes and rule 7 need them."""
    ctx.state[STATE_REQUIREMENTS] = node_input
    ctx.state[STATE_ATTEMPT] = 0
    ctx.state[STATE_ROUND_ATTEMPTS] = 0
    ctx.state[STATE_HISTORY] = []
    ctx.state[STATE_REVIEW_HISTORY] = []
    ctx.state[STATE_REVISIONS] = 0
    return node_input


def build_architect_request(ctx: Context, node_input: RequirementsAnalysis) -> str:
    """Hand the analyst's output to the architect, together with the original text."""
    ctx.state[STATE_ANALYSIS] = json.loads(node_input.model_dump_json())
    return (
        "Design the architecture for this requirements analysis. Meet every design obligation "
        "and add one fulfilment entry per obligation.\n\n"
        f"## Requirements analysis\n{_dump(node_input)}\n\n"
        f"## Original requirements\n{ctx.state.get(STATE_REQUIREMENTS, '')}\n"
    )


def validate_architecture(ctx: Context, node_input: ArchitectureModel) -> Event:
    """Run the validation rules and choose the next edge. Never calls a model."""
    analysis = _analysis(ctx)
    errors = validate_model(
        node_input,
        ctx.state.get(STATE_REQUIREMENTS),
        analysis.obligations if analysis else None,
    )
    hard = blocking(errors)
    attempt = int(ctx.state.get(STATE_ATTEMPT, 0)) + 1
    round_attempts = int(ctx.state.get(STATE_ROUND_ATTEMPTS, 0)) + 1
    error_dicts = [e.model_dump() for e in errors]
    ctx.state[STATE_ATTEMPT] = attempt
    ctx.state[STATE_ROUND_ATTEMPTS] = round_attempts
    ctx.state[STATE_ERRORS] = error_dicts
    ctx.state[STATE_HISTORY] = [
        *ctx.state.get(STATE_HISTORY, []),
        {
            "attempt": attempt,
            "error_count": len(hard),
            "warning_count": len(errors) - len(hard),
            "errors": error_dicts,
        },
    ]
    if hard and round_attempts <= MAX_REPAIRS_PER_ROUND:
        route = REPAIR
    elif analysis is not None:
        route = REVIEW
    else:
        route = ACCEPT
    return Event(route=route, output=node_input)


def _requirements_block(ctx: Context) -> str:
    analysis = _analysis(ctx)
    obligations = (
        "\n".join(
            f"- {o.id} ({', '.join(o.requirement_ids)}): {o.statement}"
            for o in analysis.obligations
        )
        if analysis
        else ""
    )
    block = f"## Original requirements\n{ctx.state.get(STATE_REQUIREMENTS, '')}\n"
    if obligations:
        block += f"\n## Design obligations\n{obligations}\n"
    return block


def build_repair_request(ctx: Context, node_input: ArchitectureModel) -> str:
    """Turn the failed model and its errors into the next message for the architect agent."""
    errors = "\n".join(
        f"- [{e['rule']}] {e['message']}"
        for e in ctx.state.get(STATE_ERRORS, [])
        if e.get("severity", "error") == "error"
    )
    return (
        "Your previous architecture failed automatic validation. Return the complete corrected "
        "architecture as JSON in the same schema. Fix every error below and change nothing "
        "else that is already correct.\n\n"
        f"## Validation errors\n{errors}\n\n"
        f"## Your previous architecture\n{_dump(node_input)}\n\n" + _requirements_block(ctx)
    )


def build_review_request(ctx: Context, node_input: ArchitectureModel) -> str:
    """Give the critic the obligations, the design, and what the rules already found."""
    analysis = _analysis(ctx)
    notes = (
        "\n".join(
            f"- [{e['rule']}, {e.get('severity', 'error')}] {e['message']}"
            for e in ctx.state.get(STATE_ERRORS, [])
        )
        or "- none"
    )
    return (
        "Review this architecture against the design obligations.\n\n"
        f"## Design obligations\n{_dump(analysis) if analysis else '(none)'}\n\n"
        f"## Proposed architecture\n{_dump(node_input)}\n\n"
        f"## Already reported by the automatic rules\n{notes}\n"
    )


def review_router(ctx: Context, node_input: CriticReport) -> Event:
    """Decide whether the critic's findings justify one revision round."""
    revisions = int(ctx.state.get(STATE_REVISIONS, 0))
    statuses = [c.status for c in node_input.obligation_checks]
    severities = [f.severity for f in node_input.findings]
    ctx.state[STATE_REVIEW] = json.loads(node_input.model_dump_json())
    ctx.state[STATE_REVIEW_HISTORY] = [
        *ctx.state.get(STATE_REVIEW_HISTORY, []),
        {
            "round": revisions + 1,
            "met": statuses.count("met"),
            "partial": statuses.count("partial"),
            "missing": statuses.count("missing"),
            "blocking": severities.count("blocking"),
            "major": severities.count("major"),
            "minor": severities.count("minor"),
        },
    ]
    needs_revision = (
        "blocking" in severities
        or "major" in severities
        or "missing" in statuses
        or "partial" in statuses
    )
    model = ArchitectureModel.model_validate(ctx.state[STATE_ARCHITECTURE])
    route = REVISE if needs_revision and revisions < MAX_REVISIONS else ACCEPT
    return Event(route=route, output=model)


def build_revision_request(ctx: Context, node_input: ArchitectureModel) -> str:
    """Send the critic's findings back to the architect for one revision round."""
    ctx.state[STATE_REVISIONS] = int(ctx.state.get(STATE_REVISIONS, 0)) + 1
    ctx.state[STATE_ROUND_ATTEMPTS] = 0
    review = CriticReport.model_validate(ctx.state.get(STATE_REVIEW, {}))
    unmet = (
        "\n".join(
            f"- {c.obligation_id} is {c.status}: {c.reason}"
            for c in review.obligation_checks
            if c.status != "met"
        )
        or "- none"
    )
    findings = (
        "\n".join(f"- [{f.severity}] {f.problem} Fix: {f.fix}" for f in review.findings) or "- none"
    )
    return (
        "A senior architect reviewed your design. Return the complete revised architecture as "
        "JSON in the same schema. Address every unmet obligation and every blocking or major "
        "finding with real elements and relations, update the fulfilments, and keep what was "
        "already right.\n\n"
        f"## Obligations not yet met\n{unmet}\n\n"
        f"## Review findings\n{findings}\n\n"
        f"## Your previous architecture\n{_dump(node_input)}\n\n" + _requirements_block(ctx)
    )


def render_diagram(ctx: Context, node_input: ArchitectureModel) -> dict[str, Any]:
    """Final node: the model, its Mermaid source, and everything the reviewers found."""
    return {
        "model": json.loads(node_input.model_dump_json()),
        "mermaid": to_mermaid(node_input),
        "validation_errors": ctx.state.get(STATE_ERRORS, []),
        "analysis": ctx.state.get(STATE_ANALYSIS),
        "review": ctx.state.get(STATE_REVIEW),
    }


# ---------------------------------------------------------------------------------------------
# LLM agents and the graphs.
# ---------------------------------------------------------------------------------------------


def build_requirements_analyst(model: str | BaseLlm) -> Agent:
    return Agent(
        name=ANALYST_NAME,
        model=with_retries(model),
        retry_config=NODE_RETRY,
        description="Turns raw requirements into data classes and checkable design obligations.",
        instruction=_prompt(ANALYST_NAME),
        output_schema=RequirementsAnalysis,
    )


def build_requirements_to_architecture(model: str | BaseLlm) -> Agent:
    return Agent(
        name=ARCHITECT_NAME,
        model=with_retries(model),
        retry_config=NODE_RETRY,
        description="Designs a traceable C4 container model that meets the obligations.",
        instruction=_prompt(ARCHITECT_NAME),
        output_schema=ArchitectureModel,
        output_key=STATE_ARCHITECTURE,
    )


def build_architecture_critic(model: str | BaseLlm) -> Agent:
    return Agent(
        name=CRITIC_NAME,
        model=with_retries(model),
        retry_config=NODE_RETRY,
        description="Checks each obligation against the actual boxes and arrows.",
        instruction=_prompt(CRITIC_NAME),
        output_schema=CriticReport,
    )


def build_pipeline(model: str | BaseLlm) -> Workflow:
    """The ArchDraft v2 pipeline. Add future agents as nodes in `edges`."""
    analyst = build_requirements_analyst(model)
    architect = build_requirements_to_architecture(model)
    critic = build_architecture_critic(model)
    return Workflow(
        name=PIPELINE_NAME,
        description="Requirements -> obligations -> reviewed, traceable architecture -> diagram.",
        edges=[
            (
                START,
                prepare_input,
                analyst,
                build_architect_request,
                architect,
                validate_architecture,
            ),
            (
                validate_architecture,
                {
                    REPAIR: build_repair_request,
                    REVIEW: build_review_request,
                    ACCEPT: render_diagram,
                },
            ),
            (build_repair_request, architect),
            (build_review_request, critic, review_router),
            (review_router, {REVISE: build_revision_request, ACCEPT: render_diagram}),
            (build_revision_request, architect),
        ],
    )


def build_single_agent(model: str | BaseLlm) -> Workflow:
    """The v1 graph (one architect agent + deterministic validator), kept for evaluation."""
    architect = build_requirements_to_architecture(model)
    return Workflow(
        name=SINGLE_AGENT_NAME,
        description="v1: one architect agent, validated and repaired once.",
        edges=[
            (START, prepare_input, architect, validate_architecture),
            (validate_architecture, {REPAIR: build_repair_request, ACCEPT: render_diagram}),
            (build_repair_request, architect),
        ],
    )


def build_baseline(model: str | BaseLlm) -> Workflow:
    """The naive comparison: one prompt, straight to Mermaid, no schema, no validation."""
    naive = Agent(
        name=BASELINE_NAME,
        model=with_retries(model),
        retry_config=NODE_RETRY,
        description="Single naive prompt asking directly for a Mermaid diagram.",
        instruction=_prompt("baseline"),
    )
    return Workflow(name="archdraft_baseline", edges=[(START, naive)])


def build_judge(model: str | BaseLlm) -> Workflow:
    """Independent examiner used only for evaluation: grades any diagram against obligations."""
    judge = Agent(
        name=JUDGE_NAME,
        model=with_retries(model),
        retry_config=NODE_RETRY,
        description="Grades a Mermaid diagram against fixed design obligations.",
        instruction=_prompt("judge"),
        output_schema=JudgeReport,
    )
    return Workflow(name="archdraft_judge", edges=[(START, judge)])
