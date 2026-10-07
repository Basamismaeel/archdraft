"""Shared fixtures: a hand-written model and an offline stub LLM. No test calls a live API."""

from collections.abc import AsyncGenerator, Iterator
from pathlib import Path

import pytest
from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from archdraft import config
from archdraft.schema import (
    ArchitectureModel,
    CriticReport,
    JudgeReport,
    RequirementsAnalysis,
)

LIBRARY_REQUIREMENTS = """\
FR-01: Members can search the catalogue by title, author or ISBN.
FR-02: Librarians can add, edit and remove books.
FR-03: Members can borrow and return books.
FR-04: The system emails members when a loan is overdue.
NFR-01: Catalogue search responds within 1 second.
NFR-02: Loan history is kept for 5 years.
"""


def library_model() -> ArchitectureModel:
    return ArchitectureModel.model_validate(
        {
            "system_name": "Library System",
            "system_description": "Catalogue and loans for a public library.",
            "requirements": [
                {"id": "FR-01", "text": "Search the catalogue", "kind": "functional"},
                {"id": "FR-02", "text": "Manage books", "kind": "functional"},
                {"id": "FR-03", "text": "Borrow and return", "kind": "functional"},
                {"id": "FR-04", "text": "Overdue emails", "kind": "functional"},
                {"id": "NFR-01", "text": "Search within 1 s", "kind": "non_functional"},
                {"id": "NFR-02", "text": "Keep loans 5 years", "kind": "non_functional"},
            ],
            "elements": [
                {
                    "id": "member",
                    "name": "Member",
                    "kind": "person",
                    "technology": None,
                    "responsibility": "Searches and borrows books.",
                    "satisfies": ["FR-01", "FR-03"],
                    "confidence": 1.0,
                },
                {
                    "id": "librarian",
                    "name": "Librarian",
                    "kind": "person",
                    "technology": None,
                    "responsibility": "Maintains the catalogue.",
                    "satisfies": ["FR-02"],
                    "confidence": 1.0,
                },
                {
                    "id": "web-app",
                    "name": "Web App",
                    "kind": "container",
                    "technology": "React",
                    "responsibility": "UI for members and librarians.",
                    "satisfies": ["FR-01", "FR-02", "FR-03"],
                    "confidence": 0.9,
                },
                {
                    "id": "library-api",
                    "name": "Library API",
                    "kind": "container",
                    "technology": "FastAPI",
                    "responsibility": "Catalogue and loan logic.",
                    "satisfies": ["FR-01", "FR-02", "FR-03", "FR-04", "NFR-01"],
                    "confidence": 0.9,
                },
                {
                    "id": "catalogue-db",
                    "name": "Catalogue DB",
                    "kind": "datastore",
                    "technology": "PostgreSQL 16",
                    "responsibility": "Books, members, loans.",
                    "satisfies": ["FR-02", "FR-03", "NFR-02"],
                    "confidence": 0.9,
                },
                {
                    "id": "email",
                    "name": "Email Service",
                    "kind": "external",
                    "technology": "SendGrid",
                    "responsibility": "Delivers reminder emails.",
                    "satisfies": ["FR-04"],
                    "confidence": 0.8,
                },
            ],
            "relations": [
                {
                    "id": "member-web",
                    "source": "member",
                    "target": "web-app",
                    "description": "searches and borrows",
                    "protocol": "HTTPS",
                    "satisfies": ["FR-01", "FR-03"],
                },
                {
                    "id": "librarian-web",
                    "source": "librarian",
                    "target": "web-app",
                    "description": "manages books",
                    "protocol": "HTTPS",
                    "satisfies": ["FR-02"],
                },
                {
                    "id": "web-api",
                    "source": "web-app",
                    "target": "library-api",
                    "description": "calls",
                    "protocol": "HTTPS/JSON",
                    "satisfies": ["FR-01", "FR-02", "FR-03"],
                },
                {
                    "id": "api-db",
                    "source": "library-api",
                    "target": "catalogue-db",
                    "operation": "reads_writes",
                    "description": "reads and writes",
                    "protocol": "SQL",
                    "satisfies": ["FR-01", "FR-03", "NFR-02"],
                },
                {
                    "id": "api-email",
                    "source": "library-api",
                    "target": "email",
                    "description": "sends overdue reminders",
                    "protocol": "HTTPS",
                    "satisfies": ["FR-04"],
                },
            ],
            "unresolved": [],
        }
    )


