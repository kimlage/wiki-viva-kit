from __future__ import annotations

from pathlib import Path


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
