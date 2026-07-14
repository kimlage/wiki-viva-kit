from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/wiki.yml"


def test_required_browser_release_uses_hardware_capable_runner() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["cockpit-visual"]

    assert job["runs-on"] == "macos-15"
    commands = [
        step.get("run")
        for step in job["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    assert "npm run test:e2e:release" in commands
