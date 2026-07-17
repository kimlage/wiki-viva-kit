from __future__ import annotations

import os
import resource
import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator


def _rss_bytes() -> int | None:
    try:
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ValueError, OSError):
        return None
    # macOS reports bytes; Linux reports KiB.
    return int(value if os.uname().sysname == "Darwin" else value * 1024)


@dataclass
class TelemetryRecorder:
    samples: list[dict[str, Any]] = field(default_factory=list)

    def observe(self, name: str, duration_ns: int, metrics: dict[str, Any] | None = None) -> None:
        self.samples.append(
            {
                "stage": name,
                "duration_ms": round(duration_ns / 1_000_000, 3),
                "rss_bytes": _rss_bytes(),
                **(metrics or {}),
            }
        )

    @contextmanager
    def stage(self, name: str, **metrics: Any) -> Iterator[dict[str, Any]]:
        started = time.perf_counter_ns()
        dynamic: dict[str, Any] = {}
        try:
            yield dynamic
        finally:
            self.observe(name, time.perf_counter_ns() - started, {**metrics, **dynamic})


def tree_stats(root: Path) -> dict[str, int]:
    files = 0
    size = 0
    for path in root.rglob("*") if root.exists() else ():
        if path.is_file() and not path.is_symlink():
            files += 1
            size += path.stat().st_size
    return {"files": files, "bytes": size}


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    if not root.exists():
        return digest.hexdigest()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or ".git" in path.relative_to(root).parts:
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        with path.open("rb") as handle:
            while block := handle.read(1024 * 1024):
                digest.update(block)
    return digest.hexdigest()
