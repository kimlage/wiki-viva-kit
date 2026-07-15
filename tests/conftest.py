"""Phase-1 test policy for the retired v8 certification state machine."""

from __future__ import annotations

from pathlib import Path

import pytest


RETIRED_CERTIFICATION_TEST_MODULES = frozenset(
    {
        "test_release_receipt.py",
        "test_upgrade.py",
        "test_upgrade_lane_handoff_workflow.py",
        "test_upgrade_lanes.py",
        "test_upgrade_package_v3.py",
        "test_wiki_node_workspace.py",
        "test_wiki_toolchain_probe.py",
        "test_wiki_upgrade_cli.py",
        "test_wiki_visual_evidence.py",
    }
)

RETIRED_REASON = (
    "retired v8 certification state machine; deletion is deferred to the "
    "separate phase-2 simplification PR"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Keep retired coverage visible while removing it from the release gate."""

    retired = pytest.mark.retired
    skipped = pytest.mark.skip(reason=RETIRED_REASON)
    for item in items:
        if Path(str(item.fspath)).name in RETIRED_CERTIFICATION_TEST_MODULES:
            item.add_marker(retired)
            item.add_marker(skipped)
