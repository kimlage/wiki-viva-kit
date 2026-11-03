#!/usr/bin/env python3
"""Read canonical coordinator routes or prepare revision-bound agent context."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from _common import ROOT
from wiki_core.context_selection import strict_json_loads
from wiki_core.config import load_config
from wiki_core.coordination import coordination_index, profile_packet_migration, transition_dialogue_action
from wiki_core.coordination_context import CoordinationBinding, ProtectedCoordinationError, prepare_packet, blocker_response


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--context-id", help="Explicit context ID for a policy-approved task packet.")
    parser.add_argument("--approved-revision", help="Current approved commit SHA for protected packet mode.")
    parser.add_argument("--packet-request", type=Path, help="Explicit task selection JSON for protected packet mode.")
    parser.add_argument("--profile")
    parser.add_argument("--action-id")
    parser.add_argument("--action-path", help="Exact canonical page path; required for dialogue events.")
    parser.add_argument("--revision", default="HEAD", help="Immutable Git content revision for profile context.")
    parser.add_argument("--event-file", type=Path, help="Append one dialogue event from a JSON file (trusted local adapter).")
    parser.add_argument("--expected-sha256")
    parser.add_argument("--as-operator", action="store_true", help="Record an operator event rather than a coordinator event.")
    args = parser.parse_args()
    protected = bool(args.context_id or args.approved_revision or args.packet_request)
    if protected:
        if not (args.context_id and args.approved_revision and args.packet_request) or args.profile or args.action_id or args.event_file or args.expected_sha256 or args.as_operator or args.action_path:
            parser.error("protected mode requires context-id, approved-revision and packet-request; legacy profile/event options are separate")
        try:
            if args.packet_request.stat().st_size > 1_048_576:
                raise ValueError("request too large")
            request = strict_json_loads(args.packet_request.read_text(encoding="utf-8"))
            binding = CoordinationBinding((args.context_id,), "refs/remotes/origin/main")
            result = prepare_packet(args.root.resolve(), binding, {"context_id": args.context_id, "approved_revision": args.approved_revision, "content_revision": args.revision, "task": request})
        except (ProtectedCoordinationError, ValueError, OSError) as error:
            safe_error = error if isinstance(error, ProtectedCoordinationError) else ProtectedCoordinationError("coordination_invalid_request")
            print(json.dumps(blocker_response(safe_error), ensure_ascii=False))
            raise SystemExit(1)
        print(json.dumps(result, ensure_ascii=False))
        return
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
        if args.event_file.stat().st_size > 16_000:
            parser.error("event file exceeds limit")
        event = json.loads(args.event_file.read_text())
        if not isinstance(event, dict) or event.get("coordinator") != args.profile:
            parser.error("event coordinator must equal selected profile")
        result = transition_dialogue_action(
            root, args.action_path, args.action_id, event,
            expected_sha256=args.expected_sha256, as_operator=args.as_operator).to_dict()

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
