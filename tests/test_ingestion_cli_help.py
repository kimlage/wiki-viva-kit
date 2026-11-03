"""Public command examples distinguish approved and compatibility modes."""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("script,actions", [
    ("wiki_ingest.py", [""]),
    ("wiki_llm_context_pass.py", ["--emit-request", "--record-result", "--check"]),
])
def test_help_shows_bound_examples_and_labels_compatibility(script, actions):
    output = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), "--help"],
        check=True, capture_output=True, text=True,
    ).stdout
    approved = output.split("Approved-context example", 1)[1].split("Working-tree compatibility", 1)[0]
    examples = re.sub(r"\\\n\s*", " ", approved).splitlines()
    commands = [line.strip() for line in examples if line.strip().startswith("python3 ")]
    for action in actions:
        command = next(line for line in commands if action in line)
        assert all(flag in command for flag in ("--source", "--context", "--approved-revision", "--policy-context"))
    assert "Working-tree compatibility example" in output
    assert "fall" in output and "compatibility" in output
