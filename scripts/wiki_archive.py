#!/usr/bin/env python3
"""Physically archives RESOLVED ingestion proposals (and their events).

The ingestion directory is flat and the immutable history was re-audited forever
(scaling finding). Proposals in a terminal state (superseded/rejected) are
moved to `memorias/sistema/ingestao/arquivo/` (events to
`arquivo/eventos/`), with:

- a gate transition to `archived` recorded in the state machine;
- `stale_exempt: true` in the frontmatter (an archived page does not trigger a freshness alarm);
- rewriting of the moved page's RELATIVE links (depth +1);
- updating of references in other memory pages that link to the file.

Safe by default: dry-run lists what would be moved; use --apply to move.

Examples:
  python3 scripts/wiki_archive.py             # dry-run
  python3 scripts/wiki_archive.py --apply
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.gate import write_state  # noqa: E402

INGEST_DIR = ROOT / "memorias" / "sistema" / "ingestao"
ARCHIVE_DIR = INGEST_DIR / "arquivo"
ARCHIVE_EVENTS_DIR = ARCHIVE_DIR / "eventos"

# Resolved states: already superseded/rejected — nothing else transitions from them
# (except to archived). `approved`/`published` stay: they are still consulted.
RESOLVED_STATES = {"superseded", "rejected"}


def frontmatter_value(text: str, key: str) -> str:
    lines = text.splitlines()
    # Frontmatter only counts when the document STARTS with '---' (line 0);
    # a '---' later in the body (horizontal rule) must not open a fake block.
    if not lines or lines[0].strip() != "---":
        return ""
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith(f"{key}:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def shift_relative_links(text: str, depth: int = 1) -> str:
    """Adds ``depth`` levels of `../` to relative links (page moved down a folder).

    Only adjusts hrefs that start with `../` or a simple relative path; anchors,
    absolute URLs and links in the same destination directory are not touched.
    """
    prefix = "../" * depth

    def fix(match: re.Match[str]) -> str:
        label, href = match.group(1), match.group(2)
        if re.match(r"^[a-z]+://|^#|^mailto:", href):
            return match.group(0)
        return f"[{label}]({prefix}{href})"

    return re.sub(r"\[([^\]]*)\]\(([^)]+)\)", fix, text)


def add_stale_exempt(text: str) -> str:
    if "stale_exempt:" in text:
        return text
    lines = text.splitlines(keepends=True)
    # Frontmatter must START at line 0; without it there is nothing to annotate
    # (a '---' in the body is a horizontal rule, not a frontmatter fence).
    if not lines or lines[0].strip() != "---":
        return text
    # insert before the closing '---' (end of frontmatter)
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            lines.insert(i, "stale_exempt: true\n")
            break
    return "".join(lines)


def rewrite_inbound_links(old_rel: str, new_rel: str, *, apply: bool) -> list[str]:
    """Updates, in the other memory pages, the links that pointed to the
    moved file (matches by file name; recomputes the relative path)."""
    import os  # noqa: PLC0415

    name = Path(old_rel).name
    touched: list[str] = []
    for md in (ROOT / "memorias").rglob("*.md"):
        rel = md.relative_to(ROOT).as_posix()
        if rel == new_rel:
            continue
        text = md.read_text(encoding="utf-8")
        changed = False

        # 1. Relative markdown links that resolve to the moved file.
        pattern = re.compile(r"\[([^\]]*)\]\(((?:\.\./|\./)?[^)#]*" + re.escape(name) + r")(#[^)]*)?\)")

        def fix(match: re.Match[str]) -> str:
            nonlocal changed
            href = match.group(2)
            fragment = match.group(3) or ""
            resolved = (md.parent / href).resolve()
            if resolved != (ROOT / old_rel).resolve():
                return match.group(0)
            changed = True
            new_href = os.path.relpath(ROOT / new_rel, md.parent).replace(os.sep, "/")
            return f"[{match.group(1)}]({new_href}{fragment})"

        new_text = pattern.sub(fix, text)

        # 2. References by FULL path relative to the root (e.g., evidence_refs
        # in the frontmatter) — direct replacement old_rel -> new_rel.
        if old_rel in new_text:
            new_text = new_text.replace(old_rel, new_rel)
            changed = True

        if changed:
            touched.append(rel)
            if apply:
                md.write_text(new_text, encoding="utf-8")
    return touched


def archive_one(path: Path, *, apply: bool) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    state = frontmatter_value(text, "gate_state")
    event_ref = frontmatter_value(text, "event_ref")
    moves: list[tuple[Path, Path, Path]] = [(path, ARCHIVE_DIR / path.name, INGEST_DIR)]
    if event_ref:
        event_path = ROOT / event_ref
        if event_path.is_file() and event_path.parent.name == "eventos":
            moves.append((event_path, ARCHIVE_EVENTS_DIR / event_path.name, event_path.parent))

    inbound: list[str] = []
    if apply:
        # Preconditions FIRST (fail before any state is written): every source must
        # be tracked and no destination may already exist — a failed git mv after
        # write_state used to leave gate_state=archived stranded in ingestao/.
        for src, dst, _base in moves:
            tracked = subprocess.run(
                ["git", "ls-files", "--error-unmatch", str(src.relative_to(ROOT))],
                cwd=ROOT,
                capture_output=True,
            )
            if tracked.returncode != 0:
                raise SystemExit(f"ERROR: {src.relative_to(ROOT)} is not tracked by git; commit it before archiving")
            if dst.exists():
                raise SystemExit(f"ERROR: destination already exists: {dst.relative_to(ROOT)}")

        event_moved = len(moves) > 1
        touched: list[Path] = []
        for src, dst, _base in moves:
            dst.parent.mkdir(parents=True, exist_ok=True)
            body = src.read_text(encoding="utf-8")
            body = shift_relative_links(body, depth=1)
            body = add_stale_exempt(body)
            if src == path and event_moved and event_ref:
                # the frontmatter event_ref follows the moved event
                new_event_rel = (ARCHIVE_EVENTS_DIR / Path(event_ref).name).relative_to(ROOT).as_posix()
                body = body.replace(f"event_ref: {event_ref}", f"event_ref: {new_event_rel}")
            # git mv preserves history and keeps the index coherent (the auditor reads
            # tracked_files via git; write+unlink left the old path in the index).
            try:
                subprocess.run(
                    ["git", "mv", str(src.relative_to(ROOT)), str(dst.relative_to(ROOT))],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                raise SystemExit(f"ERROR: git mv failed: {exc.stderr.strip()}") from exc
            dst.write_text(body, encoding="utf-8")
            touched.append(dst)
            inbound += rewrite_inbound_links(
                src.relative_to(ROOT).as_posix(), dst.relative_to(ROOT).as_posix(), apply=True
            )
        # Gate transition LAST, after all filesystem work succeeded.
        archived_path = ARCHIVE_DIR / path.name
        if state in RESOLVED_STATES:
            write_state(archived_path, "archived", reason="physical archiving (wiki_archive)")
        # Stage the rewritten files so the rename in the index matches the content
        # (a partial `git commit` without -a used to ship the OLD body under the
        # new path, with broken relative links).
        stage = [str(p_.relative_to(ROOT)) for p_ in touched] + sorted(set(inbound))
        if stage:
            subprocess.run(["git", "add", "--", *stage], cwd=ROOT, check=True, capture_output=True)
    else:
        for src, dst, _base in moves:
            inbound += rewrite_inbound_links(
                src.relative_to(ROOT).as_posix(), dst.relative_to(ROOT).as_posix(), apply=False
            )
    return {
        "proposal": path.name,
        "state": state,
        "moves": [f"{s.relative_to(ROOT)} -> {d.relative_to(ROOT)}" for s, d, _ in moves],
        "inbound_links_updated": sorted(set(inbound)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="actually move (default: dry-run)")
    args = parser.parse_args(argv)

    candidates = []
    for md in sorted(INGEST_DIR.glob("*.md")):
        state = frontmatter_value(md.read_text(encoding="utf-8"), "gate_state")
        if state in RESOLVED_STATES:
            candidates.append(md)

    if not candidates:
        print("nothing to archive (no proposal in a resolved state)")
        return 0

    import json  # noqa: PLC0415

    results = [archive_one(md, apply=args.apply) for md in candidates]
    print(json.dumps({"applied": args.apply, "archived": results}, ensure_ascii=False, indent=2))
    if not args.apply:
        print(f"DRY-RUN: {len(results)} proposal(s) would be archived; use --apply.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
