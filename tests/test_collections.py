from __future__ import annotations

from wiki_core.collections import (
    collection_cycle_diagnostics,
    collection_membership_basis,
    collection_memberships,
    collection_reference_diagnostics,
    compile_collections,
    relation_cycle_diagnostics,
    validate_collection_declaration,
)


def page(
    page_id: str,
    page_type: str,
    context: str,
    **values: object,
) -> dict[str, object]:
    return {
        "id": page_id,
        "path": f"memories/{page_id}.md",
        "page_type": page_type,
        "context": context,
        "values": values,
    }


def test_typed_collection_defaults_to_same_context_and_star_is_explicit() -> None:
    anchor = page(
        "claims-index",
        "ontology_index",
        "work",
        collection={"member_types": ["claim"]},
    )
    same = page("claim-same", "claim", "work")
    other = page("claim-other", "claim", "personal")

    assert collection_membership_basis(anchor, same) == "collection.member_types"
    assert collection_membership_basis(anchor, other) is None

    anchor["values"] = {
        "collection": {"member_types": ["claim"], "contexts": ["*"]}
    }
    assert collection_membership_basis(anchor, other) == "collection.member_types"


def test_explicit_member_reference_wins_and_records_member_provenance() -> None:
    anchor = page(
        "claims-index",
        "ontology_index",
        "work",
        collection={"member_types": ["claim"], "members": ["claim-a"]},
    )
    member = page("claim-a", "claim", "work", collection_refs=["claims-index"])

    memberships = collection_memberships([anchor, member])

    assert memberships == [
        {
            "member": "claim-a",
            "collection": "claims-index",
            "basis": "member.collection_refs",
            "origin": "member",
            "declaration_page": "claim-a",
            "declaration_path": "memories/claim-a.md",
            "template_type": "",
        }
    ]


def test_explicit_members_and_template_defaults_carry_their_real_origin() -> None:
    manual = page(
        "manual-index",
        "ontology_index",
        "work",
        collection={"members": ["claim-a"]},
    )
    registry = page("source-registry", "source_registry", "system")
    claim = page("claim-a", "claim", "work")
    source = page("source-a", "source", "work")

    memberships = collection_memberships(
        [manual, registry, claim, source],
        defaults_by_type={
            "source_registry": {"member_types": ["source"], "contexts": ["*"]}
        },
    )
    by_pair = {
        (item["member"], item["collection"]): item for item in memberships
    }
    assert by_pair[("claim-a", "manual-index")]["origin"] == "collection_page"
    assert by_pair[("claim-a", "manual-index")]["declaration_page"] == "manual-index"
    assert by_pair[("source-a", "source-registry")]["origin"] == "template_default"
    assert by_pair[("source-a", "source-registry")]["template_type"] == "source_registry"


def test_collection_compilation_reuses_one_membership_inventory_for_diagnostics() -> None:
    pages = [
        page("a", "ontology_index", "work", collection_refs=["b"]),
        page("b", "ontology_index", "work", collection_refs=["a"]),
        page("orphan", "claim", "work", collection_refs=["missing"]),
    ]

    compiled = compile_collections(pages)

    assert {(row["member"], row["collection"]) for row in compiled.memberships} == {
        ("a", "b"),
        ("b", "a"),
    }
    assert [row["code"] for row in compiled.reference_diagnostics] == [
        "unresolved_collection_ref"
    ]
    assert [row["cycle_path"] for row in compiled.cycle_diagnostics] == [
        ["a", "b", "a"]
    ]


def test_invalid_shapes_and_unresolved_references_are_reported() -> None:
    malformed = page(
        "bad-index",
        "ontology_index",
        "work",
        collection_refs="other-index",
        collection={"member_types": "claim", "mystery": []},
    )
    assert validate_collection_declaration(malformed) == [
        "collection_refs must be a list",
        "collection has unknown key `mystery`",
        "collection.member_types must be a list",
    ]

    member = page("claim-a", "claim", "work", collection_refs=["missing-index"])
    anchor = page(
        "claims-index",
        "ontology_index",
        "work",
        collection={"members": ["missing-claim"]},
    )
    assert [item["code"] for item in collection_reference_diagnostics([member, anchor])] == [
        "unresolved_collection_ref",
        "unresolved_collection_member",
    ]


