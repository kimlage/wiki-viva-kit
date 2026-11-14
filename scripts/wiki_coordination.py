#!/usr/bin/env python3
"""Read canonical coordinator routes or prepare revision-bound agent context."""
from __future__ import annotations
import json
import io
import os
import stat
import re
import sys
from pathlib import Path
from _common import ROOT
from wiki_core.context_selection import strict_json_loads
from wiki_core.cli_errors import SafeArgumentParser
from wiki_core.context_policy import revision
from wiki_core.config import load_config
from wiki_core.coordination import coordination_index, profile_packet_migration, transition_dialogue_action
from wiki_core.coordination_context import (CoordinationBinding, ProtectedCoordinationError,
    prepare_packet, protected_source_stage, blocker_response, _policy, capability)




class _EventTooLarge(ValueError):
    pass


def _read_dialogue_event(path: Path):
    """Read one bounded event; reject special files before reading on POSIX."""
    flags = os.O_RDONLY | getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_BINARY', 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('event input unavailable')
        if os.fstat(stream.fileno()).st_size > 16_000:
            raise _EventTooLarge('event file exceeds limit')
        raw = stream.read(16_001)
    if len(raw) > 16_000:
        raise _EventTooLarge('event file exceeds limit')
    # Match Path.read_text's platform-default encoding and newline handling.
    with io.TextIOWrapper(io.BytesIO(raw)) as text:
        return json.loads(text.read())


