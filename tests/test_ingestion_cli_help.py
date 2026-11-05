"""Public command help distinguishes folder policy from compatibility."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script,stages", [
    ("wiki_ingest.py", ["prepare"]),
    ("wiki_llm_context_pass.py", ["prepare", "record", "inspect"]),
])
def test_help_points_to_folder_stages_and_labels_compatibility(script, stages):
    output = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        check=True, capture_output=True, text=True,
    ).stdout
    approved = output.split("Approved folder-policy", 1)[1].split("Working-tree compatibility", 1)[0]
    examples = re.sub(r"\\\n\s*", " ", approved).splitlines()
    commands = [line.strip() for line in examples if line.strip().startswith("python3 ")]
    for stage in stages:
        command = next(line for line in commands if f"--source-stage {stage}" in line)
        assert "scripts/wiki_coordination.py" in command
        assert all(flag in command for flag in ("--context-id", "--approved-revision", "< STAGE.json"))
        assert "--policy-context" not in command
    assert "Working-tree compatibility example" in output
    assert "retired" in output and "falling back" in output


@pytest.mark.parametrize("script", ["wiki_ingest.py", "wiki_llm_context_pass.py"])
def test_help_redirect_matches_retired_cli_behavior(script, tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--root", str(tmp_path),
         "--source", "missing.md", "--context", "synthetic",
         "--approved-revision", "a" * 40, "--policy-context", "root"],
        capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "new approved v1 ingestion is retired" in result.stderr
    assert "wiki_coordination.py --source-stage" in result.stderr
    assert not list(tmp_path.iterdir())
