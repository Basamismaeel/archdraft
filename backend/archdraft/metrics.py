"""Numbers shown in the report strip and in the baseline-vs-ArchDraft comparison.

Pipeline numbers come from the structured model. Baseline numbers come from the Mermaid text,
because the naive baseline has no structured model; those are keyword and ID matches, and the
UI labels them that way.
"""

import re

from pydantic import BaseModel

from archdraft.schema import ArchitectureModel
from archdraft.validation.rules import (
    REQUIREMENT_ID_PATTERN,
    normalise_requirement_id,
    requirement_ids_in_text,
)


class Coverage(BaseModel):
    covered: int
    total: int
    percent: float
    uncovered: list[str]
    basis: str


class DiagramStats(BaseModel):
    elements: int
    relations: int
    traced_elements: int
    datastore_nodes: int
    datastore_technologies: list[str]
    basis: str


# Canonical name -> lowercase patterns. Used for both modes so the comparison is like for like.
DATASTORE_TECHNOLOGIES: dict[str, list[str]] = {
    "PostgreSQL": [r"postgre", r"\bpg\b", r"aurora postgres"],
    "MySQL": [r"mysql", r"mariadb", r"aurora mysql"],
    "SQL Server": [r"sql server", r"\bmssql\b", r"azure sql"],
    "Oracle": [r"oracle"],
    "SQLite": [r"sqlite"],
    "MongoDB": [r"mongo"],
    "DynamoDB": [r"dynamo"],
    "Cassandra": [r"cassandra", r"scylla"],
    "Couchbase/CouchDB": [r"couch"],
    "Firestore": [r"firestore", r"firebase"],
    "Cosmos DB": [r"cosmos"],
    "Redis": [r"redis", r"valkey", r"elasticache"],
    "Memcached": [r"memcache"],
    "Elasticsearch/OpenSearch": [r"elastic ?search", r"opensearch"],
    "Solr": [r"\bsolr\b"],
    "Algolia": [r"algolia"],
    "Meilisearch/Typesense": [r"meilisearch", r"typesense"],
    "Neo4j": [r"neo4j"],
    "Object storage": [
        r"\bs3\b",
        r"blob storage",
        r"cloud storage",
        r"\bgcs\b",
        r"minio",
        r"object stor",
    ],
    "ClickHouse": [r"clickhouse"],
    "BigQuery": [r"bigquery"],
    "Snowflake": [r"snowflake"],
    "Cloud Spanner": [r"spanner"],
    "Bigtable/HBase": [r"bigtable", r"hbase"],
    "Time-series DB": [r"influx", r"timescale"],
}
_COMPILED = {
    name: [re.compile(p) for p in patterns] for name, patterns in DATASTORE_TECHNOLOGIES.items()
}
_GENERIC_DB = re.compile(r"\b(database|db|datastore|data store|storage|cache|index)\b")


