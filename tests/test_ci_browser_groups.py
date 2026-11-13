"""A green CI matrix must not silently omit or duplicate browser coverage."""
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "ci_browser_groups", ROOT / ".github/scripts/check_browser_groups.py")
groups = importlib.util.module_from_spec(spec)
spec.loader.exec_module(groups)


def test_partition_preserves_browser_identity():
    expected = [("chromium", "same test"), ("webkit", "same test")]
    groups.check_partition(expected, [[expected[0]], [expected[1]]])
    with pytest.raises(ValueError, match="missing.*extra/duplicate"):
        groups.check_partition(expected, [[expected[0]], [expected[0]]])


@pytest.mark.parametrize("actual", [[], [["a"]], [["a"], ["b", "b"]], [["a", "b"], []]])
def test_partition_refuses_missing_duplicate_or_empty_groups(actual):
    with pytest.raises(ValueError):
        groups.check_partition(["a", "b"], actual)


def test_failed_collection_cannot_be_treated_as_empty_success():
    with pytest.raises(ValueError, match="collection failed"):
        groups.test_keys({"errors": [{"message": "invalid test"}], "suites": []})


def test_workflow_runs_every_verified_group_and_requires_the_matrix():
    jobs = yaml.safe_load((ROOT / ".github/workflows/wiki.yml").read_text())["jobs"]
    assert jobs["browser-journeys"]["strategy"]["matrix"]["group"] == list(groups.GROUPS)
    gate = jobs["cockpit-browser"]
    assert gate["needs"] == ["browser-journeys"]
    assert gate["if"] == "${{ always() }}"
    assert "needs.browser-journeys.result" in gate["steps"][0]["env"]["RESULT"]
    assert gate["steps"][0]["run"] == 'test "$RESULT" = "success"'


@pytest.mark.parametrize("failed_mode", ["normal", "public-export"])
def test_parallel_audits_wait_for_both_and_propagate_either_failure(tmp_path, failed_mode):
    workflow = yaml.safe_load((ROOT / ".github/workflows/wiki.yml").read_text())
    step = next(item for item in workflow["jobs"]["audit-and-test"]["steps"]
                if item.get("name") == "Wiki and public-export audits")
    fake_python = tmp_path / "python3"
    fake_python.write_text('''#!/bin/bash
mode=normal
if [[ "$*" == *--public-export* ]]; then mode=public-export; fi
echo "finished-$mode"
test "$mode" != "$FAILED_MODE"
''')
    fake_python.chmod(0o755)
    result = subprocess.run(
        ["bash", "-e", "-c", step["run"].replace("/tmp/", str(tmp_path) + "/")],
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
             "FAILED_MODE": failed_mode}, text=True, capture_output=True)
    assert result.returncode == 1
    assert "finished-normal" in result.stdout
    assert "finished-public-export" in result.stdout
