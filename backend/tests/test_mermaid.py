from archdraft.render.mermaid import escape_label, mermaid_node_ids, to_mermaid
from archdraft.schema import ArchitectureModel, Element, Relation


def test_starts_with_flowchart_and_is_deterministic(model: ArchitectureModel) -> None:
    source = to_mermaid(model)
    assert source.startswith("flowchart TB\n")
    assert source == to_mermaid(model)


def test_every_element_and_relation_is_drawn(model: ArchitectureModel) -> None:
    source = to_mermaid(model)
    ids = mermaid_node_ids(model)
    for element in model.elements:
        assert f"class {ids[element.id]} {element.kind}" in source
    assert source.count("-->|") == len(model.relations)


def test_shapes_follow_element_kind(model: ArchitectureModel) -> None:
    source = to_mermaid(model)
    assert 'n_member(["<b>Member</b>' in source
    assert 'n_catalogue_db[("<b>Catalogue DB</b>' in source
    assert 'n_web_app["<b>Web App</b>' in source


def test_components_and_datastores_sit_inside_the_system_boundary(model: ArchitectureModel) -> None:
    lines = to_mermaid(model).splitlines()
    start = lines.index('  subgraph boundary["Library System"]')
    end = lines.index("  end")
    inside = "\n".join(lines[start:end])
    assert "n_web_app" in inside and "n_catalogue_db" in inside
    assert "n_member" not in inside and "n_email" not in inside


def test_requirement_ids_are_shown_on_nodes(model: ArchitectureModel) -> None:
    source = to_mermaid(model)
    assert "<i>PostgreSQL 16</i><br/>FR-02, FR-03, NFR-02" in source
    # More than four IDs are summarised.
    assert "FR-01, FR-02, FR-03, FR-04 +1" in source


def test_untraced_element_and_relation_are_flagged(model: ArchitectureModel) -> None:
    model.elements[2].satisfies = []
    model.relations[3].satisfies = ["FR-99"]  # unknown ID counts as untraced
    source = to_mermaid(model)
    assert "class n_web_app flagged" in source
    assert "no requirement cited" in source
    assert "linkStyle 3 " in source


def test_relation_to_unknown_element_is_skipped_not_invented(model: ArchitectureModel) -> None:
    model.relations.append(
        Relation(
            id="bad",
            source="library-api",
            target="ghost",
            description="x",
            protocol=None,
            satisfies=["FR-01"],
        )
    )
    source = to_mermaid(model)
    assert "ghost" not in source.replace("%% skipped relation bad", "")
    assert "%% skipped relation bad" in source


def test_labels_are_escaped() -> None:
    assert escape_label('Say "hi" <now> #1') == "Say #quot;hi#quot; #lt;now#gt; #35;1"
    assert escape_label("multi\nline   text") == "multi line text"


def test_node_ids_are_safe_and_unique(model: ArchitectureModel) -> None:
    model.elements.append(
        Element(
            id="web_app",
            name="Clash",
            kind="component",
            technology=None,
            responsibility="r",
            satisfies=["FR-01"],
            confidence=1,
        )
    )
    model.elements.append(
        Element(
            id="end",
            name="Keyword",
            kind="component",
            technology=None,
            responsibility="r",
            satisfies=["FR-01"],
            confidence=1,
        )
    )
    ids = mermaid_node_ids(model)
    assert ids["web-app"] == "n_web_app"
    assert ids["web_app"] == "n_web_app_2"
    assert ids["end"] == "n_end"
    assert len(set(ids.values())) == len(ids)
