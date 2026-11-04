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
import re
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


def _request_for(paths: WikiPaths, source_id: str, request_path: str | None = None) -> dict[str, object] | None:
    if request_path is not None:
        if not request_path:
            raise ValueError('empty request selection')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id):
            raise ValueError('invalid source identity')
        candidate = Path(request_path)
        if not candidate.is_absolute():
            candidate = paths.root / candidate
        legacy = paths.extraction_events / f'{source_id}-llm-context-request.json'
        if candidate == legacy:
            from wiki_core.traversal import require_wiki_path
            require_wiki_path(paths.root, candidate.relative_to(paths.root).as_posix())
            request = json.loads(candidate.read_text(encoding='utf-8'))
            if not isinstance(request, dict) or request.get('source_id') != source_id or request.get('folder_request_id'):
                raise ValueError('selected legacy request differs from source')
            return request
        from wiki_core.llm.context_pass import load_local_request
        request = load_local_request(paths, candidate)
        if request.get('source_id') != source_id:
            raise ValueError('selected request differs from source')
        return request
    requests = [r for r in load_requests(paths, root=paths.root) if str(r.get('source_id')) == source_id]
    if len(requests) > 1 or any(r.get('folder_request_id') for r in requests):
        raise ValueError('select an exact contextual request')
    return requests[0] if requests else None


def consolidate_one(
    source_id: str, *, emit_event: bool, packet: bool, source_page: str | None,
    source_ref: str | None, context: str, date: dt.date, force: bool,
    request_path: str | None = None, candidates: list[str] | None = None, repo_selections=None,
) -> int:
    import hashlib
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    from wiki_core.traversal import require_wiki_boundaries
    request = _request_for(paths, source_id, request_path)
    if request is None:
        print('ERROR: no emitted context request for source', file=sys.stderr)
        return 1
    from wiki_core.llm.context_pass import is_local_folder_request
    if is_local_folder_request(request) and not request.get('folder_request_id'):
        print('ERROR: older local request lacks folder binding; re-prepare and re-read it', file=sys.stderr)
        return 1
    if emit_event and not (str(source_page or '').strip() or str(source_ref or '').strip()):
        print('ERROR: event requires --source-page or --source-ref; no output written', file=sys.stderr)
        return 1
    if request.get('folder_request_id'):
        from wiki_core.llm.context_pass import ingestion_block_context
        package = request['block_context_package']
        current = ingestion_block_context(ROOT, config, {}, [], entry_folder=package['entry_folder'],
            entry_index=package['entry_index'], context_max_bytes=request['request_limits']['context_max_bytes'],
            repo_selections=repo_selections, expected_documents=package['documents'])
        if context != request.get('source_context') or current != package:
            print('ERROR: selected folder context changed; no output written', file=sys.stderr)
            return 1
    elif repo_selections is not None:
        raise ValueError('repository selection requires a contextual request')
    if not deep_read_complete(request, paths.llm_cache, root=ROOT):
        print('ERROR: deep read incomplete; record every result first', file=sys.stderr)
        return 1
    # Reject a vanished result on the second read instead of publishing a partial event.
    aggregated = aggregate_results(request, paths.llm_cache, root=ROOT)
    request_id = request.get('folder_request_id')
    if candidates and not request_id:
        print('ERROR: explicit candidates require a contextual request', file=sys.stderr)
        return 1
    source_digest = hashlib.sha256(source_id.encode()).hexdigest()
    packet_name = f'folder-{source_digest}-{request_id}{PACKET_SUFFIX}' if request_id else f'{source_id}{PACKET_SUFFIX}'
    packet_file = paths.extraction_events / packet_name
    require_wiki_boundaries(ROOT, directories=(paths.extraction_events, paths.llm_cache),
                            files=(packet_file,) if packet else ())
    # Local requests inspect only explicit candidate paths, including an empty
    # list; legacy callers retain their historical global catalog and FTS.
    packet_data = build_packet(aggregated, ROOT, config, paths,
                               candidates=(candidates or []) if request_id else None) if packet or emit_event else None
    markdown = None
    target = None
    if emit_event:
        event_dir = paths.ingest_events_dir
        require_wiki_boundaries(ROOT, directories=(event_dir,))
        if not event_dir.is_dir():
            raise ValueError('configured events directory unavailable')
        existing = find_event_for_source(paths, source_id, root=ROOT, request_id=request_id)
        if existing is not None and not force:
            print('ERROR: event already exists; use --force to overwrite', file=sys.stderr)
            return 1
        target = existing or (event_dir / (f'{date.isoformat()}-{source_digest}-{request_id}.md'
                            if request_id else f'{date.isoformat()}-{_source_slug(source_id)}.md'))
        require_wiki_boundaries(ROOT, files=(target,))
        if existing is None and target.exists():
            print('ERROR: event destination already exists; preserved', file=sys.stderr)
            return 1
        # Construct and validate everything before either output is written.
        markdown = build_event_markdown(aggregated, config=config, context=context, date=date,
            source_page=source_page, source_ref=source_ref, event_dir=event_dir, root=ROOT,
            impact=dict(packet_data.get('impact') or {}) if packet_data else None)
    packet_text = json.dumps(packet_data, ensure_ascii=False, indent=2, sort_keys=True) + '\n' if packet else None
    if request_id and packet and packet_file.exists():
        if packet_file.read_text(encoding='utf-8') != packet_text:
            print('ERROR: existing integration packet differs; preserved', file=sys.stderr)
            return 1
    if packet:
        paths.extraction_events.mkdir(parents=True, exist_ok=True)
        require_wiki_boundaries(ROOT, files=(packet_file,))
        if request_id:
            if not packet_file.exists():
                with packet_file.open('x', encoding='utf-8') as stream:
                    stream.write(packet_text)
        else:
            packet_file.write_text(packet_text, encoding='utf-8')
        print(packet_file.relative_to(ROOT).as_posix())
    if emit_event:
        require_wiki_boundaries(ROOT, files=(target,))
        if request_id and not force:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(markdown)
        else:
            target.write_text(markdown, encoding='utf-8')
        print(target.relative_to(ROOT).as_posix())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    config = load_config(ROOT)
    parser.add_argument("--source", help="source_id to consolidate")
    parser.add_argument("--request", help="exact retained contextual request; does not grant access")
    parser.add_argument("--candidate", action="append", default=[], help="explicit local candidate page; repeat as needed")
    parser.add_argument("--repo", nargs=4, action="append", metavar=("ROOT", "IDENTITY", "REVISION", "PATH"),
                        help="repeat each explicitly authorized independent Git selection")
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
        try:
            pending = pending_consolidations(ROOT, config)
        except (ValueError, OSError):
            print('wiki_consolidate: derived_path_crosses_repository_boundary', file=sys.stderr)
            return 2
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
    try:
        return consolidate_one(
            args.source,
            emit_event=args.emit_event,
            packet=args.packet,
            source_page=args.source_page,
            source_ref=args.source_ref,
            context=args.context,
            date=dt.date.fromisoformat(args.date),
            force=args.force,
            request_path=args.request,
            candidates=args.candidate,
            repo_selections=args.repo,
        )
    except (ValueError, OSError):
        print('wiki_consolidate: operation stopped; inspect possible partial changes', file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
