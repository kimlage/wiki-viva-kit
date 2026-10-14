"""Shared public histories exercise backend and frontend relationship semantics."""
import json
from pathlib import Path

import pytest

from wiki_core.action_dialogue import validate_history

CASES = json.loads((Path(__file__).resolve().parents[1] /
    "apps/wiki-cockpit/src/data/fixtures/action-dialogue-relationships.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_dialogue_relationship_parity(case):
    if case["valid"]:
        validate_history(case["events"])
    else:
        with pytest.raises(ValueError, match="^invalid_action_dialogue$"):
            validate_history(case["events"])
