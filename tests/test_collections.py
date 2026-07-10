from __future__ import annotations

from wiki_core.collections import (
    collection_membership_basis,
    collection_memberships,
    collection_reference_diagnostics,
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