def library_analysis() -> RequirementsAnalysis:
    model = library_model()
    return RequirementsAnalysis.model_validate(
        {
            "system_name": "Library System",
            "system_description": "Catalogue and loans for a public library.",
            "requirements": [r.model_dump() for r in model.requirements],
            "actors": ["Member", "Librarian", "Email provider"],
            "data_classes": [
                {
                    "name": "catalogue and loans",
                    "requirement_ids": ["FR-02", "FR-03", "NFR-02"],
                    "characteristics": "small, relational, transactional, kept 5 years",
                    "personal_data": True,
                }
            ],
            "obligations": [
                {
                    "id": "OB-01",
                    "requirement_ids": ["FR-01", "NFR-01"],
                    "category": "performance",
                    "statement": "Catalogue search is served by an indexed store.",
                },
                {
                    "id": "OB-02",
                    "requirement_ids": ["FR-04"],
                    "category": "integration",
                    "statement": "Overdue reminders are sent through an email provider.",
                },
            ],
            "ambiguities": [
                {
                    "requirement_id": "FR-04",
                    "issue": "How many reminders?",
                    "assumption": "One email per overdue loan.",
                }
            ],
        }
    )


def library_model_with_fulfilments() -> ArchitectureModel:
    data = library_model().model_dump()
    data["fulfilments"] = [
        {
            "obligation_id": "OB-01",
            "element_ids": ["catalogue-db"],
            "relation_ids": ["api-db"],
            "explanation": "Indexed PostgreSQL tables.",
        },
        {
            "obligation_id": "OB-02",
            "element_ids": ["email"],
            "relation_ids": ["api-email"],
            "explanation": "API calls SendGrid.",
        },
    ]
    return ArchitectureModel.model_validate(data)


def critic_report(status: str = "met", findings: int = 0) -> CriticReport:
    return CriticReport.model_validate(
        {
            "obligation_checks": [
                {"obligation_id": "OB-01", "status": status, "reason": "catalogue-db, api-db"},
                {"obligation_id": "OB-02", "status": "met", "reason": "api-email"},
            ],
            "findings": [
                {
                    "severity": "major",
                    "requirement_ids": ["NFR-01"],
                    "element_ids": ["catalogue-db"],
                    "problem": "No search index for a 1 s target.",
                    "fix": "Add a search index fed by the API.",
                }
            ]
            * findings,
        }
    )


class StubLlm(BaseLlm):
    """Answers as whichever agent is asking, chosen by the requested output schema.

    `responses` maps a schema name ("RequirementsAnalysis", "ArchitectureModel", "CriticReport",
    "JudgeReport", or "text" for agents without a schema) to the answers to give, in order;
    the last answer repeats. Every request is recorded."""

    responses: dict[str, list[str]] = {}
    requests: list[LlmRequest] = []

    def requests_for(self, schema: str) -> list[LlmRequest]:
        return [r for r in self.requests if _schema_name(r) == schema]

    async def generate_content_async(
        self, llm_request: LlmRequest, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        self.requests.append(llm_request)
        name = _schema_name(llm_request)
        answers = self.responses[name]
        text = answers[min(len(self.requests_for(name)), len(answers)) - 1]
        yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=text)]))


def _schema_name(request: LlmRequest) -> str:
    schema = request.config.response_schema
    return schema.__name__ if isinstance(schema, type) else "text"


def stub_answers(
    architectures: list[str] | None = None,
    critics: list[str] | None = None,
    baseline: str = "flowchart TD\n  A[App] --> B[(DB)]",
    judge: str | None = None,
) -> dict[str, list[str]]:
    return {
        "RequirementsAnalysis": [library_analysis().model_dump_json()],
        "ArchitectureModel": architectures or [library_model_with_fulfilments().model_dump_json()],
        "CriticReport": critics or [critic_report().model_dump_json()],
        "text": [baseline],
        "JudgeReport": [
            judge
            or JudgeReport(
                obligation_checks=critic_report().obligation_checks,
                unjustified_elements=[],
                illogical_connections=[],
            ).model_dump_json()
        ],
    }


@pytest.fixture
def model() -> ArchitectureModel:
    return library_model()


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    yield tmp_path
