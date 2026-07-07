from __future__ import annotations

import importlib.util
import json
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE = KIT_ROOT / "apps/wiki-cockpit/public/sample-snapshot"


def _demo_module():
    spec = importlib.util.spec_from_file_location("wiki_build_demo", KIT_ROOT / "scripts/wiki_build_demo.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_stage_fixtures_are_monotonic_subsets(tmp_path: Path) -> None:
    demo = _demo_module()
    previous: set[str] = set()
    for stage in range(demo.FINAL_STAGE + 1):
        target = tmp_path / str(stage)
        target.mkdir()
        ids = set(demo.write_fixture(target, stage))
        assert previous <= ids, f"stage {stage} lost pages from stage {stage - 1}"
        previous = ids
    # The final stage is the full cast.
    full = tmp_path / "full"
    full.mkdir()
    assert set(demo.write_fixture(full, demo.FINAL_STAGE)) == previous


def test_root_attachments_grow_with_the_arc() -> None:
    demo = _demo_module()
    assert demo.root_attachments(1) == {}
    stage2 = demo.root_attachments(2)
    assert [b["id"] for b in stage2["blocks"]] == ["wiki.block.quadrants.v1"]
    stage4 = demo.root_attachments(4)
    assert "wiki.block.relations.v1" in [b["id"] for b in stage4["blocks"]]
    assert "packages" not in stage4  # stage 4 is QUIET on purpose
    stage5 = demo.root_attachments(5)
    assert stage5["packages"] == ["gamification"]


def test_committed_stage_snapshots_are_consistent() -> None:
    """The committed artifacts (what the tutorial actually loads) must hold the
    contract: monotonic page subsets, stage arc materializing the interface,
    final stage identical to the full demo."""
    stages_dir = SAMPLE / "stages"
    manifest = json.loads((stages_dir / "stages.json").read_text(encoding="utf-8"))
    final = manifest["final_stage"]
    previous: set[str] = set()
    for entry in manifest["stages"]:
        stage_dir = SAMPLE / entry["dir"]
        pages = json.loads((stage_dir / "pages.json").read_text(encoding="utf-8"))
        ids = {page["id"] for page in pages["pages"]}
        assert previous <= ids
        previous = ids
        assert (stage_dir / "block_stacks.json").exists()
    # Final stage == full demo (same page set).
    full_pages = json.loads((SAMPLE / "pages.json").read_text(encoding="utf-8"))
    assert previous == {page["id"] for page in full_pages["pages"]}

    # The tutorial's dramatic beats, straight from the artifacts:
    def root_ui(stage: int) -> dict:
        payload = json.loads((SAMPLE / f"stages/{stage}/block_stacks.json").read_text(encoding="utf-8"))
        return payload["anchors"]["root-alex-rivera"]

    assert root_ui(1)["interface"]["views"]["default"] == "radar"          # bare root: no quadrant map
    assert root_ui(2)["interface"]["has_quadrants"] is True                # lenses attach
    assert root_ui(4)["interface"]["missions"]["active"] is False          # world knows...
    assert root_ui(4)["derived"]["relations"]["due"]                       # ...Marina is overdue
    assert root_ui(5)["interface"]["missions"]["active"] is True           # ...and now it asks
    assert final == 8

    final_blocks = json.loads((SAMPLE / "block_stacks.json").read_text(encoding="utf-8"))
    anchors = final_blocks["anchors"]
    assert "block-library-lens" in anchors
    template_q = anchors["block-library-lens"]["derived"]["quadrant_assignments"]
    assert "claim-template-library-purpose" in template_q["q1"]
    assert "artifact-template-library-example" in template_q["q2"]
    assert "meeting-template-library-review" in template_q["q3"]
    assert "process-template-library-governance" in template_q["q4"]
    system_q = anchors["hub-sistema"]["derived"]["quadrant_assignments"]
    assert "block-library-lens" in system_q["q4"]
    root_q = anchors["root-alex-rivera"]["derived"]["quadrant_assignments"]
    assert "block-library-lens" not in root_q["q4"]
    assert "claim-template-library-purpose" not in root_q["q1"]
    company_q = anchors["company-clearpath-labs"]["derived"]["quadrant_assignments"]
    assert "claim-clearpath-market-signal" in company_q["q1"]
    assert "source-clearpath-customer-interviews" in company_q["q2"]
    assert "dashboard-clearpath-activation" in company_q["q2"]
    assert "role-clearpath-customer-success-lead" in company_q["q3"]
    assert "rule-clearpath-release-gate" in company_q["q4"]