def test_collection_cycle_detector_reports_an_actionable_self_loop() -> None:
    anchor = page(
        "claims-index",
        "ontology_index",
        "work",
        collection_refs=["memories/claims-index.md"],
    )

    diagnostics = collection_cycle_diagnostics([anchor])

    assert diagnostics == [
        {
            "code": "forbidden_collection_cycle",
            "relation_type": "collection_member",
            "cycle_path": ["claims-index", "claims-index"],
            "cycle_path_text": "claims-index -> claims-index",
            "page_paths": [
                "memories/claims-index.md",
                "memories/claims-index.md",
            ],
            "cycle_edges": [
                {
                    "member": "claims-index",
                    "collection": "claims-index",
                    "basis": "member.collection_refs",
                    "origin": "member",
                    "declaration_page": "claims-index",
                    "declaration_path": "memories/claims-index.md",
                    "template_type": "",
                }
            ],
        }
    ]
    # Legacy membership readers keep ignoring an invalid self-membership; the
    # dedicated diagnostic is what makes the authoring defect visible.
    assert collection_memberships([anchor]) == []


def test_collection_cycle_detector_reports_two_and_three_node_paths() -> None:
    two_node = [
        page(
            "a",
            "ontology_index",
            "work",
            collection={"members": ["b"]},
        ),
        page(
            "b",
            "ontology_index",
            "work",
            collection={"members": ["a"]},
        ),
    ]
    three_node = [
        page("a", "ontology_index", "work", collection_refs=["memories/b.md"]),
        page("b", "ontology_index", "work", collection_refs=["c"]),
        page("c", "ontology_index", "work", collection_refs=["memories/a.md"]),
    ]

    assert [
        item["cycle_path"] for item in collection_cycle_diagnostics(two_node)
    ] == [["a", "b", "a"]]
    assert [
        item["cycle_path"] for item in collection_cycle_diagnostics(three_node)
    ] == [["a", "b", "c", "a"]]


def test_collection_cycle_detector_accepts_acyclic_id_and_path_references() -> None:
    pages = [
        page("a", "ontology_index", "work", collection_refs=["memories/b.md"]),
        page("b", "ontology_index", "work", collection_refs=["c"]),
        page("c", "ontology_index", "work"),
    ]

    assert collection_cycle_diagnostics(pages) == []
    assert {
        (item["member"], item["collection"])
        for item in collection_memberships(pages)
    } == {("a", "b"), ("b", "c")}


def test_typed_collection_excludes_its_anchor_without_fabricating_self_cycle() -> None:
    anchor = page(
        "ontology-family",
        "ontology_index",
        "work",
        collection={"member_types": ["ontology_index"]},
    )

    assert collection_memberships([anchor]) == []
    assert collection_cycle_diagnostics([anchor]) == []


def test_typed_collection_cycle_reports_each_real_declaration_basis() -> None:
    pages = [
        page(
            "a",
            "ontology_index",
            "work",
            collection={"member_types": ["ontology_index"]},
        ),
        page(
            "b",
            "ontology_index",
            "work",
            collection={"member_types": ["ontology_index"]},
        ),
    ]

    diagnostics = collection_cycle_diagnostics(pages)

    assert [item["cycle_path"] for item in diagnostics] == [["a", "b", "a"]]
    assert diagnostics[0]["cycle_edges"] == [
        {
            "member": "a",
            "collection": "b",
            "basis": "collection.member_types",
            "origin": "collection_page",
            "declaration_page": "b",
            "declaration_path": "memories/b.md",
            "template_type": "",
        },
        {
            "member": "b",
            "collection": "a",
            "basis": "collection.member_types",
            "origin": "collection_page",
            "declaration_page": "a",
            "declaration_path": "memories/a.md",
            "template_type": "",
        },
    ]


def test_relation_cycle_detector_respects_explicit_vocabulary_permission() -> None:
    edges = [
        {"type": "forbidden", "source": "a", "target": "b"},
        {"type": "forbidden", "source": "b", "target": "a"},
        {"type": "allowed", "source": "a", "target": "b"},
        {"type": "allowed", "source": "b", "target": "a"},
        {"type": "legacy", "source": "a", "target": "a"},
    ]

    assert relation_cycle_diagnostics(
        edges,
        {
            "forbidden": {"allows_cycles": False},
            "allowed": {"allows_cycles": True},
            # Missing metadata remains readable instead of becoming a new
            # implicit hard failure for legacy relation vocabularies.
            "legacy": {},
        },
    ) == [
        {
            "code": "forbidden_relation_cycle",
            "relation_type": "forbidden",
            "cycle_path": ["a", "b", "a"],
            "cycle_path_text": "a -> b -> a",
        }
    ]
