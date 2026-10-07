from archdraft.schema import ArchitectureModel, Element, Relation, Unresolved
from archdraft.validation.rules import (
    normalise_requirement_id,
    requirement_ids_in_text,
    validate_model,
)
from tests.conftest import LIBRARY_REQUIREMENTS


def rules_of(model: ArchitectureModel, source: str | None = None) -> list[str]:
    return [e.rule for e in validate_model(model, source)]


def test_valid_model_has_no_errors(model: ArchitectureModel) -> None:
    assert validate_model(model, LIBRARY_REQUIREMENTS) == []


def test_rule1_relation_endpoint_must_exist(model: ArchitectureModel) -> None:
    model.relations[0].target = "ghost"
    errors = validate_model(model)
    endpoint = [e for e in errors if e.rule == "relation_endpoint_exists"]
    assert len(endpoint) == 1
    assert endpoint[0].element_id == "member-web"
    assert "ghost" in endpoint[0].message


def test_rule2_isolated_element(model: ArchitectureModel) -> None:
    model.elements.append(
        Element(
            id="cache",
            name="Cache",
            kind="datastore",
            technology="Redis",
            responsibility="x",
            satisfies=["NFR-01"],
            confidence=0.5,
        )
    )
    errors = [e for e in validate_model(model) if e.rule == "no_isolated_element"]
    assert [e.element_id for e in errors] == ["cache"]


def test_rule2_single_element_is_not_isolated() -> None:
    lone = ArchitectureModel(
        system_name="s",
        system_description="d",
        requirements=[{"id": "FR-01", "text": "t", "kind": "functional"}],
        elements=[
            Element(
                id="app",
                name="App",
                kind="container",
                technology=None,
                responsibility="r",
                satisfies=["FR-01"],
                confidence=1,
            )
        ],
        relations=[],
        unresolved=[],
    )
    assert validate_model(lone) == []


def test_rule2_relation_to_missing_element_does_not_count_as_connection(
    model: ArchitectureModel,
) -> None:
    model.relations = [r for r in model.relations if r.id != "api-email"]
    model.relations.append(
        Relation(
            id="email-ghost",
            source="email",
            target="ghost",
            description="x",
            protocol=None,
            satisfies=["FR-04"],
        )
    )
    errors = validate_model(model)
    assert "email" in [e.element_id for e in errors if e.rule == "no_isolated_element"]


def test_rule3_untraced_element_and_relation(model: ArchitectureModel) -> None:
    model.elements[2].satisfies = []
    model.relations[2].satisfies = []
    rules = rules_of(model)
    assert "element_traced" in rules
    assert "relation_traced" in rules


def test_rule4_unknown_requirement_id(model: ArchitectureModel) -> None:
    model.elements[3].satisfies.append("FR-99")
    errors = [e for e in validate_model(model) if e.rule == "known_requirement_id"]
    assert len(errors) == 1
    assert errors[0].requirement_id == "FR-99"
    assert errors[0].element_id == "library-api"


def test_rule4_id_formatting_differences_are_not_errors(model: ArchitectureModel) -> None:
    model.elements[3].satisfies = ["fr-1", "FR-002", "FR-03", "FR-04", "NFR-1"]
    assert "known_requirement_id" not in rules_of(model)


def test_rule5_requirement_not_accounted_for(model: ArchitectureModel) -> None:
    for owner in [*model.elements, *model.relations]:
        owner.satisfies = [r for r in owner.satisfies if r != "FR-04"] or ["FR-01"]
    errors = [e for e in validate_model(model) if e.rule == "requirement_accounted_for"]
    assert [e.requirement_id for e in errors] == ["FR-04"]


def test_rule5_unresolved_counts_as_accounted_for(model: ArchitectureModel) -> None:
    for owner in [*model.elements, *model.relations]:
        owner.satisfies = [r for r in owner.satisfies if r != "FR-04"] or ["FR-01"]
    model.unresolved.append(Unresolved(requirement_id="FR-04", reason="No mail provider named."))
    assert "requirement_accounted_for" not in rules_of(model)


def test_rule6_duplicate_element_ids(model: ArchitectureModel) -> None:
    model.elements.append(model.elements[2].model_copy())
    errors = [e for e in validate_model(model) if e.rule == "unique_element_id"]
    assert [e.element_id for e in errors] == ["web-app"]


def test_rule7_dropped_input_requirement(model: ArchitectureModel) -> None:
    source = LIBRARY_REQUIREMENTS + "NFR-03: Works on mobile browsers.\n"
    errors = [e for e in validate_model(model, source) if e.rule == "input_requirement_kept"]
    assert [e.requirement_id for e in errors] == ["NFR-03"]


def test_requirement_id_helpers() -> None:
    assert normalise_requirement_id("nfr-3") == "NFR-03"
    assert normalise_requirement_id("FR-012") == "FR-12"
    assert requirement_ids_in_text("intro FR-09 mentioned\nFR-1: a\n - NFR-02 b\nFR-01 again") == [
        "FR-01",
        "NFR-02",
    ]


def test_rule8_datastore_must_be_written(model: ArchitectureModel) -> None:
    model.relations[3].operation = "reads"  # api only reads the catalogue now
    errors = [e for e in validate_model(model) if e.rule == "datastore_written"]
    assert [e.element_id for e in errors] == ["catalogue-db"]


def test_rule8_publishing_into_a_queue_counts_as_writing(model: ArchitectureModel) -> None:
    model.elements.append(
        Element(
            id="queue",
            name="Queue",
            kind="datastore",
            technology="RabbitMQ",
            responsibility="r",
            satisfies=["FR-04"],
            confidence=0.8,
        )
    )
    model.relations.append(
        Relation(
            id="api-queue",
            source="library-api",
            target="queue",
            description="d",
            protocol="AMQP",
            operation="publishes",
            satisfies=["FR-04"],
        )
    )
    assert "datastore_written" not in rules_of(model)


def test_rule9_obligation_must_be_addressed() -> None:
    from tests.conftest import library_analysis, library_model_with_fulfilments

    model = library_model_with_fulfilments()
    obligations = library_analysis().obligations
    assert validate_model(model, LIBRARY_REQUIREMENTS, obligations) == []

    model.fulfilments = model.fulfilments[:1]
    errors = [
        e for e in validate_model(model, None, obligations) if e.rule == "obligation_addressed"
    ]
    assert len(errors) == 1 and "OB-02" in errors[0].message


def test_rule10_fulfilment_must_reference_real_parts() -> None:
    from tests.conftest import library_model_with_fulfilments

    model = library_model_with_fulfilments()
    model.fulfilments[0].element_ids.append("ghost-index")
    errors = [e for e in validate_model(model) if e.rule == "fulfilment_reference"]
    assert [e.element_id for e in errors] == ["ghost-index"]


def test_rule11_blanket_citation_is_a_warning(model: ArchitectureModel) -> None:
    for i in range(6):
        model.elements.append(
            Element(
                id=f"svc-{i}",
                name=f"Svc {i}",
                kind="container",
                technology=None,
                responsibility="r",
                satisfies=["NFR-02"],
                confidence=0.5,
            )
        )
    for e in model.elements[:4]:
        e.satisfies.append("NFR-02")
    warnings = [e for e in validate_model(model) if e.rule == "blanket_citation"]
    assert [w.requirement_id for w in warnings] == ["NFR-02"]
    assert warnings[0].severity == "warning"
