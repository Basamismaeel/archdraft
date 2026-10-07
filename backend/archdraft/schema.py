"""The canonical architecture model: the contract between the agent, validator, renderer and UI.

The LLM returns exactly this shape (via ADK structured output). Field descriptions are sent to
the model as part of the response schema, so they double as instructions.
"""

from typing import Literal

from pydantic import BaseModel, Field


class Element(BaseModel):
    id: str = Field(description='Lowercase slug, unique in the model, e.g. "listing-api".')
    name: str = Field(description="Human-readable name shown in the diagram.")
    kind: Literal["person", "system", "container", "datastore", "external"] = Field(
        description=(
            "person = a user role; container = a deployable unit of this system "
            "(app, API, worker); datastore = a database, cache, index or object store "
            "of this system; external = a third-party system; system = another system "
            "owned by the same organisation."
        )
    )
    technology: str | None = Field(
        default=None,
        description='Concrete technology, e.g. "PostgreSQL 16". Null for persons.',
    )
    responsibility: str = Field(description="One sentence: what this element does.")
    satisfies: list[str] = Field(
        description='IDs of the requirements that justify this element, e.g. ["FR-03"].'
    )
    confidence: float = Field(
        description="0.0 to 1.0: how strongly the cited requirements demand this element."
    )


class Relation(BaseModel):
    id: str = Field(description='Unique slug, e.g. "web-to-listing-api".')
    source: str = Field(description="Element.id of the caller / sender.")
    target: str = Field(description="Element.id of the callee / receiver.")
    description: str = Field(description='Short verb phrase, e.g. "searches listings".')
    protocol: str | None = Field(default=None, description="e.g. HTTPS/JSON, gRPC, AMQP, SQL.")
    operation: Literal["calls", "reads", "writes", "reads_writes", "publishes", "consumes"] = Field(
        default="calls",
        description=(
            "What the source does to the target: reads/writes/reads_writes for datastores, "
            "publishes/consumes for queues and event brokers, calls for services and externals."
        ),
    )
    satisfies: list[str] = Field(description="IDs of the requirements that imply this relation.")


class Requirement(BaseModel):
    id: str = Field(description="FR-nn for functional, NFR-nn for non-functional.")
    text: str = Field(description="The requirement text, verbatim from the input.")
    kind: Literal["functional", "non_functional"]


class Unresolved(BaseModel):
    requirement_id: str
    reason: str = Field(description="Why no element could be justified for this requirement.")


class Fulfilment(BaseModel):
    obligation_id: str = Field(description="OB-nn from the requirements analysis.")
    element_ids: list[str] = Field(description="Elements that together fulfil the obligation.")
    relation_ids: list[str] = Field(description="Relations that carry the data or calls needed.")
    explanation: str = Field(description="One or two sentences: how the design meets it.")


class ArchitectureModel(BaseModel):
    system_name: str
    system_description: str
    requirements: list[Requirement]
    elements: list[Element]
    relations: list[Relation]
    unresolved: list[Unresolved]
    fulfilments: list[Fulfilment] = Field(
        default_factory=list,
        description="One entry per design obligation, showing where the design meets it.",
    )


# ---------------------------------------------------------------------------------------------
# Requirements analysis (output of the requirements_analyst agent).
# ---------------------------------------------------------------------------------------------


class DataClass(BaseModel):
    name: str = Field(description='A kind of data the system keeps, e.g. "deposit payments".')
    requirement_ids: list[str]
    characteristics: str = Field(
        description="Volume, access pattern, consistency, retention: what decides its store."
    )
    personal_data: bool = Field(description="True if it holds data about identifiable people.")


class Obligation(BaseModel):
    id: str = Field(description="OB-01, OB-02, ...")
    requirement_ids: list[str]
    category: Literal[
        "data_store",
        "data_flow",
        "integration",
        "security",
        "performance",
        "availability",
        "compliance",
        "functional_path",
    ]
    statement: str = Field(
        description=(
            "A concrete design obligation a reviewer can check on a container diagram, e.g. "
            '"Every store holding personal data has a path that erases it on account deletion."'
        )
    )


class Ambiguity(BaseModel):
    requirement_id: str
    issue: str = Field(description="What is unclear or missing.")
    assumption: str = Field(description="The assumption the design makes until it is resolved.")


class RequirementsAnalysis(BaseModel):
    system_name: str
    system_description: str
    requirements: list[Requirement]
    actors: list[str] = Field(description="User roles and external parties named or implied.")
    data_classes: list[DataClass]
    obligations: list[Obligation]
    ambiguities: list[Ambiguity]


# ---------------------------------------------------------------------------------------------
# Review (output of the architecture_critic agent and of the independent judge).
# ---------------------------------------------------------------------------------------------


class ObligationCheck(BaseModel):
    obligation_id: str
    status: Literal["met", "partial", "missing"]
    reason: str = Field(description="One sentence naming the elements or flows that decide it.")


class Finding(BaseModel):
    severity: Literal["blocking", "major", "minor"]
    requirement_ids: list[str]
    element_ids: list[str]
    problem: str
    fix: str = Field(description="A concrete change to the design.")


class CriticReport(BaseModel):
    obligation_checks: list[ObligationCheck]
    findings: list[Finding]


class JudgeReport(BaseModel):
    obligation_checks: list[ObligationCheck]
    unjustified_elements: list[str] = Field(
        description="Names of boxes in the diagram that no requirement needs."
    )
    illogical_connections: list[str] = Field(
        description=(
            'Connections that no requirement needs or that point the wrong way, as "A -> B".'
        )
    )
