from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from wiki_core.quadrants import quadrant_contract


ROOT = Path(__file__).resolve().parents[1]


def test_context_deep_read_prompt_preserves_aqal_boundaries() -> None:
    prompt = (ROOT / "wiki_core/llm/prompts/context_deep_read.v3.md").read_text(
        encoding="utf-8"
    )
    normalized_prompt = " ".join(prompt.split())

    assert "interior/exterior" in prompt
    assert "individual/collective" in prompt
    assert "`interior_individual` | `I`, interior individual" in prompt
    assert "`exterior_individual` | `It`, exterior individual" in prompt
    assert "`interior_collective` | `We`, interior collective" in prompt
    assert "`exterior_collective` | `Its`, exterior collective" in prompt
    assert "A plain roster, org chart, RACI or workflow assignment" in normalized_prompt
    assert "administered structure as `exterior_collective`" in normalized_prompt


def test_public_quadrant_report_rejects_lossy_entity_bucket_mapping() -> None:
    report = (
        ROOT / "docs/references/reports/aqal-quadrant-alignment-2026-06-25.md"
    ).read_text(encoding="utf-8")

    assert "The current kit does not support the interpretation" in report
    assert "Q3 = any people/roles" in report
    assert "Q2 = any file/repository" in report
    assert "classify the extracted fact in relation to the root holon" in report


def test_methodology_references_do_not_teach_q3_as_plain_people_bucket() -> None:
    proposal = (
        ROOT
        / "docs/references/proposals/integral-root-entity-and-input-stage-refactor-2026-06-25.md"
    ).read_text(encoding="utf-8")
    channel = (ROOT / "memories/system/input-channels/methodology-reference.md").read_text(
        encoding="utf-8"
    )

    assert 'Q3["Q3 - roles, people, culture and relationships"]' not in proposal
    assert 'Q3 --> People["People, roles, responsibilities"]' not in proposal
    assert "| Q1/Q2/Q3/Q4 | identity, artifacts, roles, systems |" not in channel
    assert "shared meaning/roles-as-lived" in channel


def test_root_overlays_preserve_aqal_boundary_when_read_without_base_template() -> None:
    person = (ROOT / "docs/references/templates/wiki/root-person.md").read_text(
        encoding="utf-8"
    )
    team = (ROOT / "docs/references/templates/wiki/root-team.md").read_text(
        encoding="utf-8"
    )
    company = (ROOT / "docs/references/templates/wiki/root-company.md").read_text(
        encoding="utf-8"
    )

    assert "Social contexts are Q3 only" in person
    assert (
        "Communication channels such as email, calendar, Drive and chat are Q4"
        in person
    )
    assert (
        "Team membership, org charts, RACI rows and workflow assignments are not Q3"
        in team
    )
    assert "Repositories, tools and boards are Q2 only" in team
    assert (
        "Units, departments, governance forums and reporting lines are not Q3"
        in company
    )
    assert (
        "Systems of record, CRM/ERP, document systems, support systems, calendars"
        in company
    )


def test_topical_stakeholder_perspective_does_not_define_q3() -> None:
    registry = (ROOT / "memories/system/perspectives/index.md").read_text(
        encoding="utf-8"
    )
    stakeholder = (ROOT / "memories/system/perspectives/stakeholder.md").read_text(
        encoding="utf-8"
    )
    roles = (ROOT / "memories/system/perspectives/roles-relationships.md").read_text(
        encoding="utf-8"
    )

    assert "topical perspectives" in registry
    assert "not the Q3 AQAL contract" in registry
    assert "This is a topical stakeholder perspective, not the Q3 quadrant contract" in stakeholder
    assert "assignments as Q4 unless" in stakeholder
    assert "quadrant: q3" in roles


def test_quadrant_contract_is_authoritative_for_external_consumers() -> None:
    contract = quadrant_contract("en")
    quadrants = contract["quadrants"]

    assert contract["schema_version"] == "wiki_quadrant_contract.v1"
    assert contract["axis_pair"] == {
        "interior_exterior": "interior/exterior",
        "individual_collective": "individual/collective",
    }
    assert quadrants["q1"]["semantic_key"] == "interior_individual"
    assert quadrants["q1"]["aqal_position"] == "I / interior individual"
    assert quadrants["q2"]["semantic_key"] == "exterior_individual"
    assert quadrants["q2"]["aqal_position"] == "It / exterior individual"
    assert quadrants["q3"]["semantic_key"] == "interior_collective"
    assert quadrants["q3"]["aqal_position"] == "We / interior collective"
    assert quadrants["q4"]["semantic_key"] == "exterior_collective"
    assert quadrants["q4"]["aqal_position"] == "Its / exterior collective"
    assert quadrants["q3"]["perspective_id"] == "perspective-roles-relationships"
    assert "plain people roster" in quadrants["q3"]["operational_test"]
    assert "output/evidence of the root entity" in quadrants["q2"]["operational_test"]
    assert "q2 only" in contract["boundary_rule"]
    assert "they belong to q4" in contract["boundary_rule"]
    assert "Q3 = any person, role list, roster, org chart or RACI" in contract["anti_patterns"]


def test_quadrant_contract_cli_matches_python_contract() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/wiki_quadrant_contract.py"),
            "--format",
            "json",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert json.loads(result.stdout) == quadrant_contract("en")
