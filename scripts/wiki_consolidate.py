#!/usr/bin/env python3
"""Consolidate a deep-read source into the wiki (the integration half).

Usage:
  python3 scripts/wiki_consolidate.py --max-age-days <days> [--folder-candidate <path>] < request.json
  python3 scripts/wiki_consolidate.py --mode v1 --source <source_id> --emit-event --packet
  python3 scripts/wiki_consolidate.py --mode v1 --check
  python3 scripts/wiki_consolidate.py --mode v1 --all-pending

Folder options select a reviewable proposal from explicitly selected v2 inputs
and never write or claim closure. The existing event/check flow remains the
default without folder options; its gate does not cover folder-v2 ingestion.

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


class RequestSelectionError(ValueError):
    """The source request cannot be selected unambiguously."""


def _request_for(paths: WikiPaths, source_id: str, *, request_id: str | None = None) -> dict[str, object] | None:
    if request_id is not None:
        import re
        from wiki_core.context_selection import strict_json_loads
        from wiki_core.folder_request_identity_v2 import request_identity, request_identity_path
        from wiki_core.traversal import require_wiki_boundaries
        if (not isinstance(source_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,511}', source_id)
                or not isinstance(request_id, str) or not re.fullmatch(r'[0-9a-f]{64}', request_id)):
            raise RequestSelectionError('invalid request selection')
        path = request_identity_path(paths, source_id, request_id)
        require_wiki_boundaries(paths.root, directories=(paths.extraction_events,), files=(path,))
        if not path.exists():
            # A historical request may still use its source-qualified filename.
            # This checks only that exact file, never an inventory fallback.
            path = paths.extraction_events / f'{source_id}-llm-context-request.json'
            require_wiki_boundaries(paths.root, files=(path,))
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2_000_000:
            return None
        with path.open('rb') as stream:
            content = stream.read(2_000_001)
        if len(content) > 2_000_000:
            raise RequestSelectionError('selected request exceeds byte limit')
        request = strict_json_loads(content.decode('utf-8'))
        if (not isinstance(request, dict) or request.get('source_id') != source_id
                or request.get('context_binding_version') == 2
                or request.get('folder_request_id') not in (None, request_id)
                or request_identity(request) != request_id):
            raise RequestSelectionError('selected request differs')
        return request
    matches = [request for request in load_requests(paths, root=paths.root, strict=True)
               if str(request.get('source_id')) == source_id and request.get('context_binding_version') != 2]
    if len(matches) > 1:
        raise RequestSelectionError('ambiguous source request; select an exact request')
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
    request_id: str | None = None,
) -> int:
    config = load_config(ROOT)
    paths = WikiPaths(ROOT, config)
    from wiki_core.traversal import require_wiki_boundaries
    request = _request_for(paths, source_id, request_id=request_id)
    if request is None:
        print(f"ERROR: no emitted context request for source_id {source_id}", file=sys.stderr)
        return 1
    declared_id = request.get('folder_request_id')
    if declared_id is not None:
        from wiki_core.folder_request_identity_v2 import request_identity
        if request_identity(request) != declared_id:
            raise RequestSelectionError('selected request identity differs')
        request_id = declared_id
    suffix = f'-{request_id}' if request_id else ''
    output_source = _source_slug(source_id, bounded=True) if request_id else source_id
    event_source = _source_slug(source_id, bounded=request_id is not None)
    packet_file = paths.extraction_events / f"{output_source}{suffix}{PACKET_SUFFIX}"
    directories = [paths.extraction_events, paths.llm_cache]
    files = [packet_file] if packet else []
    if emit_event:
        directories.append(paths.ingest_events_dir)
        files.append(paths.ingest_events_dir / f"{date.isoformat()}-{event_source}{suffix}.md")
    require_wiki_boundaries(ROOT, directories=directories, files=files)
    if emit_event and request_id is None and paths.ingest_events_dir.is_dir():
        require_wiki_boundaries(ROOT, files=paths.ingest_events_dir.glob('*.md'))
    if not deep_read_complete(request, paths.llm_cache, root=ROOT):
        print(
            f"ERROR: deep read incomplete for {source_id} — run the LLM pass and "
            f"--record-result first (see wiki_llm_context_pass.py)",
            file=sys.stderr,
        )
        return 1
    aggregated = aggregate_results(request, paths.llm_cache, root=ROOT,
                                   **({'require_complete': True} if request_id is not None else {}))
    packet_data = build_packet(aggregated, ROOT, config, paths) if (packet or emit_event) else None

    def revalidate_selection():
        if request_id is not None and _request_for(paths, source_id, request_id=request_id) is None:
            raise ValueError('selected request changed; existing work was preserved')

    if packet:
        revalidate_selection()
        paths.extraction_events.mkdir(parents=True, exist_ok=True)
        require_wiki_boundaries(ROOT, files=(packet_file,))
        packet_text = json.dumps(packet_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if request_id:
            try:
                with packet_file.open('x', encoding='utf-8') as stream:
                    stream.write(packet_text)
            except FileExistsError:
                if packet_file.is_symlink() or packet_file.read_text(encoding='utf-8') != packet_text:
                    raise ValueError('existing request packet differs; preserved') from None
        else:
            packet_file.write_text(packet_text, encoding='utf-8')
        print(packet_file.relative_to(ROOT).as_posix())

    if emit_event:
        revalidate_selection()
        existing = find_event_for_source(paths, source_id, request_id=request_id, root=ROOT)
        if existing is not None and (not force or request_id is not None):
            if request_id is not None:
                print('ERROR: existing selected request event was preserved', file=sys.stderr)
                return 1
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
            request_id=request_id,
        )
        target = existing if existing is not None else (
            event_dir / f"{date.isoformat()}-{event_source}{suffix}.md"
        )
        require_wiki_boundaries(ROOT, files=(target,))
        if request_id is not None:
            with target.open('x', encoding='utf-8') as stream:
                stream.write(markdown)
        else:
            target.write_text(markdown, encoding="utf-8")
        print(target.relative_to(ROOT).as_posix())
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    config = load_config(ROOT)
    parser.add_argument("--mode", choices=("folder", "v1"),
                        help="explicitly select folder proposal or the existing global flow")
    parser.add_argument("--source", help="legacy source_id to consolidate (v1 only)")
    parser.add_argument("--request-id", help="select one exact semantic request when the source is ambiguous")
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
                        help="explicitly select a folder proposal")
    parser.add_argument("--folder-candidate", action="append", default=[],
                        help="explicit authorized wiki page to include in the folder preview")
    parser.add_argument("--max-age-days", type=int, help="explicit source freshness policy for folder preview")
    args = parser.parse_args()
    if args.mode is None:
        args.mode = 'folder' if args.folder_preview or args.folder_candidate or args.max_age_days is not None else 'v1'

    if args.mode == "folder":
        if (args.check or args.all_pending or args.source or args.request_id or args.emit_event or args.packet
                or args.source_page or args.source_ref or args.force or args.context or args.date):
            parser.error("folder and existing consolidation options cannot be mixed; folder closure is not established by the global check")
        if args.max_age_days is None:
            parser.error("folder proposal requires --max-age-days and explicit request/results JSON on stdin")
        try:
            from wiki_core.context_selection import strict_json_loads
            from wiki_core.folder_ingestion_v2 import host_binding_from_environment
            binding = host_binding_from_environment()
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
    if args.folder_preview or args.folder_candidate or args.max_age_days is not None:
        parser.error("folder proposal options are incompatible with --mode v1")

    if (args.check or args.all_pending) and args.request_id:
        parser.error('--request-id requires source consolidation')
    if args.check or args.all_pending:
        try:
            pending = pending_consolidations(ROOT, config)
        except (ValueError, OSError):
            print('wiki_consolidate: pending consolidation unavailable; check paths and ambiguous events', file=sys.stderr)
            return 2
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
    try:
        return consolidate_one(
            args.source,
            emit_event=args.emit_event,
            packet=args.packet,
            source_page=args.source_page,
            source_ref=args.source_ref,
            context=args.context or config.default_context,
            date=dt.date.fromisoformat(args.date) if args.date else dt.date.today(),
            force=args.force,
            request_id=args.request_id,
        )
    except RequestSelectionError:
        print('wiki_consolidate: ambiguous or invalid request; select an exact request with --request-id', file=sys.stderr)
        return 2
    except (ValueError, OSError):
        print('wiki_consolidate: operation stopped; inspect possible partial changes', file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
