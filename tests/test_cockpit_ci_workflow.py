from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/wiki.yml"
AGENT_GUIDE = ROOT / "AGENTS.md"
IMPACT_REGISTRY = ROOT / "docs/references/upgrades/wiki-viva-v8/impact-registry.yaml"


def test_release_validation_prerequisites_are_fail_closed() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    audit = workflow["jobs"]["audit-and-test"]
    audit_commands = [
        step.get("run")
        for step in audit["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    guide = AGENT_GUIDE.read_text(encoding="utf-8")
    registry = yaml.safe_load(IMPACT_REGISTRY.read_text(encoding="utf-8"))
    catalog = {item["id"]: item["command"] for item in registry["gate_catalog"]}

    assert catalog["portable_python"] in audit_commands
    assert catalog["operational_pass"] in audit_commands
    assert catalog["portable_python"] in guide
    assert catalog["operational_pass"] in guide
    legacy_alias_lines = [
        line.strip()
        for command in audit_commands
        for line in command.splitlines()
        if line.strip().startswith(("python ", "pip "))
    ]
    assert legacy_alias_lines == []


def test_required_browser_release_uses_explicit_trusted_runner_authority() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    policy = workflow["jobs"]["cockpit_visual_runner_policy"]
    job = workflow["jobs"]["cockpit-visual"]

    assert workflow["permissions"] == {"contents": "read"}
    assert policy["runs-on"] == "ubuntu-latest"
    policy_env = policy["env"]
    assert policy_env["EVENT_NAME"] == "${{ github.event_name }}"
    assert policy_env["HEAD_REPOSITORY"] == (
        "${{ github.event.pull_request.head.repo.full_name }}"
    )
    assert policy_env["REF"] == "${{ github.ref }}"
    assert policy_env["REPOSITORY"] == "${{ github.repository }}"
    assert policy_env["STRICT_VISUAL_RUNNER"] == (
        "${{ vars.WIKI_VIVA_STRICT_VISUAL_RUNNER }}"
    )
    policy_commands = "\n".join(
        step.get("run", "") for step in policy["steps"] if isinstance(step, dict)
    )
    assert "WIKI_VIVA_STRICT_VISUAL_RUNNER" in policy_commands
    assert "HEAD_REPOSITORY" in policy_commands
    assert "REPOSITORY" in policy_commands
    assert "refs/heads/main" in policy_commands
    assert "wiki-viva-strict-visual-*" in policy_commands
    assert "fork code" in policy_commands
    assert "exit 1" in policy_commands

    assert job["needs"] == [
        "audit-and-test",
        "cockpit-v8",
        "cockpit_visual_runner_policy",
    ]
    assert job["if"] == (
        "${{ needs.audit-and-test.result == 'success' && "
        "needs.cockpit_visual_runner_policy.result == 'success' }}"
    )
    assert job["runs-on"] == [
        "self-hosted",
        "macOS",
        "ARM64",
        "${{ vars.WIKI_VIVA_STRICT_VISUAL_RUNNER }}",
    ]
    checkout = next(
        step for step in job["steps"] if step.get("uses") == "actions/checkout@v5"
    )
    assert checkout["with"]["persist-credentials"] is False
    commands = [
        step.get("run")
        for step in job["steps"]
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]
    assert "npm run test:e2e:release" in commands
    upload = next(
        step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v7"
    )
    assert upload["with"]["if-no-files-found"] == "error"
