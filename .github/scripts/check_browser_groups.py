"""Prove CI groups partition the existing functional Playwright collection."""
from collections import Counter
import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "apps/wiki-cockpit"
GROUPS = ("desktop-1", "desktop-2", "visual-mobile", "cross-browser")
# Hardware frame-time evidence is a separate local GPU run, as before.
PROJECTS = ("chromium-desktop", "webkit-keyboard", "webkit-mobile",
            "chromium-fallback", "firefox-smoke")


def test_keys(report):
    """Include project identity: the same test legitimately runs in two browsers."""
    def walk(suite):
        for spec in suite.get("specs", []):
            for test in spec["tests"]:
                yield (test["projectName"], spec["file"], spec["line"],
                       spec["column"], spec["title"])
        for child in suite.get("suites", []):
            yield from walk(child)

    if report.get("errors"):
        raise ValueError("Playwright collection failed")
    return [key for suite in report["suites"] for key in walk(suite)]


def check_partition(expected, groups):
    if not expected or any(not group for group in groups):
        raise ValueError("Empty collection or CI group")
    expected_counts = Counter(expected)
    actual_counts = Counter(key for group in groups for key in group)
    if expected_counts != actual_counts:
        missing = sum((expected_counts - actual_counts).values())
        extra = sum((actual_counts - expected_counts).values())
        raise ValueError(f"CI collection changed: {missing} missing, {extra} extra/duplicate")


def collect(group=None):
    config = "playwright.ci.config.ts" if group else "playwright.config.ts"
    command = ["node", "node_modules/@playwright/test/cli.js", "test",
               f"--config={config}", "--list", "--reporter=json"]
    if group is None:
        command.extend(f"--project={project}" for project in PROJECTS)
    env = {**os.environ, "CI": "1"}
    if group:
        env["WIKI_CI_BROWSER_GROUP"] = group
    result = subprocess.run(command, cwd=APP, env=env, check=True,
                            text=True, capture_output=True, timeout=120)
    return test_keys(json.loads(result.stdout))


def main():
    expected = collect()
    groups = {group: collect(group) for group in GROUPS}
    check_partition(expected, list(groups.values()))
    print(json.dumps({"total": len(expected),
                      "groups": {name: len(keys) for name, keys in groups.items()},
                      "missing_or_duplicate": 0}, indent=2))


if __name__ == "__main__":
    main()
