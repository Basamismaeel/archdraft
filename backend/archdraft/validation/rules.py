"""Deterministic checks on an ArchitectureModel. No LLM calls in this module, ever.

Each rule is a plain function returning a list of ValidationError. `validate_model` runs them all.
Rules 1-6 are the checks from the project brief; rule 7 stops the model from silently dropping
requirements that the input labelled, which would otherwise inflate the coverage number.
Rules 8-10 check that the design is coherent, not just cited: every datastore is written by
something, and every design obligation from the requirements analysis is addressed by real
elements and relations. Rule 11 is a warning against blanket citations, which make coverage
look complete without the design actually doing anything for the requirement.

Errors trigger a repair round; warnings are reported but never block.
"""

import re
from collections import Counter
from collections.abc import Callable

from pydantic import BaseModel

from archdraft.schema import ArchitectureModel, Obligation

REQUIREMENT_ID_PATTERN = re.compile(r"\b(N?FR)-(\d+)\b", re.IGNORECASE)


class ValidationError(BaseModel):
    rule: str
    message: str
    element_id: str | None = None
    requirement_id: str | None = None
    severity: str = "error"  # "error" triggers repair; "warning" is reported only


def normalise_requirement_id(raw: str) -> str:
    """FR-1, fr-01 and FR-001 all become FR-01, so formatting differences are not errors."""
    match = REQUIREMENT_ID_PATTERN.fullmatch(raw.strip())
    if not match:
        return raw.strip()
    return f"{match.group(1).upper()}-{int(match.group(2)):02d}"


def requirement_ids_in_text(text: str) -> list[str]:
    """Requirement IDs that appear at the start of a line in free text, in order, deduplicated."""
    ids: list[str] = []
    for line in text.splitlines():
        match = re.match(r"\s*[-*]?\s*(N?FR-\d+)\b", line, re.IGNORECASE)
        if match:
            rid = normalise_requirement_id(match.group(1))
            if rid not in ids:
                ids.append(rid)
    return ids


def _known_ids(model: ArchitectureModel) -> set[str]:
    return {normalise_requirement_id(r.id) for r in model.requirements}


