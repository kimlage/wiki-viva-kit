#!/usr/bin/env python3
"""Synthetic ``codex`` CLI for tests — emulates ``codex exec - --json -o final``.

It reads the brief from stdin, streams a few canned JSONL events to stdout,
edits a file inside ``--cd`` (so the runner sees a real changeset), and writes a
final message to the ``-o`` path. Behaviour is tunable via env vars:

* CODEX_SHIM_TARGET  — repo-relative file to append a marker line to
                       (default: the first ``memories/**/*.md`` found).
* CODEX_SHIM_SLEEP   — seconds to sleep mid-run (lets a cancel test interrupt).
* CODEX_SHIM_LEAK    — if set, emit a fake secret so redaction can be asserted.
* CODEX_SHIM_RC      — exit code (default 0); nonzero simulates a Codex failure.
* CODEX_SHIM_NOEDIT  — if set, make NO file change (simulates an empty result).
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def main() -> int:
    args = sys.argv[1:]
    cd = Path.cwd()
    final_path = None
    for i, arg in enumerate(args):
        if arg == "--cd" and i + 1 < len(args):
            cd = Path(args[i + 1])
        if arg == "-o" and i + 1 < len(args):
            final_path = Path(args[i + 1])

    brief = sys.stdin.read()
    _emit({"type": "thread.started", "brief_chars": len(brief)})
    if os.environ.get("CODEX_SHIM_LEAK"):
        # A token-shaped string the redactor must scrub before it reaches disk.
        _emit({"type": "item.completed", "item": {"type": "agent_message",
                "text": "using OPENAI_API_KEY=sk-test1234567890ABCDEFisagreatsecretvalue"}})

    sleep = os.environ.get("CODEX_SHIM_SLEEP")
    if sleep:
        time.sleep(float(sleep))

    if not os.environ.get("CODEX_SHIM_NOEDIT"):
        target = os.environ.get("CODEX_SHIM_TARGET")
        path = None
        if target:
            path = cd / target
        else:
            candidates = sorted((cd / "memories").rglob("*.md"))
            path = candidates[0] if candidates else None
        if path and path.is_file():
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\n<!-- codex shim edit -->\n")
            _emit({"type": "item.completed", "item": {"type": "file_change", "path": str(path)}})

    rc = int(os.environ.get("CODEX_SHIM_RC", "0"))
    _emit({"type": "turn.completed" if rc == 0 else "turn.failed", "returncode": rc})

    if final_path is not None:
        final_path.write_text("Codex shim: appended a verification marker to the target page.\n", encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
