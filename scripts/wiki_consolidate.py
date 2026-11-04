#!/usr/bin/env python3
"""Consolidate a deep-read source into the wiki (the integration half).

Usage:
  python3 scripts/wiki_consolidate.py --max-age-days <days> [--folder-candidate <path>] < request.json
  python3 scripts/wiki_consolidate.py --mode v1 --source <source_id> --emit-event --packet
  python3 scripts/wiki_consolidate.py --mode v1 --check
  python3 scripts/wiki_consolidate.py --mode v1 --all-pending

The default folder mode prepares a reviewable proposal from explicitly selected
v2 inputs and never writes or claims closure. The historical event/check flow
requires --mode v1; that gate does not cover folder-v2 ingestion.

In v1, --emit-event generates the normalized EVENT page from the recorded deep read
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
import os
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
    prepare_folder_consolidation,
    _source_slug,
)
from wiki_core.paths import WikiPaths


def _request_for(paths: WikiPaths, source_id: str) -> dict[str, object] | None:
    for request in load_requests(paths):
        if str(request.get("source_id")) == source_id and request.get("context_binding_version") != 2:
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
    packet_data = build_packet(aggregated, ROOT, config, paths) if (packet or emit_event) else None

    if packet:
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
            impact=dict(packet_data.get("impact") or {}) if packet_data else None,
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
    parser.add_argument("--mode", choices=("folder", "v1"), default="folder",
                        help="folder proposal by default; v1 selects the historical global flow")
    parser.add_argument("--source", help="legacy source_id to consolidate (v1 only)")
    parser.add_argument("--all-pending", action="store_true", help="list every pending consolidation (JSON)")
    parser.add_argument("--emit-event", action="store_true", help="generate the normalized event from llm-cache")
    parser.add_argument("--packet", action="store_true", help="emit the integration packet (gitignored)")
    parser.add_argument("--source-page", help="repo-relative path of the canonical source page (linked in the event)")
    parser.add_argument("--source-ref", help="page_id of the canonical source page (source_ref in the event)")
    parser.add_argument("--context", help="legacy event context (v1 only)")
    parser.add_argument("--date", help="legacy event date (v1 only)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing event for the source")
    parser.add_argument("--check", action="store_true", help="rc 1 while any consolidation is pending (CI)")
    parser.add_argument("--folder-preview", action="store_true",
                        help="compatibility alias for the default folder proposal")
    parser.add_argument("--folder-candidate", action="append", default=[],
                        help="explicit authorized wiki page to include in the folder preview")
    parser.add_argument("--max-age-days", type=int, help="explicit source freshness policy for folder preview")
    args = parser.parse_args()

    if args.mode == "folder":
        if (args.check or args.all_pending or args.source or args.emit_event or args.packet
                or args.source_page or args.source_ref or args.force or args.context or args.date):
            parser.error("legacy consolidation and its global check require --mode v1; folder closure is not established by this command")
        if args.max_age_days is None:
            parser.error("folder proposal requires --max-age-days and explicit request/results JSON on stdin")
        try:
            from wiki_core.context_selection import strict_json_loads
            from wiki_core.folder_coordination_v2 import FolderHostBinding
            host_root = os.environ.get('WIKI_FOLDER_INGEST_HOST_ROOT', '').strip()
            folders = os.environ.get('WIKI_FOLDER_INGEST_HOST_FOLDERS', '').strip()
            if not host_root or not folders:
                raise ValueError('host unavailable')
            configured = strict_json_loads(os.environ.get('WIKI_FOLDER_INGEST_HOST_REPOSITORIES', '[]'))
            if not isinstance(configured, list):
                raise ValueError('invalid repository bindings')
            binding = FolderHostBinding(Path(host_root), tuple(item.strip() for item in folders.split(',')),
                                        tuple(tuple(row) for row in configured))
            raw = sys.stdin.buffer.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('input budget exceeded')
            payload = strict_json_loads(raw.decode('utf-8'))
            if (not isinstance(payload, dict) or not {'request', 'results', 'page_metadata'} <= set(payload)
                    or set(payload) - {'request', 'results', 'page_metadata', 'query_packet', 'query_result'}):
                raise ValueError('invalid input')
            preview = prepare_folder_consolidation(ROOT, binding, payload['request'], payload['results'],
                        candidates=args.folder_candidate, max_age_days=args.max_age_days,
                        page_metadata=payload['page_metadata'], query_packet=payload.get('query_packet'),
                        query_result=payload.get('query_result'))
        except (ValueError, OSError, TypeError, KeyError, AttributeError):
            print(json.dumps({'status': 'blocked', 'reason': 'folder_consolidation_unavailable'}), file=sys.stderr)
            return 1
        print(json.dumps(preview, ensure_ascii=False, sort_keys=True))
        return 0
    if args.folder_preview or args.folder_candidate or args.max_age_days is not None:
        parser.error("folder proposal options are incompatible with --mode v1")

    if args.check or args.all_pending:
        pending = pending_consolidations(ROOT, config)
        print(json.dumps({"coverage": "legacy_v1_only", "pending": pending, "total": len(pending)}, ensure_ascii=False, indent=2))
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
        context=args.context or config.default_context,
        date=dt.date.fromisoformat(args.date) if args.date else dt.date.today(),
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