def check_relation_endpoints(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 1: every relation.source and relation.target matches an existing Element.id."""
    element_ids = {e.id for e in model.elements}
    errors: list[ValidationError] = []
    for rel in model.relations:
        for end, value in (("source", rel.source), ("target", rel.target)):
            if value not in element_ids:
                errors.append(
                    ValidationError(
                        rule="relation_endpoint_exists",
                        message=(
                            f"Relation '{rel.id}' has {end} '{value}', which is not an element ID."
                        ),
                        element_id=rel.id,
                    )
                )
    return errors


def check_isolated_elements(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 2: no element is isolated unless it is the only element."""
    if len(model.elements) <= 1:
        return []
    element_ids = {e.id for e in model.elements}
    connected: set[str] = set()
    for rel in model.relations:
        # Only relations that can actually be drawn count as connections.
        if rel.source in element_ids and rel.target in element_ids:
            connected.update((rel.source, rel.target))
    return [
        ValidationError(
            rule="no_isolated_element",
            message=f"Element '{e.id}' has no relations to any other element.",
            element_id=e.id,
        )
        for e in model.elements
        if e.id not in connected
    ]


def check_traced(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 3: every element and relation has a non-empty `satisfies` list."""
    errors = [
        ValidationError(
            rule="element_traced",
            message=f"Element '{e.id}' does not cite any requirement.",
            element_id=e.id,
        )
        for e in model.elements
        if not e.satisfies
    ]
    errors += [
        ValidationError(
            rule="relation_traced",
            message=f"Relation '{r.id}' ({r.source} -> {r.target}) does not cite any requirement.",
            element_id=r.id,
        )
        for r in model.relations
        if not r.satisfies
    ]
    return errors


def check_known_requirement_ids(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 4: every ID cited in `satisfies` (or listed in `unresolved`) is a known requirement."""
    known = _known_ids(model)
    errors: list[ValidationError] = []
    owners: list[tuple[str, list[str]]] = [(e.id, e.satisfies) for e in model.elements]
    owners += [(r.id, r.satisfies) for r in model.relations]
    for owner_id, satisfies in owners:
        for rid in satisfies:
            if normalise_requirement_id(rid) not in known:
                errors.append(
                    ValidationError(
                        rule="known_requirement_id",
                        message=f"'{owner_id}' cites '{rid}', which is not a known requirement.",
                        element_id=owner_id,
                        requirement_id=rid,
                    )
                )
    for item in model.unresolved:
        if normalise_requirement_id(item.requirement_id) not in known:
            errors.append(
                ValidationError(
                    rule="known_requirement_id",
                    message=f"Unresolved entry '{item.requirement_id}' is not a requirement.",
                    requirement_id=item.requirement_id,
                )
            )
    return errors


def check_requirements_accounted_for(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 5: every requirement is cited at least once, or listed in `unresolved`."""
    cited = {normalise_requirement_id(rid) for e in model.elements for rid in e.satisfies}
    cited |= {normalise_requirement_id(rid) for r in model.relations for rid in r.satisfies}
    unresolved = {normalise_requirement_id(u.requirement_id) for u in model.unresolved}
    return [
        ValidationError(
            rule="requirement_accounted_for",
            message=(
                f"Requirement '{req.id}' is not satisfied by any element or relation "
                "and is not listed as unresolved."
            ),
            requirement_id=req.id,
        )
        for req in model.requirements
        if normalise_requirement_id(req.id) not in cited | unresolved
    ]


def check_duplicate_element_ids(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 6: no duplicate element IDs."""
    counts = Counter(e.id for e in model.elements)
    return [
        ValidationError(
            rule="unique_element_id",
            message=f"Element ID '{eid}' is used {n} times.",
            element_id=eid,
        )
        for eid, n in counts.items()
        if n > 1
    ]


def check_input_requirements_kept(
    model: ArchitectureModel, source_text: str
) -> list[ValidationError]:
    """Rule 7: requirement IDs written in the input all appear in the model's requirement list."""
    known = _known_ids(model)
    return [
        ValidationError(
            rule="input_requirement_kept",
            message=f"Requirement '{rid}' is in the input but missing from the model.",
            requirement_id=rid,
        )
        for rid in requirement_ids_in_text(source_text)
        if rid not in known
    ]


WRITE_OPERATIONS = {"writes", "reads_writes", "publishes"}
# A requirement legitimately appears on every hop of its own path (person -> app -> API ->
# store), so it is only "blanket" when it is cited by more than half of all elements and by
# more elements than any plausible path has.
BLANKET_SHARE = 0.5
BLANKET_MIN_COUNT = 6
MAX_CITATIONS_PER_ELEMENT = 9


def check_datastores_written(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 8: every datastore receives data: some relation writes or publishes into it.

    A store that is only ever read (for example a search index nobody indexes into) is a
    missing data flow."""
    written = {r.target for r in model.relations if r.operation in WRITE_OPERATIONS}
    # A consumer that reads from a queue or a CDN pulling from storage does not fill it.
    return [
        ValidationError(
            rule="datastore_written",
            message=(
                f"Datastore '{e.id}' is never written to: no relation writes or publishes "
                "into it, so the design does not say how its data gets there."
            ),
            element_id=e.id,
        )
        for e in model.elements
        if e.kind == "datastore" and e.id not in written
    ]


def check_obligations_addressed(
    model: ArchitectureModel, obligations: list[Obligation]
) -> list[ValidationError]:
    """Rule 9: every design obligation has a fulfilment that names real elements or relations."""
    element_ids = {e.id for e in model.elements}
    relation_ids = {r.id for r in model.relations}
    by_id = {f.obligation_id.strip().upper(): f for f in model.fulfilments}
    errors: list[ValidationError] = []
    for ob in obligations:
        fulfilment = by_id.get(ob.id.strip().upper())
        real = (
            [e for e in fulfilment.element_ids if e in element_ids]
            + [r for r in fulfilment.relation_ids if r in relation_ids]
            if fulfilment
            else []
        )
        if not real:
            errors.append(
                ValidationError(
                    rule="obligation_addressed",
                    message=f"Obligation {ob.id} is not addressed by the design: {ob.statement}",
                    requirement_id=ob.requirement_ids[0] if ob.requirement_ids else None,
                )
            )
    return errors


def check_fulfilment_references(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 10: fulfilments only name elements and relations that exist."""
    element_ids = {e.id for e in model.elements}
    relation_ids = {r.id for r in model.relations}
    errors: list[ValidationError] = []
    for f in model.fulfilments:
        for ref in [e for e in f.element_ids if e not in element_ids] + [
            r for r in f.relation_ids if r not in relation_ids
        ]:
            errors.append(
                ValidationError(
                    rule="fulfilment_reference",
                    message=f"Fulfilment of {f.obligation_id} names '{ref}', which does not exist.",
                    element_id=ref,
                )
            )
    return errors


def check_blanket_citations(model: ArchitectureModel) -> list[ValidationError]:
    """Rule 11 (warning): citations that are everywhere carry no information."""
    warnings: list[ValidationError] = []
    n = len(model.elements)
    if n:
        counts = Counter(
            normalise_requirement_id(r) for e in model.elements for r in set(e.satisfies)
        )
        for rid, count in sorted(counts.items()):
            if count / n > BLANKET_SHARE and count >= BLANKET_MIN_COUNT:
                warnings.append(
                    ValidationError(
                        rule="blanket_citation",
                        message=(
                            f"{rid} is cited by {count} of {n} elements. Cite it only where an "
                            "element actually does something for it."
                        ),
                        requirement_id=rid,
                        severity="warning",
                    )
                )
    for e in model.elements:
        if len(set(e.satisfies)) > MAX_CITATIONS_PER_ELEMENT and e.kind != "person":
            warnings.append(
                ValidationError(
                    rule="over_citation",
                    message=(
                        f"'{e.id}' cites {len(set(e.satisfies))} requirements; a box that "
                        "serves everything explains nothing. Consider splitting it."
                    ),
                    element_id=e.id,
                    severity="warning",
                )
            )
    return warnings


MODEL_RULES: list[Callable[[ArchitectureModel], list[ValidationError]]] = [
    check_relation_endpoints,
    check_isolated_elements,
    check_traced,
    check_known_requirement_ids,
    check_requirements_accounted_for,
    check_duplicate_element_ids,
    check_datastores_written,
    check_fulfilment_references,
    check_blanket_citations,
]


def validate_model(
    model: ArchitectureModel,
    source_text: str | None = None,
    obligations: list[Obligation] | None = None,
) -> list[ValidationError]:
    """Run every rule. Pass the original text to run rule 7, and obligations to run rule 9."""
    errors: list[ValidationError] = []
    for rule in MODEL_RULES:
        errors.extend(rule(model))
    if source_text:
        errors.extend(check_input_requirements_kept(model, source_text))
    if obligations:
        errors.extend(check_obligations_addressed(model, obligations))
    return errors


def blocking(errors: list[ValidationError]) -> list[ValidationError]:
    return [e for e in errors if e.severity == "error"]
