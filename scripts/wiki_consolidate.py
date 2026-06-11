#!/usr/bin/env python3
"""Consolidate a deep-read source into the wiki (the integration half).

Usage:
  python3 scripts/wiki_consolidate.py --source <source_id> --emit-event --packet
  python3 scripts/wiki_consolidate.py --source <source_id> --source-page memories/sources/x.md
  python3 scripts/wiki_consolidate.py --check
  python3 scripts/wiki_consolidate.py --all-pending

--emit-event generates the normalized EVENT page from the recorded deep read
(quadrants filled from llm-cache — never placeholders) with consolidated_into:[]
for the agent to close during integration. --packet emits the integration packet
(gitignored): related pages, overlapping claims and potential conflicts per
claim/entity. --check fails (rc 1) while any deep-read-complete source lacks an
event or has an event whose consolidated_into is empty — ingestion is only done
when the wiki's concepts reflect the new information.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wiki_core.config import load_config
from wiki_core.consolidate import (
    PACKET_SUFFIX,
    aggregate_results,
    build_event_markdown,
    build_packet,
    deep_read_complete,
    find_event_for_source,
    load_requests,
    pending_consolidations,
    _source_slug,
)
from wiki_core.paths import WikiPaths


def _request_for(paths: WikiPaths, source_id: str) -> dict[str, object] | None:
    for request in load_requests(paths):
        if str(request.get("source_id")) == source_id:
            return request
    return None


def consolidate_one(
    source_id: str,
    *,
    emit_event: bool,
    packet: bool,
    source_page: str | None,
    source_ref: str | None,
    context: str,
    date: dt.date,
    force: bool,
) -> int:
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    request = _request_for(paths, source_id)
    if request is None:
        print(f"ERROR: no emitted context request for source_id {source_id}", file=sys.stderr)
        return 1
    if not deep_read_complete(request, paths.llm_cache):
        print(
            f"ERROR: deep read incomplete for {source_id} — run the LLM pass and "
            f"--record-result first (see wiki_llm_context_pass.py)",
            file=sys.stderr,
        )
        return 1
    aggregated = aggregate_results(request, paths.llm_cache)

    if packet:
        packet_data = build_packet(aggregated, ROOT, config, paths)
        paths.extraction_events.mkdir(parents=True, exist_ok=True)
        packet_file = paths.extraction_events / f"{source_id}{PACKET_SUFFIX}"
        packet_file.write_text(
            json.dumps(packet_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(packet_file.relative_to(ROOT).as_posix())

    if emit_event:
        existing = find_event_for_source(paths, source_id)
        if existing is not None and not force:
            print(
                f"ERROR: event already exists for {source_id}: "
                f"{existing.relative_to(ROOT).as_posix()} (use --force to overwrite)",
                file=sys.stderr,
            )
            return 1
        event_dir = paths.ingest_events_dir
        if not event_dir.is_dir():
            print(f"ERROR: configured events directory does not exist: {event_dir}", file=sys.stderr)
            return 1
        markdown = build_event_markdown(
            aggregated,
            config=config,
            context=context,
            date=date,
            source_page=source_page,
            source_ref=source_ref,
            event_dir=event_dir,
            root=ROOT,
        )
        target = existing if existing is not None else (
            event_dir / f"{date.isoformat()}-{_source_slug(source_id)}.md"
        )
        target.write_text(markdown, encoding="utf-8")
        print(target.relative_to(ROOT).as_posix())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    config = load_config(ROOT)
    parser.add_argument("--source", help="source_id to consolidate")
    parser.add_argument("--all-pending", action="store_true", help="list every pending consolidation (JSON)")
    parser.add_argument("--emit-event", action="store_true", help="generate the normalized event from llm-cache")
    parser.add_argument("--packet", action="store_true", help="emit the integration packet (gitignored)")
    parser.add_argument("--source-page", help="repo-relative path of the canonical source page (linked in the event)")
    parser.add_argument("--source-ref", help="page_id of the canonical source page (source_ref in the event)")
    parser.add_argument("--context", default=config.default_context)
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--force", action="store_true", help="overwrite an existing event for the source")
    parser.add_argument("--check", action="store_true", help="rc 1 while any consolidation is pending (CI)")
    args = parser.parse_args()

    if args.check or args.all_pending:
        pending = pending_consolidations(ROOT, config)
        print(json.dumps({"pending": pending, "total": len(pending)}, ensure_ascii=False, indent=2))
        if args.check and pending:
            print(
                f"wiki_consolidate: {len(pending)} source(s) awaiting consolidation — "
                f"integrate and fill consolidated_into (see the wiki-viva skill)",
                file=sys.stderr,
            )
            return 1
        return 0

    if not args.source:
        parser.error("--source is required (or use --check / --all-pending)")
    if not (args.emit_event or args.packet):
        parser.error("nothing to do: pass --emit-event and/or --packet")
    return consolidate_one(
        args.source,
        emit_event=args.emit_event,
        packet=args.packet,
        source_page=args.source_page,
        source_ref=args.source_ref,
        context=args.context,
        date=dt.date.fromisoformat(args.date),
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
