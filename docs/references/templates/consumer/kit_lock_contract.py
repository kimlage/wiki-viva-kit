"""Minimum consumer-owned test: kit-managed files change only through the sync.

Copy this file once to `tests/test_kit_lock.py` in a consumer that adopted the
Wiki Viva Kit with `scripts/wiki_sync_from_kit.py`. The copy is consumer-owned;
this template is kit-managed and may change at the next sync.

It checks the Git index, not unstaged edits, so the result does not depend on
line-ending conversion: every path in `kit.lock` `managed_files` must be staged
with the recorded mode and SHA-256. A local edit to a kit-owned file fails here;
the fix is a kit issue and a later sync, or reverting the edit.

The generic kit suites are not copied: they run in the kit CI at the revision
recorded in `kit.lock` (`source_sha`). Add your own tests next to this one for
every consumer-owned script, adapter and C3 migration command.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _lock() -> dict:
    path = ROOT / "kit.lock"
    assert path.is_file(), "kit.lock is missing: adopt the kit with scripts/wiki_sync_from_kit.py"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict) and isinstance(data.get("managed_files"), dict), "kit.lock has no managed_files"
    return data


def _index() -> dict[str, tuple[str, str]]:
    raw = subprocess.run(["git", "ls-files", "--stage", "-z"], cwd=ROOT, check=True,
                         stdout=subprocess.PIPE).stdout
    staged = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        meta, _, name = record.partition(b"\t")
        mode, blob, stage = meta.decode().split()
        if stage == "0":
            staged[os.fsdecode(name)] = (mode, blob)
    return staged


def _blob_digests(blobs: list[str]) -> dict[str, str]:
    if not blobs:
        return {}
    out = subprocess.run(["git", "cat-file", "--batch"], cwd=ROOT, check=True,
                         input=("\n".join(blobs) + "\n").encode(), stdout=subprocess.PIPE).stdout
    digests = {}
    for blob in blobs:
        header, _, out = out.partition(b"\n")
        size = int(header.split()[2])
        digests[blob] = hashlib.sha256(out[:size]).hexdigest()
        out = out[size + 1:]
    return digests


def test_kit_lock_records_a_source_revision():
    lock = _lock()
    source = str(lock.get("source_sha") or "")
    assert len(source) in (40, 64) and all(c in "0123456789abcdef" for c in source)


def test_kit_managed_files_match_the_lock():
    managed = _lock()["managed_files"]
    staged = _index()
    missing = sorted(path for path in managed if path not in staged)
    digests = _blob_digests(sorted({staged[path][1] for path in managed if path in staged}))
    changed = sorted(
        path for path, entry in managed.items()
        if path in staged and (staged[path][0] != str(entry.get("mode"))
                               or digests[staged[path][1]] != str(entry.get("sha256")))
    )
    assert not missing, f"kit-managed files missing from the index: {missing[:20]}"
    assert not changed, f"kit-managed files differ from kit.lock (change them in the kit, then sync): {changed[:20]}"