def detect_technologies(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(
        name for name, patterns in _COMPILED.items() if any(p.search(lowered) for p in patterns)
    )


def model_coverage(model: ArchitectureModel, source_text: str | None = None) -> Coverage:
    """Covered = cited by at least one element or relation. Total includes IDs the input
    labelled even if the model dropped them, so dropping a requirement cannot raise the score."""
    all_ids: list[str] = []
    for rid in [r.id for r in model.requirements] + requirement_ids_in_text(source_text or ""):
        norm = normalise_requirement_id(rid)
        if norm not in all_ids:
            all_ids.append(norm)
    cited = {normalise_requirement_id(r) for e in model.elements for r in e.satisfies}
    cited |= {normalise_requirement_id(r) for rel in model.relations for r in rel.satisfies}
    covered = [rid for rid in all_ids if rid in cited]
    uncovered = [rid for rid in all_ids if rid not in cited]
    total = len(all_ids)
    return Coverage(
        covered=len(covered),
        total=total,
        percent=round(100 * len(covered) / total, 1) if total else 0.0,
        uncovered=uncovered,
        basis="requirements cited by at least one element or relation",
    )


def model_stats(model: ArchitectureModel) -> DiagramStats:
    known = {normalise_requirement_id(r.id) for r in model.requirements}
    datastores = [e for e in model.elements if e.kind == "datastore"]
    techs = detect_technologies(" | ".join(e.technology or "" for e in datastores))
    # A technology the keyword list does not know still counts, under its own name.
    for e in datastores:
        if e.technology and not detect_technologies(e.technology):
            techs.append(e.technology)
    return DiagramStats(
        elements=len(model.elements),
        relations=len(model.relations),
        traced_elements=sum(
            1
            for e in model.elements
            if any(normalise_requirement_id(r) in known for r in e.satisfies)
        ),
        datastore_nodes=len(datastores),
        datastore_technologies=sorted(set(techs)),
        basis="structured model",
    )


# --- Baseline (free-text Mermaid) ------------------------------------------------------------

_NODE_DEF = re.compile(
    r"(?<![\w-])([A-Za-z_]\w*)\s*(\[\(|\(\(|\(\[|\[\[|\[/|\[\\|\[|\(|\{\{|\{)(.+?)"
    r"(\)\]|\)\)|\]\)|\]\]|/\]|\\\]|\]|\)|\}\}|\})"
)
_EDGE = re.compile(r"(-->|---|-\.->|-\.-|==>|===|--[^->]*-->|--o|--x|<-->)")


def extract_mermaid(text: str) -> str:
    """Pull the diagram out of a free-text LLM answer (fenced block if present)."""
    fenced = re.search(r"```(?:mermaid)?\s*\n(.*?)```", text, re.DOTALL)
    return (fenced.group(1) if fenced else text).strip() + "\n"


def mermaid_text_stats(mermaid: str) -> DiagramStats:
    nodes: dict[str, tuple[str, str]] = {}
    edges = 0
    for raw in mermaid.splitlines():
        line = raw.strip()
        if not line or line.startswith(
            ("%%", "classDef", "class ", "style ", "linkStyle", "click")
        ):
            continue
        if line.startswith(("subgraph", "end", "flowchart", "graph", "direction")):
            continue
        edges += len(_EDGE.findall(line))
        for node_id, opening, label, _closing in _NODE_DEF.findall(line):
            nodes.setdefault(node_id, (opening, label))
    datastore_nodes = sum(
        1
        for opening, label in nodes.values()
        if opening == "[(" or detect_technologies(label) or _GENERIC_DB.search(label.lower())
    )
    traced = sum(1 for _, label in nodes.values() if REQUIREMENT_ID_PATTERN.search(label))
    return DiagramStats(
        elements=len(nodes),
        relations=edges,
        traced_elements=traced,
        datastore_nodes=datastore_nodes,
        datastore_technologies=detect_technologies(mermaid),
        basis="parsed from Mermaid text (keyword match)",
    )


_ID_SHORTHAND = re.compile(r"\b(N?FR)-(\d+)((?:\s*/\s*\d+)+)", re.IGNORECASE)


def mentioned_requirement_ids(text: str) -> set[str]:
    """IDs written anywhere in free text, including shorthand such as "FR-08/09"."""
    found = {normalise_requirement_id(m.group(0)) for m in REQUIREMENT_ID_PATTERN.finditer(text)}
    for m in _ID_SHORTHAND.finditer(text):
        for number in re.findall(r"\d+", m.group(3)):
            found.add(normalise_requirement_id(f"{m.group(1)}-{number}"))
    return found


def text_coverage(mermaid: str, source_text: str) -> Coverage:
    """Baseline coverage: requirement IDs from the input that appear anywhere in the diagram."""
    ids = requirement_ids_in_text(source_text)
    mentioned = mentioned_requirement_ids(mermaid)
    covered = [rid for rid in ids if rid in mentioned]
    return Coverage(
        covered=len(covered),
        total=len(ids),
        percent=round(100 * len(covered) / len(ids), 1) if ids else 0.0,
        uncovered=[rid for rid in ids if rid not in mentioned],
        basis="requirement IDs mentioned anywhere in the diagram",
    )
