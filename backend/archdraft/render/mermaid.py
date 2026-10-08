"""ArchitectureModel -> Mermaid flowchart source.

Diagrams are always produced here, in code, from the validated model. The LLM never writes
diagram syntax, so broken-syntax output cannot happen, and every node can carry the IDs of the
requirements behind it.
"""

import re

from archdraft.schema import ArchitectureModel, Element, Relation
from archdraft.validation.rules import normalise_requirement_id

MAX_IDS_ON_NODE = 4
MAX_EDGE_LABEL = 42

# Mermaid shape delimiters per element kind (C4-flavoured).
SHAPES: dict[str, tuple[str, str]] = {
    "person": ('(["', '"])'),
    "system": ('[["', '"]]'),
    "component": ('["', '"]'),
    "datastore": ('[("', '")]'),
    "external": ('["', '"]'),
}

CLASS_DEFS = [
    "classDef person fill:#ffffff,stroke:#444444,stroke-width:1px",
    "classDef system fill:#ffffff,stroke:#444444,stroke-width:1px",
    "classDef component fill:#ffffff,stroke:#444444,stroke-width:1px",
    "classDef datastore fill:#f4f4f4,stroke:#444444,stroke-width:1px",
    "classDef external fill:#ffffff,stroke:#999999,stroke-width:1px,"
    "stroke-dasharray:4 3,color:#555555",
    "classDef flagged fill:#fff4f2,stroke:#c0392b,stroke-width:2px,stroke-dasharray:5 3",
]
FLAGGED_LINK_STYLE = "stroke:#c0392b,stroke-width:2px,stroke-dasharray:5 3"

INSIDE_BOUNDARY = {"component", "datastore"}


def escape_label(text: str) -> str:
    """Make arbitrary text safe inside a double-quoted Mermaid label."""
    text = " ".join(text.split())
    return (
        text.replace("#", "#35;").replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")
    )


def mermaid_node_ids(model: ArchitectureModel) -> dict[str, str]:
    """Element.id -> Mermaid node ID. Deterministic, collision-free, never a Mermaid keyword."""
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for element in model.elements:
        if element.id in mapping:
            continue
        base = "n_" + re.sub(r"[^A-Za-z0-9_]", "_", element.id)
        candidate, n = base, 2
        while candidate in used:
            candidate, n = f"{base}_{n}", n + 1
        mapping[element.id] = candidate
        used.add(candidate)
    return mapping


def _traced(satisfies: list[str], known: set[str]) -> bool:
    return any(normalise_requirement_id(rid) in known for rid in satisfies)


def _node_line(element: Element, node_id: str, flagged: bool) -> str:
    lines = [f"<b>{escape_label(element.name)}</b>"]
    if element.technology:
        lines.append(f"<i>{escape_label(element.technology)}</i>")
    if flagged:
        lines.append("no requirement cited")
    else:
        ids = [normalise_requirement_id(r) for r in element.satisfies]
        shown = ", ".join(ids[:MAX_IDS_ON_NODE])
        if len(ids) > MAX_IDS_ON_NODE:
            shown += f" +{len(ids) - MAX_IDS_ON_NODE}"
        lines.append(escape_label(shown))
    opening, closing = SHAPES[element.kind]
    return f"{node_id}{opening}{'<br/>'.join(lines)}{closing}"


def _edge_label(relation: Relation, limit: int) -> str:
    text = relation.description.strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    label = escape_label(text)
    if relation.protocol:
        label += f"<br/>[{escape_label(relation.protocol)}]"
    return label


ASYNC_OPERATIONS = {"publishes", "consumes"}


def to_mermaid(model: ArchitectureModel, max_edge_label: int = MAX_EDGE_LABEL) -> str:
    """Render the model as a Mermaid `flowchart`. Invalid relations are skipped, not invented."""
    ids = mermaid_node_ids(model)
    known = {normalise_requirement_id(r.id) for r in model.requirements}

    seen: set[str] = set()
    elements: list[Element] = []
    for element in model.elements:
        if element.id not in seen:  # duplicates are reported by the validator
            seen.add(element.id)
            elements.append(element)

    out = ["flowchart TB"]
    inside = [e for e in elements if e.kind in INSIDE_BOUNDARY]
    outside = [e for e in elements if e.kind not in INSIDE_BOUNDARY]

    for element in outside:
        out.append(
            "  " + _node_line(element, ids[element.id], not _traced(element.satisfies, known))
        )
    if inside:
        out.append(f'  subgraph boundary["{escape_label(model.system_name)}"]')
        for element in inside:
            flagged = not _traced(element.satisfies, known)
            out.append("    " + _node_line(element, ids[element.id], flagged))
        out.append("  end")

    flagged_links: list[int] = []
    link_index = 0
    for relation in model.relations:
        if relation.source not in ids or relation.target not in ids:
            out.append(f"  %% skipped relation {relation.id}: endpoint is not an element")
            continue
        arrow = "-.->" if relation.operation in ASYNC_OPERATIONS else "-->"
        out.append(
            f"  {ids[relation.source]} {arrow}"
            f'|"{_edge_label(relation, max_edge_label)}"| {ids[relation.target]}'
        )
        if not _traced(relation.satisfies, known):
            flagged_links.append(link_index)
        link_index += 1

    out.extend("  " + line for line in CLASS_DEFS)
    for element in elements:
        css_class = element.kind
        if not _traced(element.satisfies, known):
            css_class = "flagged"
        out.append(f"  class {ids[element.id]} {css_class}")
    if flagged_links:
        out.append(f"  linkStyle {','.join(map(str, flagged_links))} {FLAGGED_LINK_STYLE}")
    return "\n".join(out) + "\n"
