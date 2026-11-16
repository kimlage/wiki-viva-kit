"""Issue #519: a first sync leaves no managed Markdown link without a target.

Runs the real default sync from this kit's committed revision into a fresh
synthetic consumer that holds only the consumer-owned scaffold, then runs the
consumer's own copied link audit. Kit-only infrastructure (for example the CI
workflow, which is never installed into a consumer) must be referenced through
a stable upstream URL instead of a local relative link. CI is never enabled in
the consumer by the sync.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "scripts/wiki_sync_from_kit.py"

# Files the consumer owns (blocked from or absent in the sync manifest) and
# that kit skills legitimately link to.
CONSUMER_SCAFFOLD = {
    "AGENTS.md": "# Synthetic consumer instructions\n",
    "README.md": "# Synthetic consumer\n",
    "wiki.config.yaml": "audit: {}\n",
    "wiki.targets.yaml": "targets: []\n",
    ".skills/README.md": "# Synthetic consumer skills index\n",
}


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def test_first_sync_leaves_no_unresolved_managed_link(tmp_path: Path) -> None:
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    _git(consumer, "init", "-q")
    _git(consumer, "config", "user.email", "tests@example.invalid")
    _git(consumer, "config", "user.name", "Wiki Tests")
    for rel, text in CONSUMER_SCAFFOLD.items():
        path = consumer / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(consumer, "add", ".")
    _git(consumer, "commit", "-qm", "synthetic consumer scaffold")
    env = {**os.environ, "PATH": f"{Path(sys.executable).parent}:{os.environ.get('PATH', '')}"}

    synced = subprocess.run(
        [sys.executable, str(SYNC), "--kit", str(ROOT), "--consumer", str(consumer)],
        text=True, capture_output=True, env=env,
    )
    assert synced.returncode == 0, synced.stderr
    assert not (consumer / ".github/workflows").exists(), "sync must never enable consumer CI"
    _git(consumer, "add", "-A")

    audited = subprocess.run(
        [sys.executable, "scripts/wiki_audit.py", "--only", "clickable_local_links"],
        cwd=consumer, text=True, capture_output=True, env=env,
    )
    missing = [line for line in audited.stdout.splitlines() if "link target does not exist" in line]
    assert missing == []
    assert audited.returncode == 0, audited.stdout + audited.stderr