def main() -> None:
    parser = SafeArgumentParser(prog="wiki_coordination.py", description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--context-id", help="Explicit context ID; source stages can select a host-bound context from cwd.")
    parser.add_argument("--approved-revision", help="Current approved commit SHA for protected packet mode.")
    parser.add_argument("--packet-request", type=Path, help="Explicit task selection JSON for protected packet mode.")
    parser.add_argument("--folder", help="Physical entry folder for a folder-authority task packet.")
    parser.add_argument("--index", help="Explicit context index for a folder-authority task packet.")
    parser.add_argument("--integrator-context", help="Explicit authorized ancestor that owns protected artifacts.")
    parser.add_argument('--trusted-context', action='append', default=[], metavar='CONTEXT',
        help='additional producer context selected explicitly by the trusted local operator')
    parser.add_argument("--source-stage", choices=('prepare', 'record', 'consolidate', 'compare', 'inspect'),
        help="Trusted local operator source stage; stage payload is read from stdin.")
    parser.add_argument('--show-host-binding', action='store_true',
        help='Read back the host-configured binding without repository roots or identities.')
    parser.add_argument("--profile")
    parser.add_argument("--action-id")
    parser.add_argument("--action-path", help="Exact canonical page path; required for dialogue events.")
    parser.add_argument("--revision", default="HEAD", help="Immutable Git content revision for profile context.")
    parser.add_argument("--event-file", type=Path, help="Append one dialogue event from a JSON file (trusted local adapter).")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--as-operator", action="store_true", help="Record an operator event rather than a coordinator event.")
    args = parser.parse_args()
    if args.show_host_binding:
        if (args.source_stage or args.context_id or args.approved_revision or args.packet_request or args.profile
                or args.folder or args.index or args.integrator_context or args.action_id or args.event_file
                or args.expected_sha256 or args.as_operator or args.action_path or args.trusted_context):
            parser.error('host binding readback does not accept stage or task options')
        try:
            print(json.dumps(capability(args.root.resolve(), CoordinationBinding.from_environment()), ensure_ascii=False))
        except (ValueError, OSError, RuntimeError):
            print(json.dumps({'ok': False, 'available': False, 'reason': 'host_binding_unavailable'}))
            raise SystemExit(1)
        return
    if args.source_stage:
        if (not args.approved_revision or args.packet_request or args.profile
                or args.action_id or args.event_file or args.expected_sha256 or args.as_operator or args.action_path):
            parser.error('source stage requires approved-revision; provide stage JSON on stdin')
        try:
            if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', args.approved_revision):
                raise ProtectedCoordinationError('coordination_invalid_request')
            # The local CLI trusts its operator; discovering a folder is not a
            # host grant. Implicit contexts require an existing host binding.
            binding = CoordinationBinding.from_environment()
            if binding is None:
                if not args.context_id:
                    raise ProtectedCoordinationError('coordination_not_available')
                contexts = tuple(dict.fromkeys([args.context_id, args.integrator_context or args.context_id, *args.trusted_context]))
                binding = CoordinationBinding(contexts, 'refs/remotes/origin/main', 'wiki.config.yaml')
            root = args.root.resolve()
            raw = sys.stdin.read(2_000_001)
            if len(raw.encode('utf-8')) > 2_000_000:
                raise ValueError('request too large')
            payload = strict_json_loads(raw)
            if not isinstance(payload, dict) or {'context_id', 'approved_revision', 'artifact_context'} & set(payload):
                raise ValueError('invalid source stage payload')
            for name, explicit in (('entry_folder', args.folder), ('entry_index', args.index)):
                if explicit is not None:
                    if name in payload and payload[name] != explicit:
                        raise ValueError('conflicting source stage selection')
                    payload[name] = explicit
            if 'entry_folder' not in payload:
                from wiki_core.traversal import require_wiki_path
                relative = Path.cwd().resolve(strict=True).relative_to(root)
                folder = relative.as_posix() if relative.parts else '.'
                if not require_wiki_path(root, folder).is_dir():
                    raise ValueError('context folder unavailable')
                payload['entry_folder'] = folder
            from wiki_core.context_policy import load_policy
            try:
                policy = load_policy(root, args.approved_revision, binding.manifest, trusted_ref=binding.trusted_ref)
            except (ValueError, OSError) as exc:
                raise ProtectedCoordinationError('coordination_policy_unavailable') from exc
            if getattr(policy, 'format_version', None) != 'folder':
                raise ProtectedCoordinationError('coordination_policy_unavailable')
            folder = payload['entry_folder']
            context_id = args.context_id or ('.' if folder == '.' else policy.owner_of(folder))
            _policy(root, binding, context_id, args.approved_revision)
            if 'entry_index' not in payload:
                entry_index = policy._context_indexes.get(context_id)
                if entry_index is None:
                    raise ValueError('context index unavailable')
                payload['entry_index'] = entry_index
            if args.integrator_context:
                payload['artifact_context'] = args.integrator_context
            result = protected_source_stage(root, binding, args.source_stage,
                {**payload, 'context_id': context_id, 'approved_revision': args.approved_revision})
        except (ProtectedCoordinationError, ValueError, OSError, RuntimeError) as error:
            safe_error = error if isinstance(error, ProtectedCoordinationError) else ProtectedCoordinationError('coordination_invalid_request')
            print(json.dumps(blocker_response(safe_error), ensure_ascii=False))
            raise SystemExit(1)
        print(json.dumps({**result, 'caller_boundary': 'trusted_local_operator'}, ensure_ascii=False))
        return
    protected = bool(args.context_id or args.approved_revision or args.packet_request)
    if protected:
        if not (args.context_id and args.approved_revision and args.packet_request) or args.profile or args.action_id or args.event_file or args.expected_sha256 or args.as_operator or args.action_path or args.integrator_context:
            parser.error("protected mode requires context-id, approved-revision and packet-request; legacy profile/event options are separate")
        try:
            from wiki_core.traversal import is_protected_artifact
            if is_protected_artifact(args.packet_request):
                raise ValueError('protected request requires bound dispatch')
            binding = CoordinationBinding.from_environment()
            if binding is None:
                binding = CoordinationBinding(tuple(dict.fromkeys([args.context_id, *args.trusted_context])),
                                              'refs/remotes/origin/main', 'wiki.config.yaml')
            root = args.root.resolve()
            _policy(root, binding, args.context_id, args.approved_revision)
            if args.packet_request.stat().st_size > 1_048_576:
                raise ValueError("request too large")
            request = strict_json_loads(args.packet_request.read_text(encoding="utf-8"))
            folder = args.folder
            if folder is None:
                try: relative = Path.cwd().resolve().relative_to(root)
                except ValueError: relative = None
                folder = relative.as_posix() if relative is not None and relative.parts else args.context_id
            selection = {'entry_folder': folder}
            if args.index is not None: selection['entry_index'] = args.index
            result = prepare_packet(root, binding, {"context_id": args.context_id,
                "approved_revision": args.approved_revision, "content_revision": revision(root, args.revision),
                "task": request, **selection})
        except (ProtectedCoordinationError, ValueError, OSError, RuntimeError) as error:
            safe_error = error if isinstance(error, ProtectedCoordinationError) else ProtectedCoordinationError("coordination_invalid_request")
            print(json.dumps(blocker_response(safe_error), ensure_ascii=False))
            raise SystemExit(1)
        print(json.dumps({**result, 'caller_boundary': 'trusted_local_operator'}, ensure_ascii=False))
        return
    if args.folder or args.index or args.integrator_context or args.trusted_context:
        parser.error('folder and index require protected packet mode')
    if args.event_file and (not args.profile or not args.action_id or not args.expected_sha256 or not args.action_path):
        parser.error("--event-file requires --profile, --action-id, --action-path and --expected-sha256")
    if (args.expected_sha256 or args.as_operator or args.action_path) and not args.event_file:
        parser.error("write options require --event-file")
    if args.action_id and not args.profile:
        parser.error("--action-id requires --profile")
    if args.profile and not args.event_file:
        print(json.dumps(profile_packet_migration(), ensure_ascii=False))
        return
    root = args.root.resolve()
    if not args.event_file:
        from wiki_core.web.snapshot import build_snapshot
        result = coordination_index(root, build_snapshot(root, load_config(root)))
    if args.event_file:
        try:
            event = _read_dialogue_event(args.event_file)
        except _EventTooLarge:
            parser.error("event file exceeds limit")
        if not isinstance(event, dict) or event.get("coordinator") != args.profile:
            parser.error("event coordinator must equal selected profile")
        result = transition_dialogue_action(
            root, args.action_path, args.action_id, event,
            expected_sha256=args.expected_sha256, as_operator=args.as_operator).to_dict()

    print(json.dumps(result, ensure_ascii=False, indent=2))


def _run_cli() -> None:
    try:
        main()
    except Exception:
        # Direct callers retain original exception types and details. The CLI
        # reports no exception text and does not imply rollback after a write.
        print('coordination failed; if a transition was attempted, inspect action state before retry', file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    _run_cli()
