#!/usr/bin/env python3
"""Garbage collection of orphaned derived ingestion artifacts (finding 13).

Each VERSION of a source generates a new `source_id` (content digest), so the
manifest/text/chunks/request of old versions pile up forever in
data/derived. This command identifies and (optionally) removes the artifacts whose
`source_id` is no longer referenced by any LIVE (neither superseded nor rejected)
ingestion proposal, and prunes the FTS index. Proposals already moved to
`arquivo/` are non-live by design (the scan is flat, on purpose).

Safe by default:
  - DRY-RUN: only lists the orphans. Use --apply to remove.
  - If no live source is found (e.g., repo without proposals), NEVER deletes —
    it cannot tell a live one from an orphan; it only reports.

Examples:
  python3 scripts/wiki_gc.py            # list orphans
  python3 scripts/wiki_gc.py --apply    # remove orphans and prune the index
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.index.sqlite import prune_index
from wiki_core.paths import WikiPaths

REQUEST_SUFFIX = "-llm-context-request.json"

# Terminal states whose sources are NOT live: superseded (replaced by a newer
# version) and rejected (proposal denied) — neither is consulted again, so
# their derived artifacts are eligible for collection.
NON_LIVE_STATES = {"superseded", "rejected"}


def _frontmatter_value(text: str, key: str) -> str | None:
    in_fm = False
    for line in text.splitlines():
        if line.strip() == "---":
            if in_fm:
                break
            in_fm = True
            continue
        if in_fm and line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return None


def live_source_ids(root: Path, paths: WikiPaths) -> set[str]:
    """source_ids referenced by LIVE ingestion proposals.

    Live = top-level proposal whose gate_state is not in NON_LIVE_STATES
    (superseded/rejected). Pages physically archived under ``arquivo/`` are
    deliberately NOT scanned (flat ``glob``, not ``rglob``): archiving is a
    terminal state, so their sources are non-live by design.
    """
    ingest_dir = root / paths.config.paths["memory_root"] / "sistema" / "ingestao"
    live: set[str] = set()
    if not ingest_dir.exists():
        return live
    for md in ingest_dir.glob("*.md"):
        text = md.read_text(encoding="utf-8")
        if (_frontmatter_value(text, "gate_state") or "") in NON_LIVE_STATES:
            continue
        ref = _frontmatter_value(text, "manifest_ref")
        if ref:
            live.add(Path(ref).stem)
    return live


def _source_id_of(path: Path) -> str:
    name = path.name
    if name.endswith(REQUEST_SUFFIX):
        return name[: -len(REQUEST_SUFFIX)]
    return path.stem


def find_orphans(paths: WikiPaths, live: set[str]) -> dict[str, list[Path]]:
    dirs = {
        "source-manifests": paths.source_manifests,
        "source-text": paths.source_text,
        "chunks": paths.chunks,
        "extraction-events": paths.extraction_events,
    }
    orphans: dict[str, list[Path]] = {}
    for label, directory in dirs.items():
        if not directory.exists():
            continue
        found = [
            p for p in sorted(directory.glob("*.json")) if _source_id_of(p) not in live
        ]
        if found:
            orphans[label] = found
    return orphans


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="remove the orphans (default: list only)")
    args = parser.parse_args(argv)

    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    live = live_source_ids(ROOT, paths)
    orphans = find_orphans(paths, live)
    total = sum(len(v) for v in orphans.values())

    report = {
        "live_source_ids": len(live),
        "orphan_files": total,
        "by_dir": {k: [str(p.relative_to(ROOT)) for p in v] for k, v in orphans.items()},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))

    if not args.apply:
        if total:
            print(f"DRY-RUN: {total} orphan file(s); use --apply to remove.", file=sys.stderr)
        return 0

    if not live:
        print(
            "REFUSED: no live source found (no proposals with manifest_ref); "
            "not deleting so as not to destroy valid artifacts. Run without --apply to inspect.",
            file=sys.stderr,
        )
        return 2

    removed = 0
    for files in orphans.values():
        for path in files:
            path.unlink()
            removed += 1
    pruned = prune_index(paths.indexes / "wiki.sqlite", live)
    print(
        json.dumps(
            {"removed_files": removed, "pruned_index_sources": pruned.get("pruned_sources", 0)},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
