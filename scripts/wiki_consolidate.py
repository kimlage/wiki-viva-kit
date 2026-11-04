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


def _request_for(paths: WikiPaths, source_id: str, request_path: str | None = None) -> dict[str, object] | None:
    if request_path is not None:
        from wiki_core.folder_request_identity_v2 import load_retained_request
        request = load_retained_request(paths.root, paths, request_path)
        if (request.get('source_id') != source_id or request.get('context_binding_version') != 1
                or (request.get('block_context_package') or {}).get('policy_mode') != 'working_tree_folder_entry'):
            raise ValueError('selected request differs from source')
        return request
    matches = [request for request in load_requests(paths, include_scoped=False)
               if str(request.get('source_id')) == source_id and request.get('context_binding_version') != 2]
    if len(matches) > 1:
        raise ValueError('multiple context requests require an exact request selection')
    return matches[0] if matches else None


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
    request_path: str | None = None,
    candidates: list[str] | None = None,
) -> int:
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    try:
        request = _request_for(paths, source_id, request_path)
    except (ValueError, OSError, TypeError, KeyError):
        print("ERROR: select one exact retained context request for this source", file=sys.stderr)
        return 1
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
    scoped = (request.get('block_context_package') or {}).get('policy_mode') == 'working_tree_folder_entry'
    if candidates and not scoped:
        print('ERROR: explicit candidates require a selected working-tree folder request', file=sys.stderr)
        return 1
    if scoped and context != request.get('source_context'):
        print('ERROR: selected context differs from the retained request', file=sys.stderr)
        return 1
    try:
        if scoped:
            from wiki_core.folder_context import read_folder_entry
            package = request['block_context_package']
            actual = read_folder_entry(ROOT, package['entry_folder'], package['entry_index'],
                                       max_bytes=request['request_limits']['context_max_bytes'])
            if actual != {'folder':package['entry_folder'], 'index_path':package['entry_index'],
                          'documents':package['documents']}:
                raise ValueError('working-tree context changed')
        packet_data = build_packet(aggregated, ROOT, config, paths, candidates=(candidates or []) if scoped else None) if (packet or emit_event) else None
    except (ValueError, OSError, TypeError, KeyError):
        print('ERROR: selected context or consolidation candidates unavailable', file=sys.stderr)
        return 1

    if packet:
        paths.extraction_events.mkdir(parents=True, exist_ok=True)
        request_id = request.get('folder_request_id')
        packet_file = paths.extraction_events / f"{source_id}{('-' + request_id) if request_id else ''}{PACKET_SUFFIX}"
        packet_text = json.dumps(packet_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if scoped:
            from wiki_core.folder_request_identity_v2 import _install_once
            try:
                _install_once(packet_file, packet_text)
            except FileExistsError:
                if packet_file.is_symlink() or packet_file.read_text(encoding='utf-8') != packet_text:
                    print('ERROR: existing integration packet differs and was preserved', file=sys.stderr)
                    return 1
        else:
            packet_file.write_text(packet_text, encoding="utf-8")
        print(packet_file.relative_to(ROOT).as_posix())

    if emit_event:
        request_id = request.get('folder_request_id')
        existing = find_event_for_source(paths, source_id, request_id)
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
            event_dir / f"{date.isoformat()}-{_source_slug(source_id)}{('-' + request_id) if request_id else ''}.md"
        )
        if scoped:
            try:
                from wiki_core.folder_ingestion_v2 import _check_local_boundaries
                _check_local_boundaries(ROOT, target.relative_to(ROOT).as_posix())
            except (ValueError, OSError):
                print('ERROR: event destination unavailable', file=sys.stderr)
                return 1
        if scoped and existing is None:
            try:
                with target.open('x', encoding='utf-8') as stream:
                    stream.write(markdown)
            except FileExistsError:
                print('ERROR: existing event path was preserved', file=sys.stderr)
                return 1
        else:
            target.write_text(markdown, encoding="utf-8")
        print(target.relative_to(ROOT).as_posix())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    config = load_config(ROOT)
    parser.add_argument("--mode", choices=("folder", "v1"), default="folder",
                        help="folder proposal by default; v1 selects the historical global flow")
    parser.add_argument("--source", help="legacy source_id to consolidate (v1 only)")
    parser.add_argument("--request", help="Exact retained working-tree context request (v1 only)")
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
        if (args.check or args.all_pending or args.source or args.request or args.emit_event or args.packet
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
                    or set(payload) - {'request', 'results', 'page_metadata', 'query_packet', 'query_result', 'requalify_source'}):
                raise ValueError('invalid input')
            preview = prepare_folder_consolidation(ROOT, binding, payload['request'], payload['results'],
                        candidates=args.folder_candidate, max_age_days=args.max_age_days,
                        page_metadata=payload['page_metadata'], query_packet=payload.get('query_packet'),
                        query_result=payload.get('query_result'), requalify_source=payload.get('requalify_source', False))
        except (ValueError, OSError, TypeError, KeyError, AttributeError):
            print(json.dumps({'status': 'blocked', 'reason': 'folder_consolidation_unavailable'}), file=sys.stderr)
            return 1
        print(json.dumps(preview, ensure_ascii=False, sort_keys=True))
        return 0
    if args.folder_preview or args.max_age_days is not None:
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
        request_path=args.request,
        candidates=args.folder_candidate,
    )


if __name__ == "__main__":
    sys.exit(main())
