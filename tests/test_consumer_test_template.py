"""Issue #529: a new consumer owns a minimum suite; the kit suites stay here.

Runs the real default sync from this kit's committed revision into a fresh
synthetic consumer, installs the kit-lock contract template as the consumer's
own test and runs it there. Synthetic data only.
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "scripts/wiki_sync_from_kit.py"
TEMPLATE = "docs/references/templates/consumer/kit_lock_contract.py"
ENV = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _pytest(consumer: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_kit_lock.py"],
                          cwd=consumer, text=True, capture_output=True, env=ENV)


def test_sync_installs_no_kit_suite_and_the_contract_template_guards_the_lock(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _git(consumer, "init", "-q")
    _git(consumer, "config", "user.email", "tests@example.invalid")
    _git(consumer, "config", "user.name", "Wiki Tests")
    (consumer / "README.md").write_text("# Synthetic consumer\n", encoding="utf-8")
    (consumer / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic consumer")

    synced = subprocess.run([sys.executable, str(SYNC), "--kit", str(ROOT), "--consumer", str(consumer)],
                            text=True, capture_output=True, env=ENV)
    assert synced.returncode == 0, synced.stderr
    managed = yaml.safe_load((consumer / "kit.lock").read_text(encoding="utf-8"))["managed_files"]
    assert TEMPLATE in managed
    assert not [p for p in managed if p.startswith(("tests/", ".github/"))], "kit suites and CI are never synced"
    assert not [p for p in managed if p.startswith("apps/wiki-cockpit/src/") and ".test." in p]

    (consumer / "tests").mkdir()
    shutil.copyfile(consumer / TEMPLATE, consumer / "tests/test_kit_lock.py")
    _git(consumer, "add", "-A")
    _git(consumer, "commit", "-qm", "adopt kit and own the minimum suite")
    passed = _pytest(consumer)
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "2 passed" in passed.stdout

    edited = consumer / "wiki_core/config.py"
    original = edited.read_bytes()
    edited.write_bytes(original + b"\n# local edit to a kit-owned file\n")
    _git(consumer, "add", "wiki_core/config.py")
    failed = _pytest(consumer)
    assert failed.returncode != 0 and "wiki_core/config.py" in failed.stdout

    edited.write_bytes(original)
    _git(consumer, "add", "wiki_core/config.py")
    _git(consumer, "update-index", "--chmod=+x", "wiki_core/config.py")
    assert _pytest(consumer).returncode != 0
    _git(consumer, "update-index", "--chmod=-x", "wiki_core/config.py")
    assert _pytest(consumer).returncode == 0

    (consumer / "kit.lock").unlink()
    missing = _pytest(consumer)
    assert missing.returncode != 0 and "kit.lock is missing" in missing.stdout


def test_setup_guide_matches_the_sync_contract() -> None:
    setup = (ROOT / ".skills/wiki-viva/reference/setup.md").read_text(encoding="utf-8")
    assert "the core's test suite" not in setup
    assert "kit's own suite must pass" not in setup
    assert "### Minimum consumer-owned tests" in setup
    assert "templates/consumer/kit_lock_contract.py" in setup
    manifest = yaml.safe_load((ROOT / "docs/references/upgrades/sync-manifest.yaml").read_text(encoding="utf-8"))
    allow = manifest["portable"]["allow"]
    assert not [p for p in allow if p.startswith(("tests", ".github"))]
    assert "docs/references/templates/consumer/**" in allow
